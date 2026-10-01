"""Deterministic publish of one upload item (spec 6.3 step 5, 5.4, 5.5, 6.4).

Runs under a PostgreSQL advisory lock per project. Writes the original and the converted
Markdown (with frontmatter) to storage, records storage version ids, creates or extends the
document, removes an unchanged stub, regenerates the reports. Idempotent: an item that already
has a document version is returned as-is (checked under the lock).

Storage is written before the caller commits. If anything fails after the first storage write,
``publish_item`` puts storage back the way it found it (best effort) and re-raises: a new
version's paths get the previous version's bytes again, a new document's paths are trashed and
a trashed stub is restored. The reports are not re-rendered on failure (that would need the
rolled-back session); the next successful publish regenerates them.
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import BigInteger, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slugs import unique_slug
from app.db.models import Document, DocumentVersion, Project, Upload, UploadItem, User
from app.ingestion.naming import (
    Frontmatter,
    markdown_path,
    original_path,
    render_markdown_file,
    title_slug,
)
from app.ingestion.taxonomy import DocType, Taxonomy
from app.services.workspace import (
    ensure_workspace,
    is_provisioned,
    refresh_reports,
    sha256_hex,
)
from app.storage.base import StorageBackend, StorageNotFound

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "txt": "text/plain",
    "html": "text/html",
    "csv": "text/csv",
}
MARKDOWN_SUFFIX = ".md"  # converted text sits next to the staged original: <staging_path>.md


class NoChange(Exception):
    """The uploaded file is byte-identical to the document's current version."""


class PublishError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def content_type_for(ext: str) -> str:
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def project_lock_key(project_id: uuid.UUID) -> int:
    digest = hashlib.sha256(project_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def acquire_project_lock(db: AsyncSession, project_id: uuid.UUID) -> None:
    """Transaction-scoped advisory lock; released automatically at commit or rollback."""
    await db.execute(
        select(func.pg_advisory_xact_lock(literal(project_lock_key(project_id), BigInteger)))
    )


async def _taken_slugs(db: AsyncSession, project_id: uuid.UUID, doc_type: DocType) -> set[str]:
    return set(
        (
            await db.scalars(
                select(Document.slug).where(
                    Document.project_id == project_id,
                    Document.doc_type == doc_type.key,
                    Document.is_stub.is_(False),
                )
            )
        ).all()
    )


@dataclass
class _StorageChanges:
    """What one publish changed in storage, so a failure before commit can undo it."""

    # path -> storage version id of the content it held before (None: unknown, leave it)
    previous: dict[str, str | None] = field(default_factory=dict)
    written: list[tuple[str, str]] = field(default_factory=list)  # (path, content type)
    trashed_stub: tuple[str, bytes] | None = None

    async def undo(self, backend: StorageBackend, document_id: uuid.UUID) -> None:
        """Best effort; every step runs even if an earlier one fails. Logs ids and error
        classes only."""
        for path, content_type in reversed(self.written):
            prior = self.previous.get(path)
            try:
                if path not in self.previous:
                    await backend.move_to_trash(path)
                elif prior is None:
                    logger.error("No storage version to restore for document %s", document_id)
                else:
                    await backend.put_file(
                        path, await backend.get_version(path, prior), content_type
                    )
            except Exception as exc:
                logger.error(
                    "Could not undo a storage write for document %s (%s)",
                    document_id,
                    type(exc).__name__,
                )
        if self.trashed_stub is not None:
            path, data = self.trashed_stub
            try:
                await backend.put_file(path, data, "text/markdown")
            except Exception as exc:
                logger.error(
                    "Could not restore the stub for document %s (%s)",
                    document_id,
                    type(exc).__name__,
                )


async def _remove_unchanged_stub(
    db: AsyncSession,
    project: Project,
    doc_type: DocType,
    backend: StorageBackend,
    changes: _StorageChanges,
) -> None:
    row = (
        await db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(
                Document.project_id == project.id,
                Document.doc_type == doc_type.key,
                Document.is_stub.is_(True),
            )
        )
    ).first()
    if row is None:
        return
    stub, version = row
    try:
        current = await backend.get_file(version.markdown_path)
    except StorageNotFound:
        current = None
    if current is None or sha256_hex(current) == version.sha256:
        if current is not None:
            await backend.move_to_trash(version.markdown_path)
            changes.trashed_stub = (version.markdown_path, current)
        await db.delete(stub)
        await db.flush()


