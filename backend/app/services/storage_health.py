"""Storage part of the public ``/health`` endpoint (spec 16).

``/health`` has no authentication, so this returns one word. Which connection failed and why is
admin-only and lives in ``POST /storage-connections/{id}/test``. The result is cached for a
minute so an anonymous caller cannot turn one request into one Graph or Drive call per
connection.

This also calls each adapter's ``health`` with ``probe_write=False`` (the default): a read-only
liveness check only (mint a token, confirm the configured library or Shared Drive is reachable).
The full staged probe - which, on SharePoint, writes and deletes a small file to measure whether
version history is on - is reserved for the admin-only Test connection in
``app.services.storage_connections.test_connection``, where a human asked for the answer. A
sixty-second cache bounds the *rate* of even the read-only check; it is not what keeps this
endpoint from writing into a customer's library - ``probe_write=False`` is what does that.
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
            # Read-only liveness only - never the write-probing full check (see module docstring).
            status = await connection_backend(connection, settings).health(probe_write=False)
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
