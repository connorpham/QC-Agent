"""Resolve the storage adapter for a connection and for a project's binding (spec 8.5).

A project's ``storage`` column holds ``{"connection_id": "<uuid>", "root": "<folder>"}`` plus
``provisioned_at`` once the workspace exists. The connection row supplies the adapter type and
its non-secret configuration; for ``localfs`` that is ``root_path``, which must stay inside
``LOCAL_STORAGE_ROOT`` so an administrator cannot point storage at arbitrary system folders.
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.db.models import Project, StorageConnection
from app.storage.base import StorageBackend, StorageError, validate_root_segment
from app.storage.gdrive import GoogleDriveBackend, ServiceAccountTokenProvider
from app.storage.localfs import LocalFsBackend
from app.storage.sharepoint import GraphTokenProvider, SharePointBackend

LOCALFS = "localfs"
SHAREPOINT = "sharepoint"
GDRIVE = "gdrive"
ROOT_OUTSIDE_MESSAGE = "Storage root must be inside LOCAL_STORAGE_ROOT."
NO_SECRET = "This storage connection has no stored secret. Enter it on the Storage page."  # noqa: S105
BAD_SECRET = "The stored secret could not be decrypted. Enter it again on the Storage page."  # noqa: S105

# One token provider per (connection, secret), so a publish does not mint a token per file and
# rotating a connection's secret transparently replaces the provider instead of leaving a stale
# one in place. Keyed on a hash of the encrypted secret, never the plaintext, so an administrator
# who edits the configuration but not the secret keeps reusing the same provider and its cached
# health; rotating the secret changes the key and both are rebuilt from the new value. This cache
# is process-local and unbounded for the lifetime of the process - acceptable for the number of
# storage connections an installation has, but it is not evicted when a connection is deleted
# (connections are never deleted, per the plan's global constraints).
_providers: dict[str, Any] = {}


def connection_secret(connection: StorageConnection, settings: Settings) -> str:
    """Decrypt a connection's stored secret. The only place in the system that does this."""
    if not connection.secret_enc:
        raise StorageError(NO_SECRET)
    try:
        return SecretBox(settings.secret_encryption_key).decrypt(connection.secret_enc)
    except InvalidToken as exc:
        raise StorageError(BAD_SECRET) from exc


def _provider_key(connection: StorageConnection) -> str:
    digest = hashlib.sha256((connection.secret_enc or "").encode()).hexdigest()[:16]
    # SharePoint's token provider stores the tenant id and client id inside the cached object
    # itself, not just the secret, so a cache key built from the secret's digest alone goes stale
    # the moment either is corrected while the secret field is left blank - the documented way to
    # keep a stored secret. Folding both into the key (empty for every other connection type, so
    # this is a no-op for localfs and gdrive) makes a config-only correction get a fresh provider
    # on the very next request, with no restart (finding 2).
    tenant_id = connection.config.get("tenant_id", "") if connection.type == SHAREPOINT else ""
    client_id = connection.config.get("client_id", "") if connection.type == SHAREPOINT else ""
    return f"{connection.type}:{connection.id}:{digest}:{tenant_id}:{client_id}"


def _config_value(connection: StorageConnection, key: str) -> str:
    value = connection.config.get(key)
    if not isinstance(value, str) or not value:
        raise StorageError("Storage connection configuration is incomplete.")
    return value


def _cloud_backend(connection: StorageConnection, root: str, settings: Settings) -> StorageBackend:
    key = _provider_key(connection)
    if connection.type == SHAREPOINT:
        provider = _providers.get(key)
        if not isinstance(provider, GraphTokenProvider):
            secret = connection_secret(connection, settings)
            provider = GraphTokenProvider(
                _config_value(connection, "tenant_id"),
                _config_value(connection, "client_id"),
                secret,
            )
            _providers[key] = provider
        return SharePointBackend(
            _config_value(connection, "site_id"),
            _config_value(connection, "drive_id"),
            root,
            provider,
        )
    provider = _providers.get(key)
    if not isinstance(provider, ServiceAccountTokenProvider):
        provider = ServiceAccountTokenProvider(connection_secret(connection, settings))
        _providers[key] = provider
    return GoogleDriveBackend(
        _config_value(connection, "drive_id"), root, provider, scope=str(connection.id)
    )


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
    if connection.type in (SHAREPOINT, GDRIVE):
        return _cloud_backend(connection, "", settings)
    raise StorageError(f"Storage type {connection.type!r} is not available in this deployment.")


def backend_for(connection: StorageConnection, root: str, settings: Settings) -> StorageBackend:
    """Adapter for the project folder ``root`` inside the connection."""
    if connection.type == LOCALFS:
        segment = validate_root_segment(root)
        return LocalFsBackend(_localfs_connection_root(connection, settings) / segment)
    if connection.type in (SHAREPOINT, GDRIVE):
        return _cloud_backend(connection, validate_root_segment(root), settings)
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
