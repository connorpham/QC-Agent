import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.emails import normalize_email
from app.core.passwords import (
    burn_password_check,
    hash_password,
    validate_new_password,
    verify_password,
)
from app.core.tokens import hash_token, new_session_token
from app.db.models import AuthSession, User
from app.services import audit
from app.services.context import SessionContext


@dataclass
class LoginResult:
    user: User
    token: str
    auth_session: AuthSession


async def register_failure(db: AsyncSession, user: User, settings: Settings, now: datetime) -> bool:
    """Count a failed credential check atomically. Returns True when this failure locked the
    account. Concurrent failures each add one in the database, so a stale in-memory
    ``failed_logins`` cannot lose a count."""
    count = await db.scalar(
        update(User)
        .where(User.id == user.id)
        .values(failed_logins=User.failed_logins + 1)
        .returning(User.failed_logins)
        .execution_options(synchronize_session=False)
    )
    locked = False
    if count is not None and count >= settings.login_max_failures:
        locked_id = await db.scalar(
            update(User)
            .where(User.id == user.id, User.failed_logins >= settings.login_max_failures)
            .values(locked_until=now + timedelta(minutes=settings.lockout_minutes), failed_logins=0)
            .returning(User.id)
            .execution_options(synchronize_session=False)
        )
        locked = locked_id is not None
    await db.refresh(user)
    return locked


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
        await audit.record(db, "auth.login_failed_unknown", details={"ip": ip})
        await db.commit()
        return None
    if is_locked(user, moment):
        burn_password_check(password)
        await audit.record(db, "auth.login_blocked_locked", user_id=user.id, details={"ip": ip})
        await db.commit()
        return None
    if not verify_password(user.password_hash, password):
        locked = await register_failure(db, user, settings, moment)
        await audit.record(
            db, "auth.login_failed", user_id=user.id, details={"locked": locked, "ip": ip}
        )
        await db.commit()
        return None
    # The failure counter is shared with MFA; only a completed second factor resets it.
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


async def revoke_user_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    except_session_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> None:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    await db.execute(stmt)


class PasswordChangeError(Exception):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


async def change_password(
    db: AsyncSession, ctx: SessionContext, current_password: str, new_password: str
) -> None:
    user = ctx.user
    if not verify_password(user.password_hash, current_password):
        raise PasswordChangeError(["Current password is incorrect."])
    errors = validate_new_password(new_password, email=user.email)
    if verify_password(user.password_hash, new_password):
        errors.append("New password must differ from the current password.")
    if errors:
        raise PasswordChangeError(errors)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.failed_logins = 0
    await revoke_user_sessions(db, user.id, except_session_id=ctx.auth_session.id)
    await audit.record(db, "auth.password_changed", user_id=user.id)
    await db.commit()
