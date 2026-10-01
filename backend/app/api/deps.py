from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import SESSION_COOKIE
from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.tokens import hash_token
from app.db.models import AuthSession, User
from app.db.session import get_session
from app.services.context import SessionContext


def settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(settings_dep)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


async def session_context(request: Request, db: DbSession, settings: AppSettings) -> SessionContext:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    auth_session = await db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(token, settings.session_secret)
        )
    )
    now = datetime.now(UTC)
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
    ):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user = await db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return SessionContext(auth_session=auth_session, user=user)


SessionCtx = Annotated[SessionContext, Depends(session_context)]


def auth_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    if not request.app.state.auth_limiter.hit(key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")


def secret_box_dep(settings: AppSettings) -> SecretBox:
    return SecretBox(settings.secret_encryption_key)


Box = Annotated[SecretBox, Depends(secret_box_dep)]


async def mfa_context(ctx: SessionCtx) -> SessionContext:
    if not ctx.auth_session.mfa_verified:
        raise HTTPException(status_code=401, detail="MFA verification required.")
    return ctx


MfaCtx = Annotated[SessionContext, Depends(mfa_context)]
