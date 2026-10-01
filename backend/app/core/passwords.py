import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("dummy-password-used-for-constant-time-checks")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown e-mails are not distinguishable."""
    verify_password(_DUMMY_HASH, password)


def validate_new_password(password: str, *, email: str) -> list[str]:
    errors: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    local_part = email.split("@", 1)[0].strip().lower()
    if len(local_part) >= 3 and local_part in password.lower():
        errors.append("Password must not contain your e-mail name.")
    return errors


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(12)  # 16 characters
