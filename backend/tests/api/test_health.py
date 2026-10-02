from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app
from app.services import storage_health


@pytest.fixture(autouse=True)
def _clear_storage_health_cache() -> None:
    storage_health.reset_cache()


class _EmptyScalars:
    def all(self) -> list[Any]:
        return []


class _OkSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def scalars(self, *_args: Any, **_kwargs: Any) -> _EmptyScalars:
        return _EmptyScalars()


class _BrokenSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("database down")


def _client_with(session: object, headers: dict[str, str] | None = None) -> AsyncClient:
    app = create_app(Settings())

    async def override() -> AsyncIterator[object]:
        yield session

    app.dependency_overrides[get_session] = override
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers=headers or {}
    )


async def test_health_ok() -> None:
    async with _client_with(_OkSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "storage": "ok"}}


async def test_health_reports_database_failure() -> None:
    async with _client_with(_BrokenSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "error", "storage": "skipped"},
    }


async def test_state_changing_request_without_csrf_header_is_rejected() -> None:
    async with _client_with(_OkSession()) as client:
        response = await client.post("/api/v1/health")
    assert response.status_code == 403
    assert response.json() == {"detail": "Missing CSRF header."}


async def test_state_changing_request_with_csrf_header_reaches_router() -> None:
    async with _client_with(_OkSession(), headers={"X-QC-Agent": "1"}) as client:
        response = await client.post("/api/v1/health")
    assert response.status_code == 405  # no POST route; the guard let it through


async def test_api_docs_are_hidden_by_default() -> None:
    async with _client_with(_OkSession()) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404
        assert (await client.get("/redoc")).status_code == 404


async def test_api_docs_can_be_exposed() -> None:
    app = create_app(Settings(expose_docs=True))  # type: ignore[call-arg]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        assert (await c.get("/openapi.json")).status_code == 200
        assert (await c.get("/docs")).status_code == 200


async def test_health_reports_storage_without_any_detail(monkeypatch: Any) -> None:
    """Anonymous callers learn that storage is unhealthy, never which one or why."""
    from app.api.routes import health as health_route

    async def failing(*_args: Any, **_kwargs: Any) -> str:
        return "error"

    monkeypatch.setattr(health_route, "storage_check", failing)
    async with _client_with(_OkSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "storage": "error"},
    }
    body = response.text
    for leak in ("sharepoint", "gdrive", "drive_id", "tenant", "site", "secret", "Bearer"):
        assert leak not in body


async def test_health_is_ok_when_storage_is_ok(monkeypatch: Any) -> None:
    from app.api.routes import health as health_route

    async def healthy(*_args: Any, **_kwargs: Any) -> str:
        return "ok"

    monkeypatch.setattr(health_route, "storage_check", healthy)
    async with _client_with(_OkSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["checks"]["storage"] == "ok"


async def test_health_skips_storage_when_the_database_is_down(monkeypatch: Any) -> None:
    """Without a database there are no connection rows to check; say so, do not guess."""
    async with _client_with(_BrokenSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "error", "storage": "skipped"}
