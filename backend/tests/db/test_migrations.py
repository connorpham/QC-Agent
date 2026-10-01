"""The migrations, applied to an empty database, must produce exactly the ORM schema.

Uses a throwaway database (``qc_agent_migtest``) on the test server rather than a schema
inside the test database: ``migrations/env.py`` builds its own engine from DATABASE_URL, so
a separate database is the most reliable way to give it an empty target.
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.base import Base

BACKEND = Path(__file__).resolve().parents[2]
MIGTEST_DB = "qc_agent_migtest"


def _admin_url() -> str:
    return (
        make_url(os.environ["TEST_DATABASE_URL"])
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )


def _migtest_url() -> str:
    return (
        make_url(os.environ["TEST_DATABASE_URL"])
        .set(database=MIGTEST_DB)
        .render_as_string(hide_password=False)
    )


async def _recreate_database(*, create: bool) -> None:
    engine = create_async_engine(_admin_url(), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {MIGTEST_DB} WITH (FORCE)"))
        if create:
            await conn.execute(text(f"CREATE DATABASE {MIGTEST_DB}"))
    await engine.dispose()


def _diff(conn: Connection) -> list[object]:
    context = MigrationContext.configure(conn, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))


async def _schema_diff() -> list[object]:
    engine = create_async_engine(_migtest_url(), poolclass=NullPool)
    async with engine.connect() as conn:
        diff = await conn.run_sync(_diff)
    await engine.dispose()
    return diff


def test_migrations_match_models(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_recreate_database(create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", _migtest_url())
        get_settings.cache_clear()
        # No ini file: env.py would otherwise call logging.fileConfig and reconfigure
        # the test process's loggers.
        config = Config()
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(config, "head")
        assert asyncio.run(_schema_diff()) == []
    finally:
        get_settings.cache_clear()
        asyncio.run(_recreate_database(create=False))
