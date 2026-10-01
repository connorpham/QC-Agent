import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from cryptography.fernet import Fernet

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://qc:qc@localhost:5434/qc_agent_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-production")
os.environ.setdefault("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["COOKIE_SECURE"] = "false"
os.environ["EXPOSE_DOCS"] = "false"  # a developer .env may enable docs; tests expect them hidden

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.agent.analyzer import Analyzer  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db import models  # noqa: E402,F401  - registers tables on Base.metadata
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, init_engine  # noqa: E402
from app.main import create_app  # noqa: E402

BASE_URL = "http://testserver"
CSRF = {"X-QC-Agent": "1"}


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    async def build() -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(build())


@pytest.fixture
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@pytest.fixture
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    maker = init_engine(os.environ["DATABASE_URL"], null_pool=True)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with maker() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
    yield maker
    await dispose_engine()


@pytest.fixture
async def db(db_sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with db_sessionmaker() as session:
        yield session


@pytest.fixture
def make_app(db_sessionmaker: async_sessionmaker[AsyncSession]) -> Callable[..., FastAPI]:
    def _make(*, analyzer: Analyzer | None = None, **overrides: Any) -> FastAPI:
        return create_app(Settings(**overrides), analyzer=analyzer)  # type: ignore[call-arg]

    return _make


@pytest.fixture
def app(make_app: Callable[..., FastAPI]) -> FastAPI:
    return make_app()


@pytest.fixture
async def make_client(
    app: FastAPI,
) -> AsyncIterator[Callable[..., Awaitable[AsyncClient]]]:
    clients: list[AsyncClient] = []

    async def _make(token: str | None = None, app_: FastAPI | None = None) -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app_ or app), base_url=BASE_URL, headers=CSRF
        )
        if token is not None:
            client.cookies.set("qc_session", token)
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


@pytest.fixture
async def client(make_client: Callable[..., Awaitable[AsyncClient]]) -> AsyncClient:
    return await make_client()
