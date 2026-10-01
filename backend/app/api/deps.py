import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import SESSION_COOKIE
from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.tokens import hash_token
from app.db.models import AuthSession, Project, ProjectMember, User
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


async def current_user(ctx: MfaCtx) -> User:
    if ctx.user.must_change_password:
        raise HTTPException(status_code=403, detail="Password change required.")
    return ctx.user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]

ALL_ROLES = ("owner", "editor", "viewer", "client")
INTERNAL_ROLES = ("owner", "editor", "viewer")


@dataclass
class ProjectContext:
    project: Project
    user: User
    role: str


def require_project_role(*allowed: str) -> Callable[..., Awaitable[ProjectContext]]:
    async def dependency(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectContext:
        project = await db.get(Project, project_id)
        if project is None or project.archived_at is not None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if user.is_admin:
            role: str | None = "owner"
        else:
            role = await db.scalar(
                select(ProjectMember.role).where(
                    ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
                )
            )
        if role is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this action.")
        return ProjectContext(project=project, user=user, role=role)

    return dependency


AnyMember = Annotated[ProjectContext, Depends(require_project_role(*ALL_ROLES))]
InternalMember = Annotated[ProjectContext, Depends(require_project_role(*INTERNAL_ROLES))]
ProjectOwner = Annotated[ProjectContext, Depends(require_project_role("owner"))]
