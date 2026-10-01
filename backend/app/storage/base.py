"""Storage backend interface shared by the local, SharePoint and Google Drive adapters (spec 8.1).

Every path is relative to the project root, uses ``/`` as separator and is normalised by
``normalize_path`` before any adapter touches it.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

RESERVED_TOP_LEVEL = frozenset({".versions", ".trash"})
DRIVE_RE = re.compile(r"^[A-Za-z]:")  # a Windows drive prefix such as ``C:``
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class StorageError(Exception):
    """Base class for storage failures; the message is safe to show to users."""


class StoragePathError(StorageError):
    """The path is absolute, escapes the project root, or uses reserved names."""


class StorageNotFound(StorageError):
    """The file or version does not exist."""


@dataclass(frozen=True)
class StoredFile:
    item_id: str
    version_id: str
    web_url: str | None = None


@dataclass(frozen=True)
class StoredVersion:
    version_id: str
    size: int
    modified_at: datetime


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str = ""


def normalize_path(path: str) -> str:
    if "\\" in path or _CONTROL_RE.search(path):
        raise StoragePathError("Path contains characters that are not allowed.")
    if path.startswith("/") or DRIVE_RE.match(path):
        raise StoragePathError("Path must be relative to the project root.")
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if not parts:
        raise StoragePathError("Path is empty.")
    if ".." in parts:
        raise StoragePathError("Path must not contain '..'.")
    if parts[0].casefold() in RESERVED_TOP_LEVEL:
        raise StoragePathError("Path uses a reserved folder name.")
    return "/".join(parts)


class StorageBackend(Protocol):
    async def ensure_folder(self, path: str) -> None: ...

    async def put_file(self, path: str, data: bytes, content_type: str) -> StoredFile: ...

    async def get_file(self, path: str) -> bytes: ...

    async def exists(self, path: str) -> bool: ...

    async def list_versions(self, path: str) -> list[StoredVersion]: ...

    async def get_version(self, path: str, version_id: str) -> bytes: ...

    async def move_to_trash(self, path: str) -> None: ...

    async def health(self) -> HealthStatus: ...
