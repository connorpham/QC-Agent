"""Document queries and edits with the role and visibility rules of spec 9."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentVersion, User
from app.ingestion.taxonomy import Taxonomy
from app.ingestion.versioning import VersionCandidate, VersionSuggestion, suggest_versions
from app.services import audit


class DocumentPermissionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def visible_to_role(role: str) -> str | None:
    """The visibility a role is restricted to (clients see shared documents only)."""
    return "shared" if role == "client" else None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_documents(
    db: AsyncSession,
    project_id: uuid.UUID,
    role: str,
    taxonomy: Taxonomy,
    *,
    folder: str | None = None,
    doc_type: str | None = None,
    visibility: str | None = None,
    q: str | None = None,
) -> list[Document]:
    stmt = select(Document).where(Document.project_id == project_id)
    restricted = visible_to_role(role)
    if restricted is not None:
        stmt = stmt.where(Document.visibility == restricted)
    if folder is not None:
        stmt = stmt.where(Document.folder_id == folder)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)
    if visibility is not None:
        stmt = stmt.where(Document.visibility == visibility)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{_escape_like(q)}%", escape="\\"))
    documents = list((await db.scalars(stmt)).all())
    order = {folder.id: index for index, folder in enumerate(taxonomy.folders)}
    documents.sort(
        key=lambda d: (order.get(d.folder_id, 99), d.doc_type, d.is_stub, d.title.lower())
    )
    return documents


async def list_versions(
    db: AsyncSession, document_id: uuid.UUID
) -> list[tuple[DocumentVersion, str]]:
    rows = (
        await db.execute(
            select(DocumentVersion, User.display_name)
            .join(User, User.id == DocumentVersion.uploaded_by)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version)
        )
    ).all()
    return [(version, name) for version, name in rows]


async def get_version(
    db: AsyncSession, document_id: uuid.UUID, version: int
) -> DocumentVersion | None:
    return await db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id, DocumentVersion.version == version
        )
    )


async def update_document(
    db: AsyncSession,
    document: Document,
    *,
    actor: User,
    role: str,
    title: str | None,
    visibility: str | None,
) -> None:
    """Owners change anything; editors rename and may share internal documents; viewers and
    clients cannot edit. Renaming never moves files in storage (paths follow the slug)."""
    if role not in ("owner", "editor"):
        raise DocumentPermissionError("You do not have access to this action.")
    if document.is_stub:
        raise DocumentPermissionError("Stub documents cannot be edited.")
    changes: dict[str, str] = {}
    if visibility is not None and visibility != document.visibility:
        if role == "editor" and visibility == "internal":
            raise DocumentPermissionError(
                "Only a project owner can make a shared document internal."
            )
        changes["visibility"] = visibility
        document.visibility = visibility
    if title is not None and title != document.title:
        changes["title"] = title
        document.title = title
    if not changes:
        return
    document.updated_at = datetime.now(UTC)
    action = "document.visibility_changed" if "visibility" in changes else "document.updated"
    await audit.record(
        db,
        action,
        user_id=actor.id,
        project_id=document.project_id,
        target_type="document",
        target_id=str(document.id),
        details=changes,
    )
    await db.commit()


async def version_suggestions(
    db: AsyncSession, project_id: uuid.UUID, role: str, *, doc_type: str, title: str
) -> list[VersionSuggestion]:
    stmt = select(Document).where(
        Document.project_id == project_id,
        Document.doc_type == doc_type,
        Document.is_stub.is_(False),
    )
    restricted = visible_to_role(role)
    if restricted is not None:
        stmt = stmt.where(Document.visibility == restricted)
    documents: Sequence[Document] = (await db.scalars(stmt)).all()
    return suggest_versions(
        title,
        [
            VersionCandidate(
                document_id=d.id, title=d.title, slug=d.slug, current_version=d.current_version
            )
            for d in documents
        ],
    )
