from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.emails import normalize_email
from app.core.passwords import burn_password_check, verify_password
from app.core.tokens import hash_token, new_session_token
from app.db.models import AuthSession, User
from app.services import audit


@dataclass
class LoginResult:
    user: User
    token: str
    auth_session: AuthSession


def register_failure(user: User, settings: Settings, now: datetime) -> bool:
    """Count a failed credential check. Returns True when the account just got locked."""
    user.failed_logins += 1
    if user.failed_logins >= settings.login_max_failures:
        user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
        user.failed_logins = 0
        return True
    return False


def is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now


async def authenticate(
    db: AsyncSession,
    email: str,
    password: str,
    settings: Settings,
    *,
    ip: str | None,
    user_agent: str | None,
    now: datetime | None = None,
) -> LoginResult | None:
    moment = now or datetime.now(UTC)
    user = await db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or not user.is_active:
        burn_password_check(password)
        await audit.record(db, "auth.login_failed_unknown")
        await db.commit()
        return None
    if is_locked(user, moment):
        burn_password_check(password)
        await audit.record(db, "auth.login_blocked_locked", user_id=user.id)
        await db.commit()
        return None
    if not verify_password(user.password_hash, password):
        locked = register_failure(user, settings, moment)
        await audit.record(db, "auth.login_failed", user_id=user.id, details={"locked": locked})
        await db.commit()
        return None
    user.failed_logins = 0
    user.locked_until = None
    token = new_session_token()
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token, settings.session_secret),
        expires_at=moment + timedelta(hours=settings.session_ttl_hours),
        ip=ip,
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(auth_session)
    await audit.record(db, "auth.login", user_id=user.id)
    await db.commit()
    return LoginResult(user=user, token=token, auth_session=auth_session)
