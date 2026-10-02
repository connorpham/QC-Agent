import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ITEM_STATUSES = (
    "uploaded",
    "converting",
    "checking",
    "needs_confirmation",
    "publishing",
    "published",
    "failed",
)
TERMINAL_STATUSES = ("published", "failed")
ACTIVE_STATUSES = ("uploaded", "converting", "checking", "publishing")  # work in progress
ITEM_STATUS_EVENT = "item.status"
INTENTS = ("new", "version")
VISIBILITIES = ("internal", "shared")
TYPE_CHECKS = ("match", "mismatch_kept", "mismatch_changed", "skipped")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    repo_ref: Mapped[str | None] = mapped_column(String(500))  # repository reference, later plan
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("project_id", "doc_type", "slug", name="uq_documents_project_type_slug"),
        CheckConstraint(f"visibility IN ({_in_list(VISIBILITIES)})", name="visibility"),
        CheckConstraint(
            "(is_stub AND slug = '') OR (NOT is_stub AND slug <> '')", name="stub_slug"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[str] = mapped_column(String(40))
    doc_type: Mapped[str] = mapped_column(String(80))  # taxonomy key, e.g. "srs" or "design/other"
    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))  # title slug; "" for stubs
    visibility: Mapped[str] = mapped_column(String(8), default="internal")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    is_stub: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UploadItem(Base):
    __tablename__ = "upload_items"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in_list(ITEM_STATUSES)})", name="status"),
        CheckConstraint(f"intent IN ({_in_list(INTENTS)})", name="intent"),
        CheckConstraint(f"visibility IN ({_in_list(VISIBILITIES)})", name="visibility"),
        CheckConstraint(
            f"type_check IS NULL OR type_check IN ({_in_list(TYPE_CHECKS)})", name="type_check"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    ext: Mapped[str] = mapped_column(String(8))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    staging_path: Mapped[str] = mapped_column(String(500))  # relative to STAGING_ROOT
    selected_doc_type: Mapped[str] = mapped_column(String(80))
    final_doc_type: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    intent: Mapped[str] = mapped_column(String(8), default="new")
    target_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    visibility: Mapped[str] = mapped_column(String(8), default="internal")
    status: Mapped[str] = mapped_column(String(24), default="uploaded", index=True)
    type_check: Mapped[str | None] = mapped_column(String(24))
    check_explanation: Mapped[str | None] = mapped_column(Text)
    suggested_doc_type: Mapped[str | None] = mapped_column(String(80))
    version_hint_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    conversion_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_document_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    original_path: Mapped[str | None] = mapped_column(String(500))  # None for stubs
    original_storage_version: Mapped[str | None] = mapped_column(String(100))
    markdown_path: Mapped[str] = mapped_column(String(500))
    markdown_storage_version: Mapped[str] = mapped_column(String(100))
    markdown_text: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    upload_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("upload_items.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadEvent(Base):
    """One row per upload-item state change (spec 10 ``events``), written in the same
    transaction as the change; ``id`` is the Server-Sent Events id and ``Last-Event-ID``."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_upload_id_id", "upload_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("upload_items.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
