"""Storage connections (spec 8.5): the configured storage locations projects bind to.
Plan 3a accepts ``localfs`` only; SharePoint and Google Drive arrive with Plan 3b."""

import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.db.locks import acquire_xact_lock
from app.db.models import Project, StorageConnection, User
from app.schemas.storage import LocalFsConfig
from app.services import audit
from app.storage.base import HealthStatus, StorageError
from app.storage.select import connection_backend, localfs_root

logger = logging.getLogger(__name__)

# Migration 0003 holds a frozen copy of this name and root; changing them here does not
# rename the connection in databases that already ran that migration.
DEFAULT_CONNECTION_NAME = "Local storage"
DEFAULT_ROOT_PATH = "."
ACCEPTED_TYPES = ("localfs",)


async def list_connections(db: AsyncSession) -> list[StorageConnection]:
    rows = await db.scalars(select(StorageConnection).order_by(StorageConnection.name))
    return list(rows.all())


async def connections_by_id(db: AsyncSession) -> dict[uuid.UUID, StorageConnection]:
    return {connection.id: connection for connection in await list_connections(db)}


async def get_connection(db: AsyncSession, connection_id: uuid.UUID) -> StorageConnection | None:
    return await db.get(StorageConnection, connection_id)


async def default_connection(db: AsyncSession) -> StorageConnection | None:
    return await db.scalar(select(StorageConnection).where(StorageConnection.is_default.is_(True)))


async def ensure_default_connection(db: AsyncSession) -> StorageConnection | None:
    """Create the default local connection when no connection exists yet (first start of a
    fresh database). Commits. Returns the default, or None when connections exist but none is
    marked default (logged; the admin API keeps exactly one, so this means manual tampering)."""
    existing = await default_connection(db)
    if existing is not None:
        return existing
    if await db.scalar(select(func.count()).select_from(StorageConnection)):
        logger.error("Storage connections exist but none is the default")
        return None
    connection = StorageConnection(
        type="localfs",
        name=DEFAULT_CONNECTION_NAME,
        config={"root_path": DEFAULT_ROOT_PATH},
        is_default=True,
        is_active=True,
        created_by=None,
    )
    db.add(connection)
    try:
        await db.flush()
    except IntegrityError:  # another process created it first
        await db.rollback()
        return await default_connection(db)
    await audit.record(
        db,
        "storage_connection.created",
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"type": connection.type, "name": connection.name, "system": True},
    )
    await db.commit()
    return connection


class StorageConnectionError(Exception):
    """Invalid input (route → 422)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StorageConnectionConflict(Exception):
    """The change contradicts the current state (route → 409)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


NAME_TAKEN = "A connection with this name already exists."


