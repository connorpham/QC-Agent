import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings

VALID_SECRET = "s" * 32
MALFORMED = "x" * 10  # not URL-safe base64 of 32 bytes


def test_valid_secrets_construct() -> None:
    key = Fernet.generate_key().decode()
    settings = Settings(session_secret=VALID_SECRET, secret_encryption_key=key)  # type: ignore[call-arg]
    assert settings.session_secret == VALID_SECRET
    assert settings.secret_encryption_key == key


def test_short_session_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            session_secret="s" * 31, secret_encryption_key=Fernet.generate_key().decode()
        )


def test_invalid_fernet_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SECRET_ENCRYPTION_KEY must be a valid Fernet key"):
        Settings(session_secret=VALID_SECRET, secret_encryption_key=MALFORMED)  # type: ignore[call-arg]


def test_auth_rate_limit_default() -> None:
    assert Settings.model_fields["rate_limit_auth_per_5min"].default == 100
