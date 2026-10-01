from datetime import UTC, datetime

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
        if hashed in user.recovery_codes_hash:
            user.recovery_codes_hash = [h for h in user.recovery_codes_hash if h != hashed]
            await audit.record(db, "auth.recovery_code_used", user_id=user.id)
            ok = True
    else:
        counter = match_totp(box.decrypt(user.mfa_secret_enc), code, now=moment)
        if counter is not None and (
            user.mfa_last_counter is None or counter > user.mfa_last_counter
        ):
            user.mfa_last_counter = counter
            ok = True
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
