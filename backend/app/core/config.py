from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    session_secret: str
    secret_encryption_key: str
    public_base_url: str = "http://localhost:3000"
    cookie_secure: bool = True
    session_ttl_hours: int = 8
    login_max_failures: int = 5
    lockout_minutes: int = 15
    rate_limit_auth_per_5min: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
