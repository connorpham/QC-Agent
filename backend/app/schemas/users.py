import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.emails import is_valid_email, normalize_email


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    account_type: str
    is_admin: bool
    is_active: bool
    mfa_enabled: bool
    must_change_password: bool
    locked_until: datetime | None


class CreateUserRequest(BaseModel):
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    account_type: Literal["internal", "customer"]
    is_admin: bool = False

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        email = normalize_email(value)
        if not is_valid_email(email):
            raise ValueError("Enter a valid e-mail address.")
        return email

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Display name is required.")
        return value.strip()

    @model_validator(mode="after")
    def _customer_not_admin(self) -> Self:
        if self.is_admin and self.account_type == "customer":
            raise ValueError("Customer accounts cannot be administrators.")
        return self


class CreateUserResponse(BaseModel):
    user: UserOut
    temporary_password: str


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    is_admin: bool | None = None

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("Display name is required.")
        return value.strip()


class TemporaryPasswordResponse(BaseModel):
    temporary_password: str
