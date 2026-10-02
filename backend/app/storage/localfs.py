"""Local filesystem adapter (spec 8.4): files under a root folder, versions as
``.versions/<path>/<n>``, trashed files under ``.trash/<path>``. All blocking I/O runs in a
worker thread so the event loop stays free."""

import asyncio
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.storage.base import (
    HealthStatus,
    StorageNotFound,
    StoragePathError,
    StoredFile,
    StoredVersion,
    normalize_path,
)

VERSIONS_DIR = ".versions"
TRASH_DIR = ".trash"


class LocalFsBackend:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    # -- path safety (synchronous helpers) -------------------------------------------------

    def _target(self, path: str) -> Path:
        relative = normalize_path(path)
        root = self._root.resolve()
        current = root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink():
                raise StoragePathError("Path goes through a symbolic link.")
        resolved = current.resolve()
        if resolved != root and root not in resolved.parents:
            raise StoragePathError("Path escapes the project root.")
        return current

    def _versions_dir(self, path: str) -> Path:
        return self._root / VERSIONS_DIR / normalize_path(path)

    @staticmethod
    def _archived_count(versions_dir: Path) -> int:
        if not versions_dir.is_dir():
            return 0
        return sum(1 for entry in versions_dir.iterdir() if entry.name.isdigit())

    # -- synchronous implementations -------------------------------------------------------

    def _ensure_folder_sync(self, path: str) -> None:
        self._target(path).mkdir(parents=True, exist_ok=True)

    def _put_sync(self, path: str, data: bytes) -> StoredFile:
        target = self._target(path)
        if target.is_dir():
            raise StoragePathError("Path is a folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        versions_dir = self._versions_dir(path)
        archived = self._archived_count(versions_dir)
        if target.exists():
            versions_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, versions_dir / str(archived + 1))
            archived += 1
        tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return StoredFile(item_id=normalize_path(path), version_id=str(archived + 1))

    def _get_sync(self, path: str) -> bytes:
        target = self._target(path)
        if not target.is_file():
            raise StorageNotFound(f"File not found: {normalize_path(path)}")
        return target.read_bytes()

    def _exists_sync(self, path: str) -> bool:
        return self._target(path).is_file()

    def _list_versions_sync(self, path: str) -> list[StoredVersion]:
        target = self._target(path)
        versions_dir = self._versions_dir(path)
        versions: list[StoredVersion] = []
        archived = self._archived_count(versions_dir)
        for number in range(1, archived + 1):
            stat = (versions_dir / str(number)).stat()
            versions.append(
                StoredVersion(
                    version_id=str(number),
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )
            )
        if target.is_file():
            stat = target.stat()
            versions.append(
                StoredVersion(
                    version_id=str(archived + 1),
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )
            )
        return versions

    def _get_version_sync(self, path: str, version_id: str) -> bytes:
        target = self._target(path)
        versions_dir = self._versions_dir(path)
        archived = self._archived_count(versions_dir)
        if not version_id.isdigit():
            raise StorageNotFound(f"Version not found: {version_id}")
        number = int(version_id)
        if number == archived + 1 and target.is_file():
            return target.read_bytes()
        if 1 <= number <= archived:
            return (versions_dir / str(number)).read_bytes()
        raise StorageNotFound(f"Version not found: {version_id}")

    def _move_to_trash_sync(self, path: str) -> None:
        target = self._target(path)
        if not target.is_file():
            raise StorageNotFound(f"File not found: {normalize_path(path)}")
        destination = self._root / TRASH_DIR / normalize_path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(target, destination)

    def _health_sync(self) -> HealthStatus:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / f".health-{uuid.uuid4().hex}"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            return HealthStatus(ok=False, detail=f"Storage root is not writable ({exc.strerror})")
        return HealthStatus(ok=True, detail="ok")

    # -- StorageBackend protocol -----------------------------------------------------------

    async def ensure_folder(self, path: str) -> None:
        await asyncio.to_thread(self._ensure_folder_sync, path)

    async def put_file(self, path: str, data: bytes, content_type: str) -> StoredFile:
        return await asyncio.to_thread(self._put_sync, path, data)

    async def get_file(self, path: str) -> bytes:
        return await asyncio.to_thread(self._get_sync, path)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._exists_sync, path)

    async def list_versions(self, path: str) -> list[StoredVersion]:
        return await asyncio.to_thread(self._list_versions_sync, path)

    async def get_version(self, path: str, version_id: str) -> bytes:
        return await asyncio.to_thread(self._get_version_sync, path, version_id)

    async def move_to_trash(self, path: str) -> None:
        await asyncio.to_thread(self._move_to_trash_sync, path)

    async def health(self, *, probe_write: bool = False) -> HealthStatus:
        # ``probe_write`` is accepted for symmetry with the SharePoint/Google Drive adapters,
        # whose public-vs-admin split it mirrors. It is ignored here: this writes a throwaway
        # file to our own local disk, not a customer's cloud document library, so there is no
        # outbound request and nothing shows up in anyone's audit trail either way.
        return await asyncio.to_thread(self._health_sync)
