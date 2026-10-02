"""The public /health storage check: one word, no details, and cached."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import StorageConnection
from app.services import storage_health
from app.storage.base import HealthStatus, StorageError
from tests.factories import make_connection


class Stub:
    calls = 0
    probe_write_values: list[bool] = []

    def __init__(self, status: HealthStatus | Exception) -> None:
        self._status = status

    async def health(self, *, probe_write: bool = False) -> HealthStatus:
        Stub.calls += 1
        Stub.probe_write_values.append(probe_write)
        if isinstance(self._status, Exception):
            raise self._status
        return self._status


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    storage_health.reset_cache()
    Stub.calls = 0
    Stub.probe_write_values = []


async def test_all_connections_healthy_is_ok(
    db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    assert await storage_health.storage_check(db, settings) == "ok"


async def test_the_public_check_never_asks_for_the_write_probe(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the public/admin split at the service boundary: the unauthenticated /health summary
    must always request the read-only mode, never the admin-only write-and-versioning probe."""
    await make_connection(db, name="Second storage", root_path="second")
    monkeypatch.setattr(
        storage_health, "connection_backend", lambda *_: Stub(HealthStatus(ok=True, detail="ok"))
    )
    await storage_health.storage_check(db, settings)
    assert Stub.calls >= 1
    assert Stub.probe_write_values == [False] * len(Stub.probe_write_values)


async def test_one_failing_connection_makes_the_check_error(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_connection(db, name="Broken", root_path="broken")

    def fake(connection: StorageConnection, _settings: Settings) -> Stub:
        return Stub(HealthStatus(ok=connection.name != "Broken", detail="x", field="drive_id"))

    monkeypatch.setattr(storage_health, "connection_backend", fake)
    assert await storage_health.storage_check(db, settings) == "error"


async def test_an_adapter_that_raises_counts_as_an_error(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        storage_health, "connection_backend", lambda *_: Stub(StorageError("no secret"))
    )
    assert await storage_health.storage_check(db, settings) == "error"


async def test_inactive_connections_are_not_checked(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_connection(db, name="Retired", root_path="retired", is_active=False)
    monkeypatch.setattr(
        storage_health, "connection_backend", lambda *_: Stub(HealthStatus(ok=True, detail="ok"))
    )
    await storage_health.storage_check(db, settings)
    assert Stub.calls == 1  # only the active default


async def test_the_result_is_cached(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unauthenticated endpoint must not become one API call per request."""
    clock = [1000.0]
    monkeypatch.setattr(
        storage_health, "connection_backend", lambda *_: Stub(HealthStatus(ok=True, detail="ok"))
    )
    await storage_health.storage_check(db, settings, now=lambda: clock[0])
    await storage_health.storage_check(db, settings, now=lambda: clock[0])
    assert Stub.calls == 1
    clock[0] += storage_health.CACHE_SECONDS + 1
    await storage_health.storage_check(db, settings, now=lambda: clock[0])
    assert Stub.calls == 2
