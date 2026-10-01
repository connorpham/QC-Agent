"""Storage connections (spec 8.5): the configured storage locations projects bind to.
Plan 3a accepts ``localfs`` only; SharePoint and Google Drive arrive with Plan 3b."""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StorageConnection
from app.services import audit

logger = logging.getLogger(__name__)

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
