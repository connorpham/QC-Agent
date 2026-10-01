"""Second-factor consumption must be atomic: a request holding stale user state must not
reuse a TOTP step or recovery code that a concurrent request already consumed."""

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.totp import hash_recovery_code
from app.db.models import AuthSession, User
from app.services.context import SessionContext
from app.services.mfa import verify_second_factor
from tests.factories import make_session_token, make_user

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
CODE = "0123abcd-4567ef89"


async def _contexts(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> tuple[AsyncSession, SessionContext, AsyncSession, SessionContext]:
    async with maker() as setup:
        user = await make_user(setup, settings, mfa_secret=SECRET)
        user.recovery_codes_hash = [hash_recovery_code(CODE, settings.session_secret)]
        await setup.commit()
        await make_session_token(setup, settings, user, mfa_verified=False)
        await make_session_token(setup, settings, user, mfa_verified=False)
    sessions: list[tuple[AsyncSession, SessionContext]] = []
    async with maker() as lookup:
        auth_ids = list((await lookup.scalars(select(AuthSession.id))).all())
    for auth_id in auth_ids:
        db = maker()
        auth = await db.get_one(AuthSession, auth_id)
        loaded = await db.get_one(User, auth.user_id)
        sessions.append((db, SessionContext(auth_session=auth, user=loaded)))
    (db_a, ctx_a), (db_b, ctx_b) = sessions
    return db_a, ctx_a, db_b, ctx_b


async def test_stale_request_cannot_reuse_recovery_code(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    box = SecretBox(settings.secret_encryption_key)
    db_a, ctx_a, db_b, ctx_b = await _contexts(db_sessionmaker, settings)
    try:
        assert await verify_second_factor(db_a, ctx_a, box, settings, CODE) is True
        assert await verify_second_factor(db_b, ctx_b, box, settings, CODE) is False
        assert ctx_b.user.recovery_codes_hash == []
    finally:
        await db_a.close()
        await db_b.close()


async def test_stale_request_cannot_reuse_totp_step(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    box = SecretBox(settings.secret_encryption_key)
    db_a, ctx_a, db_b, ctx_b = await _contexts(db_sessionmaker, settings)
    code = pyotp.TOTP(SECRET).now()
    try:
        assert await verify_second_factor(db_a, ctx_a, box, settings, code) is True
        assert await verify_second_factor(db_b, ctx_b, box, settings, code) is False
    finally:
        await db_a.close()
        await db_b.close()
