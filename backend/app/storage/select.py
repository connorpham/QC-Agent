"""Resolve the storage adapter for a connection and for a project's binding (spec 8.5).

A project's ``storage`` column holds ``{"connection_id": "<uuid>", "root": "<folder>"}`` plus
``provisioned_at`` once the workspace exists. The connection row supplies the adapter type and
its non-secret configuration; for ``localfs`` that is ``root_path``, which must stay inside
``LOCAL_STORAGE_ROOT`` so an administrator cannot point storage at arbitrary system folders.
"""

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Project, StorageConnection
from app.storage.base import StorageBackend, StorageError, validate_root_segment
from app.storage.localfs import LocalFsBackend

LOCALFS = "localfs"
ROOT_OUTSIDE_MESSAGE = "Storage root must be inside LOCAL_STORAGE_ROOT."


def storage_binding(connection_id: uuid.UUID, root: str) -> dict[str, Any]:
    return {"connection_id": str(connection_id), "root": root}


def localfs_root(root_path: str, settings: Settings) -> Path:
    """Absolute folder of a ``localfs`` connection. ``root_path`` is relative to
    ``LOCAL_STORAGE_ROOT`` ("." is the storage root itself); an absolute path is accepted only
    when it lies inside it. Symlinks are resolved before the check."""
    base = Path(settings.local_storage_root).resolve()
    candidate = Path(root_path)
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        raise StorageError(ROOT_OUTSIDE_MESSAGE)
    return resolved


def _localfs_connection_root(connection: StorageConnection, settings: Settings) -> Path:
    root_path = connection.config.get("root_path")
    if not isinstance(root_path, str) or not root_path:
        raise StorageError("Storage connection configuration is incomplete.")
    return localfs_root(root_path, settings)


def connection_backend(connection: StorageConnection, settings: Settings) -> StorageBackend:
    """Adapter for the connection's own root (used by "Test connection")."""
    if connection.type == LOCALFS:
        return LocalFsBackend(_localfs_connection_root(connection, settings))
    raise StorageError(f"Storage type {connection.type!r} is not available in this deployment.")


def backend_for(connection: StorageConnection, root: str, settings: Settings) -> StorageBackend:
    """Adapter for the project folder ``root`` inside the connection."""
    if connection.type == LOCALFS:
        segment = validate_root_segment(root)
        return LocalFsBackend(_localfs_connection_root(connection, settings) / segment)
    raise StorageError(f"Storage type {connection.type!r} is not available in this deployment.")


async def project_backend(db: AsyncSession, project: Project, settings: Settings) -> StorageBackend:
    """Load the project's connection row and return the adapter for its folder."""
    raw_id = project.storage.get("connection_id")
    root = project.storage.get("root")
    if not isinstance(raw_id, str) or not isinstance(root, str) or not root:
        raise StorageError("Project storage binding is incomplete.")
    try:
        connection_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise StorageError("Project storage binding is incomplete.") from exc
    connection = await db.get(StorageConnection, connection_id)
    if connection is None:
        raise StorageError("The project's storage connection no longer exists.")
    return backend_for(connection, root, settings)
