import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STORAGE_TYPES = ("localfs", "sharepoint", "gdrive")


class StorageConnection(Base):
    """A configured storage location projects bind to (spec 8.5). ``config`` holds the
    non-secret settings (``localfs``: ``{"root_path": ...}`` relative to LOCAL_STORAGE_ROOT);
    ``secret_enc`` the Fernet-encrypted write-only secret. Exactly one row is the default,
    enforced by the partial unique index on ``is_default``."""

    __tablename__ = "storage_connections"
    __table_args__ = (
        CheckConstraint(f"type IN ({', '.join(repr(t) for t in STORAGE_TYPES)})", name="type"),
        Index(
            "uq_storage_connections_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secret_enc: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
