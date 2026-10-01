import hashlib
import hmac
import secrets


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
