from datetime import UTC, datetime

from sqlalchemy import Text, literal, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.totp import (
    generate_recovery_codes,
    hash_recovery_code,
    is_recovery_code_format,
    match_totp,
    new_totp_secret,
    provisioning_uri,
)
from app.db.models import User
from app.services import audit
from app.services.auth import is_locked, register_failure
from app.services.context import SessionContext


class MfaStateError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def start_enrolment(db: AsyncSession, ctx: SessionContext, box: SecretBox) -> tuple[str, str]:
    if ctx.user.mfa_enabled:
        raise MfaStateError("MFA is already enabled.")
    secret = new_totp_secret()
    ctx.user.mfa_pending_secret_enc = box.encrypt(secret)
    await audit.record(db, "auth.mfa_enrol_started", user_id=ctx.user.id)
    await db.commit()
    return secret, provisioning_uri(secret, ctx.user.email)


async def confirm_enrolment(
    db: AsyncSession, ctx: SessionContext, box: SecretBox, settings: Settings, code: str
) -> list[str] | None:
    user = ctx.user
    if user.mfa_enabled:
        raise MfaStateError("MFA is already enabled.")
    if user.mfa_pending_secret_enc is None:
        raise MfaStateError("Start MFA enrolment first.")
    counter = match_totp(box.decrypt(user.mfa_pending_secret_enc), code)
    if counter is None:
        return None
    codes = generate_recovery_codes()
    user.mfa_secret_enc = user.mfa_pending_secret_enc
    user.mfa_pending_secret_enc = None
    user.mfa_enabled = True
    user.mfa_last_counter = counter
    user.recovery_codes_hash = [hash_recovery_code(c, settings.session_secret) for c in codes]
    ctx.auth_session.mfa_verified = True
    await audit.record(db, "auth.mfa_enrolled", user_id=user.id)
    await db.commit()
    return codes


async def _consume_recovery_code(db: AsyncSession, user: User, hashed: str) -> bool:
    """Atomically remove one recovery-code hash; False if it was absent (or already used)."""
    column = User.__table__.c.recovery_codes_hash
    consumed = await db.scalar(
        update(User)
        .where(User.id == user.id, column.has_key(hashed))
        .values(recovery_codes_hash=column.op("-")(literal(hashed, Text)))
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(user)
    return consumed is not None


async def _advance_totp_counter(db: AsyncSession, user: User, counter: int) -> bool:
    """Atomically record a used TOTP step; False if this or a later step was already used."""
    advanced = await db.scalar(
        update(User)
        .where(
            User.id == user.id,
            or_(User.mfa_last_counter.is_(None), User.mfa_last_counter < counter),
        )
        .values(mfa_last_counter=counter)
        .returning(User.id)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(user)
    return advanced is not None


async def verify_second_factor(
    db: AsyncSession,
    ctx: SessionContext,
    box: SecretBox,
    settings: Settings,
    code: str,
    *,
    now: datetime | None = None,
) -> bool:
    user = ctx.user
    moment = now or datetime.now(UTC)
    if not user.mfa_enabled or user.mfa_secret_enc is None:
        raise MfaStateError("MFA is not enabled.")
    if is_locked(user, moment):
        return False
    ok = False
    if is_recovery_code_format(code):
        hashed = hash_recovery_code(code, settings.session_secret)
        ok = await _consume_recovery_code(db, user, hashed)
        if ok:
            await audit.record(db, "auth.recovery_code_used", user_id=user.id)
    else:
        counter = match_totp(box.decrypt(user.mfa_secret_enc), code, now=moment)
        if counter is not None:
            ok = await _advance_totp_counter(db, user, counter)
    if ok:
        user.failed_logins = 0
        ctx.auth_session.mfa_verified = True
        await audit.record(db, "auth.mfa_verified", user_id=user.id)
    else:
        if register_failure(user, settings, moment):
            ctx.auth_session.revoked_at = moment
        await audit.record(db, "auth.mfa_failed", user_id=user.id)
    await db.commit()
    return ok
