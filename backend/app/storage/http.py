"""One httpx client for every cloud storage adapter.

A new client per request would mean a new TLS handshake per upload, so the client is created
once per process and closed by the application lifespan. Adapters accept an injected client so
tests can hand them an ``httpx.MockTransport`` and make no network call.
"""

from typing import Protocol

import httpx

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=TIMEOUT, limits=LIMITS, follow_redirects=False)
    return _client


async def aclose_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class TokenProvider(Protocol):
    """Supplies a bearer token for one connection. Implementations cache and refresh it, and
    never log it or put it in an exception message."""

    async def token(self) -> str: ...
