import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    folder_id: str
    doc_type: str
    title: str
    slug: str
    visibility: str
    current_version: int
    is_stub: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    uploaded_by_name: str | None = None  # display name of the current version's uploader
    version_created_at: datetime | None = None


class DocumentVersionOut(BaseModel):
    version: int
    sha256: str
    original_path: str | None
    markdown_path: str
    uploaded_by: str  # display name
    upload_item_id: uuid.UUID | None
    created_at: datetime


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    visibility: Literal["internal", "shared"] | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Title is required.")
        return cleaned


class VersionSuggestionOut(BaseModel):
    document_id: uuid.UUID
    title: str
    current_version: int
    similarity: float


class DocumentContentOut(BaseModel):
    """One version's converted Markdown split into frontmatter and body (spec 5.3)."""

    version: int
    frontmatter: dict[str, Any]
    body: str
    markdown_name: str
    original_name: str | None


class GapEntryOut(BaseModel):
    doc_type: str
    title: str
    required: bool
    status: Literal["present", "stub", "missing"]
    documents: int


class GapFolderOut(BaseModel):
    id: str
    dir: str
    stage: str
    doc_types: list[GapEntryOut]


class GapProjectOut(BaseModel):
    slug: str
    name: str


class GapReportOut(BaseModel):
    qc_agent: int
    project: GapProjectOut
    generated_at: datetime
    required_total: int
    required_present: int
    completeness: float
    folders: list[GapFolderOut]
