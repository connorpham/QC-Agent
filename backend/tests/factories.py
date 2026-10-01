import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.passwords import hash_password
from app.core.tokens import hash_token, new_session_token
from app.db.models import AuthSession, Project, ProjectMember, StorageConnection, User
from app.ingestion.taxonomy import Taxonomy
from app.services.consent import record_consent
from app.services.projects import create_project

DEFAULT_PASSWORD = "correct-horse-battery-staple"


async def make_user(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str = "alice@example.com",
    password: str = DEFAULT_PASSWORD,
    display_name: str = "Alice",
    account_type: str = "internal",
    is_admin: bool = False,
    is_active: bool = True,
    must_change_password: bool = False,
    mfa_secret: str | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        account_type=account_type,
        is_admin=is_admin,
        is_active=is_active,
        must_change_password=must_change_password,
    )
    if mfa_secret is not None:
        user.mfa_secret_enc = SecretBox(settings.secret_encryption_key).encrypt(mfa_secret)
        user.mfa_enabled = True
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_session_token(
    db: AsyncSession,
    settings: Settings,
    user: User,
    *,
    mfa_verified: bool = True,
    expires_in: timedelta = timedelta(hours=8),
) -> str:
    token = new_session_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token, settings.session_secret),
            mfa_verified=mfa_verified,
            expires_at=datetime.now(UTC) + expires_in,
        )
    )
    await db.commit()
    return token


async def reload[T](db: AsyncSession, model: type[T], obj_id: uuid.UUID | Any) -> T | None:
    db.expire_all()
    return await db.get(model, obj_id)


async def make_connection(
    db: AsyncSession,
    *,
    name: str = "Second storage",
    root_path: str = "second",
    type_: str = "localfs",
    is_active: bool = True,
) -> StorageConnection:
    """A non-default connection under LOCAL_STORAGE_ROOT/<root_path>; the folder is created on
    first use. Use the service's ``set_default`` to make it the default."""
    connection = StorageConnection(
        type=type_, name=name, config={"root_path": root_path}, is_active=is_active
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection


async def make_project(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    *,
    owner: User,
    name: str = "Demo Project",
    client_name: str | None = "ACME",
    consent: bool = True,
    connection_id: uuid.UUID | None = None,
    root: str | None = None,
) -> Project:
    """A project with its workspace provisioned (folders, stubs, reports) on the given or
    default connection and, by default, the LLM data-processing confirmation recorded so
    uploads are allowed."""
    project = await create_project(
        db,
        name=name,
        client_name=client_name,
        creator=owner,
        settings=settings,
        taxonomy=taxonomy,
        connection_id=connection_id,
        root=root,
    )
    if consent:
        await record_consent(db, project, actor=owner, confirmed_by_name="Customer Rep")
    await db.refresh(project)
    return project


async def add_member(db: AsyncSession, project: Project, user: User, role: str) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    await db.commit()
