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
from app.storage.select import connection_backend

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0
PER_CONNECTION_TIMEOUT = 15.0

_cache: tuple[str, float] | None = None
# Single-flight guard (see storage_check): the one shared probe currently in progress, if any.
# Holding a Future rather than a Task means a caller that is not the one running the probe never
# touches that request's own ``db`` session - it only awaits a value another coroutine will set.
_inflight: asyncio.Future[str] | None = None


def reset_cache() -> None:
    global _cache, _inflight
    _cache = None
    _inflight = None


async def _one(connection: StorageConnection, settings: Settings) -> bool:
    try:
        async with asyncio.timeout(PER_CONNECTION_TIMEOUT):
            # Read-only liveness only - never the write-probing full check (see module docstring).
            status = await connection_backend(connection, settings).health(probe_write=False)
    except Exception:  # noqa: BLE001 - this endpoint's whole job is to answer when storage is
        # broken, and nothing on this branch has ever run against a real provider: an unexpected
        # response shape (a corporate proxy or a gateway returning a 2xx carrying HTML, for
        # instance - .json() on that raises a plain JSONDecodeError, which is neither
        # StorageError, TimeoutError nor OSError) is the expected case here, not a bug to let
        # propagate into a 500 (finding 4). Only a connection id is logged, never the body.
        logger.warning("Storage connection %s failed its health check", connection.id)
        return False
    if not status.ok:
        logger.warning("Storage connection %s is unhealthy", connection.id)
    return status.ok


async def storage_check(
    db: AsyncSession, settings: Settings, *, now: Callable[[], float] = monotonic
) -> str:
    """One word, cached, and single-flighted (spec 16).

    Without a guard, concurrent anonymous callers who all miss the cache each start their own
    probe of every active connection: five hundred concurrent requests against ten connections
    becomes thousands of outbound provider requests, and the retry layer then multiplies any
    throttling response it gets back (finding 3). Two cases, handled differently:

    - No previous verdict exists at all (the first calls after process start): there is nothing
      to serve, so every caller genuinely waits for the one probe already in flight, via a shared
      ``Future`` - never starting a second one of its own.
    - A previous verdict exists but has expired: the caller that notices this performs the
      recompute as an ordinary part of handling its own request (using its own ``db``, so no
      session ever outlives the request that owns it); every other concurrent caller is handed
      the previous verdict immediately rather than piling onto that recompute or starting its own.
    """
    global _cache, _inflight
    if _cache is not None and _cache[1] > now():
        return _cache[0]

    if _inflight is not None:
        if _cache is not None:
            return _cache[0]  # a previous verdict exists: never block behind a recompute
        return await _inflight  # nothing to serve yet: wait for the one probe already running

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _inflight = future
    try:
        connections = [c for c in await list_connections(db) if c.is_active]
        results = await asyncio.gather(*(_one(c, settings) for c in connections))
        verdict = "ok" if all(results) else "error"
    except BaseException as exc:
        _inflight = None
        if _cache is None:
            # Only a cold-start caller ever awaits this future (see above); setting an exception
            # nobody retrieves would log a spurious "exception never retrieved" warning.
            future.set_exception(exc)
        raise
    _cache = (verdict, now() + CACHE_SECONDS)
    _inflight = None
    future.set_result(verdict)
    return verdict
