"""Pick the storage adapter for a project's ``storage`` binding."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.storage.base import StorageBackend, StorageError
from app.storage.localfs import LocalFsBackend

LOCALFS = "localfs"


def localfs_binding(root: str) -> dict[str, Any]:
    return {"type": LOCALFS, "root": root}


def backend_for(storage: Mapping[str, Any], settings: Settings) -> StorageBackend:
    kind = storage.get("type")
    if kind == LOCALFS:
        root = storage.get("root")
        if not isinstance(root, str) or not root:
            raise StorageError("Project storage binding is incomplete.")
        return LocalFsBackend(Path(settings.local_storage_root) / root)
    raise StorageError(f"Storage type {kind!r} is not available in this deployment.")
