import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StorageType = Literal["localfs", "sharepoint", "gdrive"]

# The site id and the drive id are the one field that separates one customer's document library
# or Shared Drive from another's. Both are interpolated into a URL path (and a drive id also into
# Drive's own query language), so a conservative whitelist - rather than merely rejecting a known
# bad character - is what keeps a pasted value from ever being able to retarget a request. The set
# covers every shape seen in practice: SharePoint's comma-separated site id
# ("host,siteCollectionId,webId"), its "b!..." drive id, and Google's plain alphanumeric Shared
# Drive id (spec 8.2, 8.3; finding 7).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.,:!_-]*[A-Za-z0-9])?$")
SAFE_ID_MESSAGE = (
    "must contain only letters, digits, and the characters . , : ! _ - , and must not start or "
    "end with one of those"
)


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Connection name is required.")
    return cleaned


def _required(label: str, value: str) -> str:
    """``label`` names the field in lower case (e.g. ``"tenant id"``) so the message both reads
    naturally and contains the exact words a caller matches on (spec 8.5's "field at fault")."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"A {label} is required.")
    return cleaned


def _safe_id(label: str, value: str) -> str:
    """Like ``_required``, but also rejects any character outside the conservative whitelist a
    site id or a drive id is interpolated under (finding 7)."""
    cleaned = _required(label, value)
    if not _SAFE_ID_RE.fullmatch(cleaned):
        raise ValueError(f"The {label} {SAFE_ID_MESSAGE}.")
    return cleaned


class LocalFsConfig(BaseModel):
    """Non-secret configuration of a ``localfs`` connection."""

    model_config = ConfigDict(extra="forbid")

    root_path: str = Field(min_length=1, max_length=500)

    @field_validator("root_path")
    @classmethod
    def _strip(cls, value: str) -> str:
        return _required("root path", value)


class SharePointConfig(BaseModel):
    """Non-secret configuration of a ``sharepoint`` connection: one customer's document library
    on the single shared site (spec 8.2). The client secret is stored separately, write-only."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="", max_length=200, validate_default=True)
    client_id: str = Field(default="", max_length=200, validate_default=True)
    site_id: str = Field(default="", max_length=400, validate_default=True)
    drive_id: str = Field(default="", max_length=400, validate_default=True)

    @field_validator("tenant_id")
    @classmethod
    def _strip_tenant(cls, value: str) -> str:
        return _required("tenant id", value)

    @field_validator("client_id")
    @classmethod
    def _strip_client(cls, value: str) -> str:
        return _required("client id", value)

    @field_validator("site_id")
    @classmethod
    def _strip_site(cls, value: str) -> str:
        return _safe_id("site id", value)

    @field_validator("drive_id")
    @classmethod
    def _strip_drive(cls, value: str) -> str:
        return _safe_id("document library drive id", value)


class GDriveConfig(BaseModel):
    """Non-secret configuration of a ``gdrive`` connection. The service-account JSON key is
    stored separately, write-only."""

    model_config = ConfigDict(extra="forbid")

    drive_id: str = Field(default="", max_length=200, validate_default=True)

    @field_validator("drive_id")
    @classmethod
    def _strip_drive(cls, value: str) -> str:
        return _safe_id("Shared Drive id", value)


class StorageConnectionCreate(BaseModel):
    type: StorageType
    name: str = Field(max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = Field(default=None, min_length=1, max_length=20000)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class StorageConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, min_length=1, max_length=20000)
    is_active: bool | None = None
    is_default: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class StorageConnectionOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    config: dict[str, Any]
    is_default: bool
    is_active: bool
    has_secret: bool
    created_at: datetime
    updated_at: datetime


class StorageConnectionAvailable(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    is_default: bool


class StorageTestResult(BaseModel):
    ok: bool
    detail: str
    field: str | None = None  # the connection field at fault, when the adapter identified one
