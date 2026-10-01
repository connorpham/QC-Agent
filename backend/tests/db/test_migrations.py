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


async def _execute(statements: list[str]) -> None:
    engine = create_async_engine(_migtest_url(), poolclass=NullPool)
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))
    await engine.dispose()


async def _fetch(statement: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(_migtest_url(), poolclass=NullPool)
    async with engine.connect() as conn:
        rows = [tuple(row) for row in await conn.execute(text(statement))]
    await engine.dispose()
    return rows


OLD_BINDING = '{"type": "localfs", "root": "demo", "provisioned_at": "2026-10-01T00:00:00+00:00"}'


def test_0003_rebinds_existing_projects_to_the_default_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_recreate_database(create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", _migtest_url())
        get_settings.cache_clear()
        config = Config()
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(config, "0002")
        asyncio.run(
            _execute(
                [
                    "INSERT INTO users (id, email, password_hash, display_name, account_type, "
                    "is_admin, is_active, must_change_password, mfa_enabled, recovery_codes_hash, "
                    "failed_logins) VALUES ('11111111-1111-1111-1111-111111111111', "
                    "'a@example.com', 'x', 'A', 'internal', false, true, false, false, '[]', 0)",
                    "INSERT INTO projects (id, slug, name, settings, storage, created_by) VALUES "
                    "('22222222-2222-2222-2222-222222222222', 'demo', 'Demo', '{}', "
                    f"'{OLD_BINDING}', '11111111-1111-1111-1111-111111111111')",
                ]
            )
        )
        command.upgrade(config, "head")
        connections = asyncio.run(
            _fetch("SELECT id, type, name, config, is_default, is_active FROM storage_connections")
        )
        assert len(connections) == 1
        connection_id, kind, name, config_json, is_default, is_active = connections[0]
        assert (kind, name, config_json) == ("localfs", "Local storage", {"root_path": "."})
        assert (is_default, is_active) == (True, True)
        (storage,) = asyncio.run(_fetch("SELECT storage FROM projects"))[0]
        assert storage == {
            "connection_id": str(connection_id),
            "root": "demo",
            "provisioned_at": "2026-10-01T00:00:00+00:00",
        }
        command.downgrade(config, "0002")
        (storage,) = asyncio.run(_fetch("SELECT storage FROM projects"))[0]
        assert storage == {
            "type": "localfs",
            "root": "demo",
            "provisioned_at": "2026-10-01T00:00:00+00:00",
        }
    finally:
        get_settings.cache_clear()
        asyncio.run(_recreate_database(create=False))