def validate_config(type_: str, config: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Validate and normalise the non-secret configuration for a connection type."""
    if type_ not in ACCEPTED_TYPES:
        raise StorageConnectionError(f"Storage type {type_!r} is not available in this version.")
    try:
        parsed = LocalFsConfig.model_validate(config)
    except ValidationError as exc:
        raise StorageConnectionError("; ".join(str(e["msg"]) for e in exc.errors())) from exc
    try:
        localfs_root(parsed.root_path, settings)
    except StorageError as exc:
        raise StorageConnectionError(str(exc)) from exc
    return parsed.model_dump()


async def _name_taken(db: AsyncSession, name: str, *, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(StorageConnection.id).where(StorageConnection.name == name)
    if exclude is not None:
        stmt = stmt.where(StorageConnection.id != exclude)
    return await db.scalar(stmt) is not None


async def _move_default(db: AsyncSession, connection: StorageConnection) -> uuid.UUID | None:
    """Make ``connection`` the only default inside the current transaction and return the
    previous default's id. An advisory lock serialises concurrent changes, and the old flag is
    flushed before the new one so the partial unique index never sees two defaults."""
    await acquire_xact_lock(db, "storage-default", "all")
    previous = await default_connection(db)
    if previous is not None and previous.id != connection.id:
        previous.is_default = False
        await db.flush()
    connection.is_default = True
    await db.flush()
    return None if previous is None else previous.id


async def create_connection(
    db: AsyncSession,
    *,
    type_: str,
    name: str,
    config: dict[str, Any],
    secret: str | None,
    is_default: bool,
    actor: User,
    box: SecretBox,
    settings: Settings,
) -> StorageConnection:
    clean_config = validate_config(type_, config, settings)
    if await _name_taken(db, name):
        raise StorageConnectionConflict(NAME_TAKEN)
    connection = StorageConnection(
        type=type_,
        name=name,
        config=clean_config,
        secret_enc=box.encrypt(secret) if secret else None,
        is_default=False,
        is_active=True,
        created_by=actor.id,
    )
    db.add(connection)
    try:
        await db.flush()
    except IntegrityError as exc:  # a concurrent request took the name
        await db.rollback()
        raise StorageConnectionConflict(NAME_TAKEN) from exc
    await audit.record(
        db,
        "storage_connection.created",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"type": type_, "name": name, "has_secret": secret is not None},
    )
    if is_default:
        previous = await _move_default(db, connection)
        await audit.record(
            db,
            "storage_connection.default_changed",
            user_id=actor.id,
            target_type="storage_connection",
            target_id=str(connection.id),
            details={"previous_id": None if previous is None else str(previous)},
        )
    await db.commit()
    if is_default:
        await db.refresh(connection)
    return connection


async def projects_using(db: AsyncSession, connection_id: uuid.UUID) -> int:
    """Non-archived projects bound to the connection."""
    count = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(
            Project.storage.op("->>")("connection_id") == str(connection_id),
            Project.archived_at.is_(None),
        )
    )
    return int(count or 0)


async def update_connection(
    db: AsyncSession,
    connection: StorageConnection,
    *,
    actor: User,
    box: SecretBox,
    settings: Settings,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    secret: str | None = None,
    is_active: bool | None = None,
    commit: bool = True,
) -> StorageConnection:
    """Apply the given changes. ``commit=False`` leaves them pending so a route can combine
    this with another change in one transaction (one route, one commit)."""
    changes: dict[str, Any] = {}
    if name is not None and name != connection.name:
        if await _name_taken(db, name, exclude=connection.id):
            raise StorageConnectionConflict(NAME_TAKEN)
        connection.name = name
        changes["name"] = name
    if config is not None:
        connection.config = validate_config(connection.type, config, settings)
        changes["config"] = True
    if secret is not None:
        connection.secret_enc = box.encrypt(secret)
        changes["secret"] = True
    if is_active is not None and is_active != connection.is_active:
        if not is_active:
            if connection.is_default:
                raise StorageConnectionConflict(
                    "The default connection cannot be deactivated. "
                    "Set another connection as the default first."
                )
            in_use = await projects_using(db, connection.id)
            if in_use:
                noun = "project" if in_use == 1 else "projects"
                raise StorageConnectionConflict(
                    f"This connection is used by {in_use} active {noun} and cannot be deactivated."
                )
        connection.is_active = is_active
        changes["is_active"] = is_active
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise StorageConnectionConflict(NAME_TAKEN) from exc
    await audit.record(
        db,
        "storage_connection.updated",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"fields": sorted(changes)},
    )
    if commit:
        await db.commit()
        await db.refresh(connection)
    return connection


async def set_default(
    db: AsyncSession, connection: StorageConnection, *, actor: User, commit: bool = True
) -> None:
    """Move the default to ``connection``. ``commit=False`` leaves the move pending so a route
    can apply further changes in the same transaction and commit once."""
    if connection.is_default:
        return
    if not connection.is_active:
        raise StorageConnectionConflict("An inactive connection cannot be the default.")
    previous = await _move_default(db, connection)
    await audit.record(
        db,
        "storage_connection.default_changed",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"previous_id": None if previous is None else str(previous)},
    )
    if commit:
        await db.commit()
        await db.refresh(connection)


async def test_connection(
    db: AsyncSession, connection: StorageConnection, *, actor: User, settings: Settings
) -> HealthStatus:
    """Run the adapter's health check for the connection root; audited either way."""
    try:
        status = await connection_backend(connection, settings).health()
    except StorageError as exc:
        status = HealthStatus(ok=False, detail=str(exc))
    await audit.record(
        db,
        "storage_connection.tested",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"ok": status.ok, "detail": status.detail},
    )
    await db.commit()
    return status
