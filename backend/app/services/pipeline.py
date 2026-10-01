"""Per-item state machine (spec 6.2): uploaded → converting → checking → (needs_confirmation)
→ publishing → published | failed. Runs as a FastAPI background task after the upload request
and from the confirm-type and retry endpoints; ``requeue_stale_items`` restarts work left in a
non-terminal state when the process starts."""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.analyzer import Analyzer, CheckBatch, CheckItem, ExistingDocument, ItemVerdict
from app.core.config import Settings
from app.db.models import Document, Project, Upload, UploadItem, User
from app.db.session import get_sessionmaker
from app.ingestion.converters import LOW_TEXT, ConversionError, convert_file
from app.ingestion.taxonomy import Taxonomy, UnknownDocType
from app.services import audit
from app.services.publish import MARKDOWN_SUFFIX, NoChange, PublishError, publish_item
from app.storage.base import StorageError
from app.storage.select import backend_for

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("uploaded", "converting", "checking", "publishing")
NO_CHANGE_ERROR = "No change: this file is identical to the current version."
LOW_TEXT_EXPLANATION = "The file has little extractable text; the type check was skipped."
CHECK_FAILED_EXPLANATION = "The type check could not run; the selected type was kept."
PREVIEW_CHARS = 2000
_background: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class PipelineContext:
    settings: Settings
    taxonomy: Taxonomy
    analyzer: Analyzer

    @property
    def staging_root(self) -> Path:
        return Path(self.settings.staging_root)


async def transition(
    db: AsyncSession,
    item_id: uuid.UUID,
    from_statuses: Sequence[str],
    to_status: str,
    **values: Any,
) -> bool:
    """Atomically move an item between states; False when it was not in ``from_statuses``."""
    moved = await db.scalar(
        update(UploadItem)
        .where(UploadItem.id == item_id, UploadItem.status.in_(list(from_statuses)))
        .values(status=to_status, updated_at=datetime.now(UTC), **values)
        .returning(UploadItem.id)
        .execution_options(synchronize_session=False)
    )
    return moved is not None


async def _fail(
    db: AsyncSession, item_id: uuid.UUID, project_id: uuid.UUID, from_status: str, error: str
) -> None:
    """Mark an item failed. Takes ids, not ORM objects: callers may have rolled back, which
    expires loaded attributes and would trigger implicit I/O on access."""
    await transition(db, item_id, (from_status,), "failed", error=error)
    await audit.record(
        db,
        "upload_item.failed",
        project_id=project_id,
        target_type="upload_item",
        target_id=str(item_id),
        details={"error": error},
    )
    await db.commit()


async def convert_item(
    ctx: PipelineContext, maker: async_sessionmaker[AsyncSession], item_id: uuid.UUID
) -> bool:
    async with maker() as db:
        if not await transition(db, item_id, ("uploaded",), "converting"):
            return False
        await db.commit()
        item = await db.get_one(UploadItem, item_id)
        upload = await db.get_one(Upload, item.upload_id)
        project_id = upload.project_id
        path = ctx.staging_root / item.staging_path
        try:
            result = await asyncio.to_thread(convert_file, path, item.ext)
            await asyncio.to_thread(
                path.with_name(path.name + MARKDOWN_SUFFIX).write_text,
                result.markdown,
                encoding="utf-8",
            )
        except ConversionError as exc:
            await _fail(db, item_id, project_id, "converting", exc.message)
            return False
        except FileNotFoundError:
            await _fail(
                db,
                item_id,
                project_id,
                "converting",
                "Staged file is no longer available; upload the file again.",
            )
            return False
        except Exception:
            logger.exception("Conversion crashed for upload item %s", item_id)
            await _fail(db, item_id, project_id, "converting", "Conversion failed unexpectedly.")
            return False
        meta = {**result.meta.to_dict(), "warnings": list(result.warnings)}
        await transition(db, item_id, ("converting",), "checking", conversion_meta=meta)
        await db.commit()
        return True


async def _preview(ctx: PipelineContext, item: UploadItem) -> str:
    path = ctx.staging_root / item.staging_path
    text = await asyncio.to_thread(
        path.with_name(path.name + MARKDOWN_SUFFIX).read_text, encoding="utf-8"
    )
    return text[:PREVIEW_CHARS]


async def _build_batch(
    ctx: PipelineContext, db: AsyncSession, project: Project, items: Sequence[UploadItem]
) -> CheckBatch:
    existing = (
        await db.scalars(
            select(Document).where(Document.project_id == project.id, Document.is_stub.is_(False))
        )
    ).all()
    check_items = [
        CheckItem(
            item_id=item.id,
            file_name=item.original_name,
            selected_doc_type=item.selected_doc_type,
            title=item.title,
            outline=list(item.conversion_meta.get("outline", [])),
            preview=await _preview(ctx, item),
            language=item.conversion_meta.get("language"),
        )
        for item in items
    ]
    return CheckBatch(
        project_id=project.id,
        items=check_items,
        allowed_doc_types=[t.key for t in ctx.taxonomy.doc_types],
        existing_documents=[
            ExistingDocument(document_id=d.id, doc_type=d.doc_type, title=d.title) for d in existing
        ],
    )


def _valid_hint(verdict: ItemVerdict | None, known: set[uuid.UUID]) -> uuid.UUID | None:
    if verdict is None or verdict.version_of_document_id not in known:
        return None
    return verdict.version_of_document_id


def _valid_suggestion(taxonomy: Taxonomy, key: str | None) -> str | None:
    if key is None:
        return None
    try:
        return taxonomy.resolve(key).key
    except UnknownDocType:
        return None


