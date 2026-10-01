"""Default connection at startup and project-to-adapter resolution through the connection."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, StorageConnection
from app.ingestion.taxonomy import Taxonomy
from app.services.storage_connections import (
    DEFAULT_CONNECTION_NAME,
    connections_by_id,
    default_connection,
    ensure_default_connection,
)
from app.storage.base import StorageError
from app.storage.localfs import LocalFsBackend
from app.storage.select import project_backend
from tests.factories import make_connection, make_project, make_user


async def test_ensure_default_connection_is_idempotent(db: AsyncSession) -> None:
    first = await ensure_default_connection(db)  # the fixture already created it
    second = await ensure_default_connection(db)
    assert first is not None and second is not None and first.id == second.id
    assert first.name == DEFAULT_CONNECTION_NAME and first.config == {"root_path": "."}
    assert first.type == "localfs" and first.is_default and first.is_active
    assert await db.scalar(select(func.count()).select_from(StorageConnection)) == 1
    created = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "storage_connection.created"))
    ).all()
    assert len(created) == 1 and created[0].details["system"] is True


async def test_ensure_default_connection_creates_one_when_the_table_is_empty(
    db: AsyncSession,
) -> None:
    await db.execute(delete(StorageConnection))
    await db.commit()
    created = await ensure_default_connection(db)
    assert created is not None and created.is_default is True
    assert (await default_connection(db)) is not None


async def test_project_backend_resolves_through_the_connection(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner = await make_user(db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    project = await make_project(
        db, settings, taxonomy, owner=owner, name="Demo", connection_id=archive.id, root="acme"
    )
    backend = await project_backend(db, project, settings)
    assert isinstance(backend, LocalFsBackend)
    assert backend.root == (storage_root / "archive" / "acme").resolve()
    assert (storage_root / "archive" / "acme" / "project.yaml").exists()
    assert project.storage["connection_id"] == str(archive.id)
    assert project.storage["root"] == "acme" and "provisioned_at" in project.storage
    default = await default_connection(db)
    assert default is not None
    assert set((await connections_by_id(db)).keys()) == {archive.id, default.id}


async def test_project_backend_with_a_missing_or_broken_binding_raises(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    project.storage = {**project.storage, "connection_id": str(uuid.uuid4())}
    with pytest.raises(StorageError, match="no longer exists"):
        await project_backend(db, project, settings)
    project.storage = {"root": "demo"}
    with pytest.raises(StorageError, match="incomplete"):
        await project_backend(db, project, settings)
