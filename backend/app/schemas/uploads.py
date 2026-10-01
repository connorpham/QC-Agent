import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UploadItemSpec(BaseModel):
    """Per-file metadata sent in the ``items`` JSON part, in the same order as ``files``."""

    model_config = ConfigDict(extra="forbid")

    doc_type: str = Field(min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=200)
    intent: Literal["new", "version"] = "new"
    target_document_id: uuid.UUID | None = None
    visibility: Literal["internal", "shared"] = "internal"

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class RejectionOut(BaseModel):
    name: str
    reason: str


class UploadItemOut(BaseModel):
    id: uuid.UUID
    upload_id: uuid.UUID
    original_name: str
    ext: str
    size: int
    sha256: str
    selected_doc_type: str
    final_doc_type: str | None
    title: str
    intent: str
    target_document_id: uuid.UUID | None
    visibility: str
    status: str
    type_check: str | None
    check_explanation: str | None
    suggested_doc_type: str | None
    version_hint_document_id: uuid.UUID | None
    warnings: list[str]
    conversion_meta: dict[str, Any]
    error: str | None
    document_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class UploadOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    uploaded_by: uuid.UUID
    created_at: datetime
    items: list[UploadItemOut]
    rejected: list[RejectionOut]


class TaskOut(BaseModel):
    item: UploadItemOut
    project_id: uuid.UUID
    project_name: str


class ConfirmTypeRequest(BaseModel):
    doc_type: str = Field(min_length=1, max_length=80)
