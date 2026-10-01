import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

import pyotp

ISSUER = "QC-Agent"
_STEP = timedelta(seconds=30)
_RECOVERY_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{8}$")


def new_totp_secret() -> str:
    return str(pyotp.random_base32())


def provisioning_uri(secret: str, email: str) -> str:
    return str(pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER))


def match_totp(secret: str, code: str, *, now: datetime | None = None) -> int | None:
    """Return the matched time-step counter (current or one step either side), or None."""
    cleaned = code.replace(" ", "").strip()
    if len(cleaned) != 6 or not cleaned.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    moment = now or datetime.now(UTC)
    for drift in (-1, 0, 1):
        at = moment + drift * _STEP
        if hmac.compare_digest(str(totp.at(at)), cleaned):
            return int(totp.timecode(at))
    return None


def _normalize_recovery(code: str) -> str:
    return code.replace(" ", "").strip().lower()


def is_recovery_code_format(code: str) -> bool:
    return _RECOVERY_RE.fullmatch(_normalize_recovery(code)) is not None


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(count)]


_RECOVERY_KEY_LABEL = b"qc-agent/recovery-codes"


def hash_recovery_code(code: str, secret: str) -> str:
    # Derived sub-key so recovery-code hashes never share a key with session-token hashes.
    key = hmac.new(secret.encode(), _RECOVERY_KEY_LABEL, hashlib.sha256).digest()
    return hmac.new(key, _normalize_recovery(code).encode(), hashlib.sha256).hexdigest()
