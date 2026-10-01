import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class LoginResponse(BaseModel):
    mfa_enrolled: bool
    must_change_password: bool


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    account_type: str
    is_admin: bool
    mfa_enabled: bool
    mfa_verified: bool
    must_change_password: bool


class CodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class EnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)
