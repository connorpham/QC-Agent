import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StorageType = Literal["localfs", "sharepoint", "gdrive"]


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Connection name is required.")
    return cleaned


class LocalFsConfig(BaseModel):
    """Non-secret configuration of a ``localfs`` connection."""

    model_config = ConfigDict(extra="forbid")

    root_path: str = Field(min_length=1, max_length=500)

    @field_validator("root_path")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Root path is required.")
        return cleaned


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
