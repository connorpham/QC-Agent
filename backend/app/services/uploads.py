"""Upload intake into staging and the database, plus item actions (confirm type, retry)."""

import asyncio
import shutil
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentVersion, Project, Upload, UploadItem, User
from app.ingestion.intake import (
    IntakeLimits,
    ReadChunk,
    Rejection,
    StagedFile,
    batch_limit_reason,
    expand_zip,
    extension_rejection,
    file_extension,
    sanitize_filename,
    size_limit_reason,
    stage_stream,
)
from app.ingestion.naming import title_from_filename
from app.ingestion.taxonomy import Taxonomy, UnknownDocType
from app.schemas.uploads import UploadItemSpec
from app.services import audit

NO_CHANGE_REASON = "No change: this file is identical to the current version."


class UploadError(Exception):
    def __init__(self, message: str, rejections: Sequence[Rejection] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.rejections = list(rejections)


class ItemStateError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class IncomingFile:
    name: str
    read: ReadChunk


@dataclass(frozen=True)
class StagedItem:
    file: StagedFile
    spec: UploadItemSpec


def staging_dir_for(staging_root: Path, upload_id: uuid.UUID) -> Path:
    return staging_root / str(upload_id)


async def stage_files(
    files: Sequence[IncomingFile],
    specs: Sequence[UploadItemSpec],
    *,
    staging_dir: Path,
    limits: IntakeLimits,
) -> tuple[list[StagedItem], list[Rejection]]:
    """Stream every file into ``staging_dir`` and expand zip archives. Zip entries inherit the
    archive's spec except the title, which defaults to the entry's file name."""
    staged: list[StagedItem] = []
    rejections: list[Rejection] = []
    total = 0
    for incoming, spec in zip(files, specs, strict=True):
        name = sanitize_filename(incoming.name)
        rejection = extension_rejection(name)
        if rejection is not None:
            rejections.append(rejection)
            continue
        ext = file_extension(name) or ""
        dest = staging_dir / "incoming" / f"{uuid.uuid4().hex}.{ext}"
        result = await stage_stream(incoming.read, dest, max_bytes=limits.max_file_bytes)
        if result is None:
            rejections.append(Rejection(name, size_limit_reason(limits)))
            continue
        size, sha256 = result
        total += size
        if total > limits.max_batch_bytes:
            await asyncio.to_thread(dest.unlink, missing_ok=True)
            rejections.append(Rejection(name, batch_limit_reason(limits)))
            continue
        file = StagedFile(name=name, ext=ext, path=dest, size=size, sha256=sha256)
        if ext != "zip":
            staged.append(StagedItem(file=file, spec=spec))
            continue
        if spec.intent == "version":
            await asyncio.to_thread(dest.unlink, missing_ok=True)
            rejections.append(Rejection(name, "Zip archives cannot be uploaded as a new version."))
            continue
        entries, zip_rejections = await asyncio.to_thread(
            expand_zip, file, staging_dir / "items", limits
        )
        rejections.extend(zip_rejections)
        entry_spec = spec.model_copy(update={"title": None})
        staged.extend(StagedItem(file=entry, spec=entry_spec) for entry in entries)
    return staged, rejections


async def _version_target_rejection(
    db: AsyncSession, project: Project, role: str, item: StagedItem
) -> Rejection | None:
    spec = item.spec
    if spec.target_document_id is None:
        return Rejection(item.file.name, "A target document is required for a new version.")
    target = await db.get(Document, spec.target_document_id)
    hidden = target is None or target.project_id != project.id or target.is_stub
    if hidden or (role == "client" and target is not None and target.visibility != "shared"):
        return Rejection(item.file.name, "Target document not found.")
    assert target is not None  # noqa: S101 - narrowed above for the type checker
    if target.doc_type != spec.doc_type:
        return Rejection(
            item.file.name,
            "The new version must have the same document type as the existing document.",
        )
    current = await db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == target.id,
            DocumentVersion.version == target.current_version,
        )
    )
    if current is not None and current.sha256 == item.file.sha256:
        return Rejection(item.file.name, NO_CHANGE_REASON)
    return None


