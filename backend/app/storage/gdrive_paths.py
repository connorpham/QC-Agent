"""Path to file id for Google Drive (spec 8.3).

``StorageBackend`` is path-addressed and assumes one item per name. Drive addresses items by id
and allows two items with the same name in one folder. This module resolves each segment, caches
folder ids per connection, and raises ``StorageAmbiguousPath`` on a duplicate instead of picking
one, so a divergence is reported rather than silently written to the wrong item.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic

import httpx

from app.storage.base import StorageAmbiguousPath, StorageNotFound, normalize_path
from app.storage.http import TokenProvider
from app.storage.retry import DRIVE_POLICY, raise_for_storage, send_with_retry

FOLDER_MIME = "application/vnd.google-apps.folder"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
LIST_FIELDS = "files(id,name,mimeType),incompleteSearch"


def escape_query_value(value: str) -> str:
    """Escape a name for a Drive query literal: backslash first, then the quote."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


@dataclass(frozen=True)
class DriveEntry:
    id: str
    name: str
    mime_type: str

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME


class FolderCache:
    """Folder ids by scoped path key, with a TTL and a size cap.

    Keys are prefixed with the connection's scope, so one customer's Shared Drive can never
    answer a lookup for another's. Entries are hints: a miss costs one request, and a stale hit
    is detected by the caller and dropped with ``invalidate``.
    """

    def __init__(self, ttl: float = 600.0, max_entries: int = 2000) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._entries: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        found = self._entries.get(key)
        if found is None:
            return None
        file_id, expires = found
        if expires <= monotonic():
            del self._entries[key]
            return None
        return file_id

    def put(self, key: str, file_id: str) -> None:
        if len(self._entries) >= self._max:
            self._entries.clear()  # a cold cache costs one request per folder; keep it simple
        self._entries[key] = (file_id, monotonic() + self._ttl)

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def invalidate_scope(self, scope: str) -> None:
        for key in [k for k in self._entries if k.startswith(f"{scope}:")]:
            del self._entries[key]


class DriveResolver:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tokens: TokenProvider,
        drive_id: str,
        *,
        scope: str,
        cache: FolderCache,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._tokens = tokens
        self._drive_id = drive_id
        self._scope = scope
        self._cache = cache
        self._sleep = sleep

    def _key(self, relative: str) -> str:
        return f"{self._scope}:{relative}"

    def forget(self, relative: str) -> None:
        self._cache.invalidate(self._key(relative))

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._tokens.token()}"}

    async def find_child(self, parent_id: str, name: str) -> DriveEntry | None:
        """The single child of ``parent_id`` called ``name``; None when there is none."""
        params = {
            "q": f"'{escape_query_value(parent_id)}' in parents and "
            f"name = '{escape_query_value(name)}' and trashed = false",
            "driveId": self._drive_id,
            "corpora": "drive",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "pageSize": "2",  # two is enough to prove a duplicate
            "fields": LIST_FIELDS,
        }
        headers = await self._headers()
        # ``context`` reaches a raised StorageError's message, which a client can read back
        # through an upload item's ``error`` field - it must never carry the Shared Drive id.
        # ``log_context`` may, for the log line only (wave 2 of finding 9).
        context = "Looking up an item in Google Drive"
        log_context = f"{context} (drive {self._drive_id})"
        response = await send_with_retry(
            self._client,
            lambda: self._client.build_request("GET", FILES_URL, params=params, headers=headers),
            policy=DRIVE_POLICY,
            context=context,
            log_context=log_context,
            sleep=self._sleep,
        )
        raise_for_storage(response, context=context, log_context=log_context)
        files = response.json().get("files", [])
        if len(files) > 1:
            raise StorageAmbiguousPath(
                f"Google Drive holds more than one item named {name!r} in the same folder. "
                "Rename or remove the duplicate in Drive, then try again."
            )
        if not files:
            return None
        found = files[0]
        return DriveEntry(id=found["id"], name=found["name"], mime_type=found["mimeType"])

    async def _folder_id(self, relative: str, parent_id: str, name: str) -> str | None:
        cached = self._cache.get(self._key(relative))
        if cached is not None:
            return cached
        entry = await self.find_child(parent_id, name)
        if entry is None or not entry.is_folder:
            return None
        self._cache.put(self._key(relative), entry.id)
        return entry.id

    async def resolve_optional(self, relative: str, *, root_id: str) -> DriveEntry | None:
        parts = normalize_path(relative).split("/")
        parent_id = root_id
        walked: list[str] = []
        for name in parts[:-1]:
            walked.append(name)
            folder_id = await self._folder_id("/".join(walked), parent_id, name)
            if folder_id is None:
                return None
            parent_id = folder_id
        return await self.find_child(parent_id, parts[-1])

    async def resolve(self, relative: str, *, root_id: str) -> DriveEntry:
        entry = await self.resolve_optional(relative, root_id=root_id)
        if entry is None:
            raise StorageNotFound(f"File not found: {normalize_path(relative)}")
        return entry

    async def create_folder(self, parent_id: str, name: str) -> str:
        headers = await self._headers()
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        context = "Creating a folder in Google Drive"
        log_context = f"{context} (drive {self._drive_id})"
        response = await send_with_retry(
            self._client,
            lambda: self._client.build_request(
                "POST",
                FILES_URL,
                params={"supportsAllDrives": "true", "fields": "id"},
                json=body,
                headers=headers,
            ),
            policy=DRIVE_POLICY,
            context=context,
            log_context=log_context,
            sleep=self._sleep,
        )
        raise_for_storage(response, context=context, log_context=log_context)
        created: str = response.json()["id"]
        return created

    async def ensure_folder(self, relative: str, *, root_id: str) -> str:
        """Resolve ``relative`` to a folder id, creating the segments that do not exist."""
        parent_id = root_id
        walked: list[str] = []
        for name in normalize_path(relative).split("/"):
            walked.append(name)
            key = "/".join(walked)
            folder_id = await self._folder_id(key, parent_id, name)
            if folder_id is None:
                folder_id = await self.create_folder(parent_id, name)
                self._cache.put(self._key(key), folder_id)
            parent_id = folder_id
        return parent_id


__all__ = [
    "FOLDER_MIME",
    "DriveEntry",
    "DriveResolver",
    "FolderCache",
    "TokenProvider",
    "escape_query_value",
]
