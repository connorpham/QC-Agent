from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    session_secret: str = Field(min_length=32)
    secret_encryption_key: str
    public_base_url: str = "http://localhost:3000"
    cookie_secure: bool = True
    expose_docs: bool = False
    session_ttl_hours: int = 8
    login_max_failures: int = 5
    lockout_minutes: int = 15
    rate_limit_auth_per_5min: int = 100
    # Plan 2: templates, storage and upload limits
    templates_dir: str | None = None  # default: <repository root>/templates
    local_storage_root: str = "./workspace"
    staging_root: str = "./staging"
    max_upload_file_mb: int = Field(default=50, ge=1)
    max_upload_batch_mb: int = Field(default=500, ge=1)

    @field_validator("secret_encryption_key")
    @classmethod
    def _valid_fernet_key(cls, value: str) -> str:
        try:
            Fernet(value.encode())
        except ValueError as exc:
            raise ValueError("SECRET_ENCRYPTION_KEY must be a valid Fernet key.") from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
