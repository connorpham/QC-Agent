import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(default="claude-opus-5", min_length=1, max_length=100)
    check_budget_usd: float = Field(default=1.0, gt=0, le=50)
    normalize_budget_usd: float = Field(default=2.0, gt=0, le=50)


class ProjectSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1, max_length=100)
    check_budget_usd: float | None = Field(default=None, gt=0, le=50)
    normalize_budget_usd: float | None = Field(default=None, gt=0, le=50)


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Project name is required.")
    return cleaned


class ProjectCreate(BaseModel):
    name: str = Field(max_length=200)
    client_name: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    settings: ProjectSettingsPatch | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class ProjectStorageOut(BaseModel):
    type: str
    root: str


class LlmConsentOut(BaseModel):
    confirmed_by_name: str
    confirmed_at: datetime


class LlmConsentRequest(BaseModel):
    confirmed_by_name: str = Field(min_length=1, max_length=200)

    @field_validator("confirmed_by_name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("The confirming person's name is required.")
        return cleaned


class ProjectOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    client_name: str | None
    created_at: datetime
    my_role: str
    settings: ProjectSettings | None
    storage: ProjectStorageOut | None
    llm_consent: LlmConsentOut | None


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: Literal["owner", "editor", "viewer", "client"]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    account_type: str
    role: str