async def create_upload(
    db: AsyncSession,
    *,
    project: Project,
    uploader: User,
    role: str,
    upload_id: uuid.UUID,
    staged: Sequence[StagedItem],
    rejections: Sequence[Rejection],
    taxonomy: Taxonomy,
    staging_root: Path,
) -> tuple[Upload, list[Rejection]]:
    """Create the upload and one item per accepted file. Client uploads are forced to
    ``shared``. Raises ``UploadError`` when no file was accepted."""
    all_rejections = list(rejections)
    upload = Upload(id=upload_id, project_id=project.id, uploaded_by=uploader.id)
    db.add(upload)
    await db.flush()
    accepted = 0
    for item in staged:
        spec = item.spec
        try:
            doc_type = taxonomy.resolve(spec.doc_type)
        except UnknownDocType:
            all_rejections.append(
                Rejection(item.file.name, f"Unknown document type {spec.doc_type!r}.")
            )
            continue
        if spec.intent == "version":
            rejection = await _version_target_rejection(db, project, role, item)
            if rejection is not None:
                all_rejections.append(rejection)
                continue
        db.add(
            UploadItem(
                upload_id=upload.id,
                original_name=item.file.name,
                ext=item.file.ext,
                size=item.file.size,
                sha256=item.file.sha256,
                staging_path=item.file.path.relative_to(staging_root).as_posix(),
                selected_doc_type=doc_type.key,
                title=(spec.title or title_from_filename(item.file.name))[:200],
                intent=spec.intent,
                target_document_id=spec.target_document_id if spec.intent == "version" else None,
                visibility="shared" if role == "client" else spec.visibility,
                status="uploaded",
            )
        )
        accepted += 1
    if accepted == 0:
        await db.rollback()
        await asyncio.to_thread(
            shutil.rmtree, staging_dir_for(staging_root, upload_id), ignore_errors=True
        )
        raise UploadError("No files were accepted.", all_rejections)
    await audit.record(
        db,
        "upload.created",
        user_id=uploader.id,
        project_id=project.id,
        target_type="upload",
        target_id=str(upload.id),
        details={"items": accepted, "rejected": len(all_rejections)},
    )
    await db.commit()
    return upload, all_rejections


async def list_items(db: AsyncSession, upload_id: uuid.UUID) -> list[UploadItem]:
    return list(
        (
            await db.scalars(
                select(UploadItem)
                .where(UploadItem.upload_id == upload_id)
                .order_by(UploadItem.created_at, UploadItem.original_name)
            )
        ).all()
    )


async def published_document_ids(
    db: AsyncSession, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    if not item_ids:
        return {}
    rows = (
        await db.execute(
            select(DocumentVersion.upload_item_id, DocumentVersion.document_id).where(
                DocumentVersion.upload_item_id.in_(list(item_ids))
            )
        )
    ).all()
    return {item_id: document_id for item_id, document_id in rows if item_id is not None}


async def my_tasks(db: AsyncSession, user: User) -> list[tuple[UploadItem, Project]]:
    rows = (
        await db.execute(
            select(UploadItem, Project)
            .join(Upload, Upload.id == UploadItem.upload_id)
            .join(Project, Project.id == Upload.project_id)
            .where(
                Upload.uploaded_by == user.id,
                UploadItem.status == "needs_confirmation",
                Project.archived_at.is_(None),
            )
            .order_by(UploadItem.updated_at)
        )
    ).all()
    return [(item, project) for item, project in rows]


def may_act_on_item(upload: Upload, role: str, user: User) -> bool:
    return upload.uploaded_by == user.id or role == "owner"


async def confirm_type(
    db: AsyncSession,
    item: UploadItem,
    *,
    doc_type_key: str,
    taxonomy: Taxonomy,
    actor: User,
    project_id: uuid.UUID,
) -> None:
    if item.status != "needs_confirmation":
        raise ItemStateError("This item is not waiting for a type confirmation.")
    try:
        doc_type = taxonomy.resolve(doc_type_key)
    except UnknownDocType:
        raise ItemStateError(f"Unknown document type {doc_type_key!r}.") from None
    if item.intent == "version" and item.target_document_id is not None:
        target = await db.get(Document, item.target_document_id)
        if target is not None and doc_type.key != target.doc_type:
            raise ItemStateError(f"A new version must keep the document type of {target.title}.")
    item.final_doc_type = doc_type.key
    item.type_check = (
        "mismatch_kept" if doc_type.key == item.selected_doc_type else "mismatch_changed"
    )
    item.status = "publishing"
    item.updated_at = datetime.now(UTC)
    await audit.record(
        db,
        "upload_item.type_confirmed",
        user_id=actor.id,
        project_id=project_id,
        target_type="upload_item",
        target_id=str(item.id),
        details={"selected": item.selected_doc_type, "final": doc_type.key},
    )
    await db.commit()


async def retry_item(
    db: AsyncSession, item: UploadItem, *, actor: User, project_id: uuid.UUID
) -> None:
    if item.status != "failed":
        raise ItemStateError("Only failed items can be retried.")
    item.status = "uploaded"
    item.error = None
    item.updated_at = datetime.now(UTC)
    await audit.record(
        db,
        "upload_item.retried",
        user_id=actor.id,
        project_id=project_id,
        target_type="upload_item",
        target_id=str(item.id),
    )
    await db.commit()