async def publish_item(
    db: AsyncSession,
    *,
    item: UploadItem,
    upload: Upload,
    project: Project,
    uploader: User,
    backend: StorageBackend,
    taxonomy: Taxonomy,
    staging_root: Path,
    now: datetime | None = None,
) -> DocumentVersion:
    moment = now or datetime.now(UTC)
    await acquire_project_lock(db, project.id)
    existing = await db.scalar(
        select(DocumentVersion).where(DocumentVersion.upload_item_id == item.id)
    )
    if existing is not None:
        return existing
    if not is_provisioned(project):
        await ensure_workspace(
            db, project=project, backend=backend, taxonomy=taxonomy, actor=uploader, now=moment
        )
    doc_type = taxonomy.resolve(item.final_doc_type or item.selected_doc_type)
    staged = staging_root / item.staging_path
    try:
        data = await asyncio.to_thread(staged.read_bytes)
        markdown = await asyncio.to_thread(
            staged.with_name(staged.name + MARKDOWN_SUFFIX).read_text, encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise PublishError("Staged file is no longer available; upload the file again.") from exc

    if item.intent == "version":
        document = (
            await db.get(Document, item.target_document_id) if item.target_document_id else None
        )
        if document is None or document.project_id != project.id or document.is_stub:
            raise PublishError("Target document not found.")
        current = await db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version == document.current_version,
            )
        )
        if current is not None and current.sha256 == item.sha256:
            raise NoChange()
        changes = _StorageChanges()
        if current is not None:
            for path, storage_version in (
                (current.original_path, current.original_storage_version),
                (current.markdown_path, current.markdown_storage_version),
            ):
                if path is not None:
                    changes.previous[path] = storage_version
        version = document.current_version + 1
    else:
        slug = unique_slug(title_slug(item.title), await _taken_slugs(db, project.id, doc_type))
        document = Document(
            project_id=project.id,
            folder_id=doc_type.folder_id,
            doc_type=doc_type.key,
            title=item.title,
            slug=slug,
            visibility=item.visibility,
            current_version=0,
            is_stub=False,
            created_by=uploader.id,
        )
        db.add(document)
        await db.flush()
        version = 1
        changes = _StorageChanges()

    orig_path = original_path(doc_type, document.slug, item.ext)
    md_path = markdown_path(doc_type, document.slug)
    frontmatter = Frontmatter(
        document_id=str(document.id),
        version=version,
        doc_type=doc_type.id,
        folder=doc_type.folder_dir,
        title=document.title,
        kind="converted",
        source_file=PurePosixPath(orig_path).name,
        source_sha256=item.sha256,
        uploaded_by=uploader.display_name,
        uploaded_at=moment,
        type_selected_by_user=item.selected_doc_type,
        type_check=item.type_check or "skipped",
        language=item.conversion_meta.get("language"),
        visibility=document.visibility,
    )
    markdown_text = render_markdown_file(frontmatter, markdown)
    document_id = document.id  # plain id: a failed flush leaves ``document`` unusable
    original_type = content_type_for(item.ext)
    try:
        stored_original = await backend.put_file(orig_path, data, original_type)
        changes.written.append((orig_path, original_type))
        stored_markdown = await backend.put_file(
            md_path, markdown_text.encode("utf-8"), "text/markdown"
        )
        changes.written.append((md_path, "text/markdown"))
        document_version = DocumentVersion(
            document_id=document.id,
            version=version,
            sha256=item.sha256,
            original_path=orig_path,
            original_storage_version=stored_original.version_id,
            markdown_path=md_path,
            markdown_storage_version=stored_markdown.version_id,
            markdown_text=markdown_text,
            uploaded_by=uploader.id,
            upload_item_id=item.id,
        )
        db.add(document_version)
        document.current_version = version
        document.updated_at = moment
        await db.flush()
        await _remove_unchanged_stub(db, project, doc_type, backend, changes)
        await refresh_reports(db, project=project, backend=backend, taxonomy=taxonomy, now=moment)
    except BaseException:
        await changes.undo(backend, document_id)
        raise
    return document_version
