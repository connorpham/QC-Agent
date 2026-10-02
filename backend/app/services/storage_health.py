"""Storage part of the public ``/health`` endpoint (spec 16).

``/health`` has no authentication, so this returns one word. Which connection failed and why is
admin-only and lives in ``POST /storage-connections/{id}/test``. The result is cached for a
minute so an anonymous caller cannot turn one request into one Graph or Drive call per
connection.
"""

import asyncio
import logging
from collections.abc import Callable
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import StorageConnection
from app.services.storage_connections import list_connections
from app.storage.base import StorageError
from app.storage.select import connection_backend

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0
PER_CONNECTION_TIMEOUT = 15.0

_cache: tuple[str, float] | None = None


def reset_cache() -> None:
    global _cache
    _cache = None


async def _one(connection: StorageConnection, settings: Settings) -> bool:
    try:
        async with asyncio.timeout(PER_CONNECTION_TIMEOUT):
            status = await connection_backend(connection, settings).health()
    except (StorageError, TimeoutError, OSError):
        logger.warning("Storage connection %s failed its health check", connection.id)
        return False
    if not status.ok:
        logger.warning("Storage connection %s is unhealthy", connection.id)
    return status.ok


async def storage_check(
    db: AsyncSession, settings: Settings, *, now: Callable[[], float] = monotonic
) -> str:
    global _cache
    if _cache is not None and _cache[1] > now():
        return _cache[0]
    connections = [c for c in await list_connections(db) if c.is_active]
    results = await asyncio.gather(*(_one(c, settings) for c in connections))
    verdict = "ok" if all(results) else "error"
    _cache = (verdict, now() + CACHE_SECONDS)
    return verdict