async def check_items(
    ctx: PipelineContext,
    maker: async_sessionmaker[AsyncSession],
    upload_id: uuid.UUID,
    item_ids: Sequence[uuid.UUID],
) -> list[uuid.UUID]:
    """Run the analyzer once for the batch; return the ids that may be published now."""
    if not item_ids:
        return []
    ready: list[uuid.UUID] = []
    async with maker() as db:
        upload = await db.get_one(Upload, upload_id)
        project = await db.get_one(Project, upload.project_id)
        items = list(
            (
                await db.scalars(
                    select(UploadItem).where(
                        UploadItem.id.in_(list(item_ids)), UploadItem.status == "checking"
                    )
                )
            ).all()
        )
        to_check: list[UploadItem] = []
        for item in items:
            if LOW_TEXT in item.conversion_meta.get("warnings", []):
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "publishing",
                    type_check="skipped",
                    check_explanation=LOW_TEXT_EXPLANATION,
                )
                ready.append(item.id)
            else:
                to_check.append(item)
        await db.commit()
        if not to_check:
            return ready
        batch = await _build_batch(ctx, db, project, to_check)
        verdicts: dict[uuid.UUID, ItemVerdict] = {}
        try:
            result = await ctx.analyzer.check(batch)
            verdicts = {v.item_id: v for v in result.verdicts}
        except Exception:
            logger.exception("Type check failed for upload %s", upload_id)
        known = {d.document_id for d in batch.existing_documents}
        for item in to_check:
            verdict = verdicts.get(item.id)
            hint = _valid_hint(verdict, known)
            if verdict is None or verdict.verdict == "skipped":
                explanation = verdict.explanation if verdict else CHECK_FAILED_EXPLANATION
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "publishing",
                    type_check="skipped",
                    check_explanation=explanation,
                    version_hint_document_id=hint,
                )
                ready.append(item.id)
            elif verdict.verdict == "match":
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "publishing",
                    type_check="match",
                    check_explanation=verdict.explanation,
                    version_hint_document_id=hint,
                )
                ready.append(item.id)
            else:
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "needs_confirmation",
                    check_explanation=verdict.explanation,
                    suggested_doc_type=_valid_suggestion(ctx.taxonomy, verdict.suggested_doc_type),
                    version_hint_document_id=hint,
                )
        await db.commit()
    return ready


async def publish_item_by_id(
    ctx: PipelineContext, maker: async_sessionmaker[AsyncSession], item_id: uuid.UUID
) -> None:
    async with maker() as db:
        item = await db.get_one(UploadItem, item_id)
        if item.status != "publishing":
            return
        upload = await db.get_one(Upload, item.upload_id)
        project = await db.get_one(Project, upload.project_id)
        uploader = await db.get_one(User, upload.uploaded_by)
        project_id, uploader_id = project.id, uploader.id
        try:
            backend = backend_for(project.storage, ctx.settings)
            version = await publish_item(
                db,
                item=item,
                upload=upload,
                project=project,
                uploader=uploader,
                backend=backend,
                taxonomy=ctx.taxonomy,
                staging_root=ctx.staging_root,
            )
        except NoChange:
            await db.rollback()
            await _fail(db, item_id, project_id, "publishing", NO_CHANGE_ERROR)
            return
        except (PublishError, StorageError) as exc:
            await db.rollback()
            await _fail(db, item_id, project_id, "publishing", str(exc))
            return
        except Exception:
            logger.exception("Publishing crashed for upload item %s", item_id)
            await db.rollback()
            await _fail(db, item_id, project_id, "publishing", "Publishing failed unexpectedly.")
            return
        await transition(db, item_id, ("publishing",), "published", error=None)
        await audit.record(
            db,
            "upload_item.published",
            user_id=uploader_id,
            project_id=project_id,
            target_type="document",
            target_id=str(version.document_id),
            details={"upload_item_id": str(item_id), "version": version.version},
        )
        await db.commit()


async def run_upload(
    ctx: PipelineContext, upload_id: uuid.UUID, item_ids: Sequence[uuid.UUID] | None = None
) -> None:
    """Convert, check and publish the ``uploaded`` items of one upload (or a subset)."""
    maker = get_sessionmaker()
    async with maker() as db:
        stmt = select(UploadItem.id).where(
            UploadItem.upload_id == upload_id, UploadItem.status == "uploaded"
        )
        if item_ids is not None:
            stmt = stmt.where(UploadItem.id.in_(list(item_ids)))
        pending = list((await db.scalars(stmt.order_by(UploadItem.created_at))).all())
    converted = [item_id for item_id in pending if await convert_item(ctx, maker, item_id)]
    for item_id in await check_items(ctx, maker, upload_id, converted):
        await publish_item_by_id(ctx, maker, item_id)


async def publish_confirmed_item(ctx: PipelineContext, item_id: uuid.UUID) -> None:
    await publish_item_by_id(ctx, get_sessionmaker(), item_id)


async def requeue_stale_items(ctx: PipelineContext) -> int:
    """Reset items left mid-flight by a previous process to ``uploaded`` and run them again."""
    maker = get_sessionmaker()
    async with maker() as db:
        rows = (
            await db.execute(
                update(UploadItem)
                .where(UploadItem.status.in_(list(ACTIVE_STATUSES)))
                .values(status="uploaded", updated_at=datetime.now(UTC))
                .returning(UploadItem.upload_id)
                .execution_options(synchronize_session=False)
            )
        ).all()
        await db.commit()
    upload_ids = {upload_id for (upload_id,) in rows}
    for upload_id in upload_ids:
        task = asyncio.create_task(run_upload(ctx, upload_id))
        _background.add(task)
        task.add_done_callback(_background.discard)
    return len(rows)
