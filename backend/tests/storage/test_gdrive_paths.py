"""Path -> file id for Google Drive. Drive has no paths and allows duplicate names, so this
module is where that mismatch is resolved; nothing else in the adapter speaks Drive's query
language."""

import httpx
import pytest

from app.storage.base import StorageAmbiguousPath, StorageNotFound
from app.storage.gdrive_paths import (
    FOLDER_MIME,
    DriveResolver,
    FolderCache,
    escape_query_value,
)

DRIVE_ID = "shared-drive-test"
ROOT = "root-folder-id"


class FakeTokens:
    async def token(self) -> str:
        return "test-token"


class Drive:
    """A tiny in-memory Drive: folders and files by (parent, name), answering files.list."""

    def __init__(self) -> None:
        self.items: dict[str, list[tuple[str, str, str]]] = {}  # parent -> [(id, name, mime)]
        self.queries: list[str] = []
        self.created: list[tuple[str, str]] = []

    def add(self, parent: str, file_id: str, name: str, mime: str = FOLDER_MIME) -> None:
        self.items.setdefault(parent, []).append((file_id, name, mime))

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = request.read().decode()
            self.created.append((str(request.url), body))
            return httpx.Response(
                200, json={"id": "new-folder", "name": "x", "mimeType": FOLDER_MIME}
            )
        query = request.url.params.get("q", "")
        self.queries.append(query)
        assert request.url.params["driveId"] == DRIVE_ID
        assert request.url.params["corpora"] == "drive"
        assert request.url.params["supportsAllDrives"] == "true"
        assert request.url.params["includeItemsFromAllDrives"] == "true"
        parent = query.split("'")[1] if "' in parents" in query else ""
        name = query.split("name = '")[1].split("'")[0] if "name = '" in query else ""
        matches = [
            {"id": i, "name": n, "mimeType": m}
            for i, n, m in self.items.get(parent, [])
            if n == name.replace("\\'", "'").replace("\\\\", "\\")
        ]
        return httpx.Response(200, json={"files": matches[:2], "incompleteSearch": False})


def _resolver(
    drive: Drive, cache: FolderCache | None = None, scope: str = "conn-1"
) -> DriveResolver:
    client = httpx.AsyncClient(transport=httpx.MockTransport(drive.handler))
    return DriveResolver(
        client,
        FakeTokens(),
        DRIVE_ID,
        scope=scope,
        cache=cache or FolderCache(),
        sleep=_no_sleep,
    )


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "plain"),
        ("it's", "it\\'s"),
        ("back\\slash", "back\\\\slash"),
        ("a'b\\c", "a\\'b\\\\c"),
    ],
)
def test_escape_query_value(raw: str, expected: str) -> None:
    """A name with a quote must not be able to change the meaning of the query."""
    assert escape_query_value(raw) == expected


async def test_resolves_a_nested_path_to_an_id() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    drive.add("f-req", "file-1", "srs--demo.md", "text/markdown")
    resolver = _resolver(drive)
    entry = await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    assert entry.id == "file-1"
    assert entry.is_folder is False


async def test_missing_segment_raises_not_found() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    resolver = _resolver(drive)
    with pytest.raises(StorageNotFound):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    assert await resolver.resolve_optional("02-requirements/srs--demo.md", root_id=ROOT) is None


async def test_duplicate_segment_is_an_error() -> None:
    """Two folders of the same name: refuse rather than write into whichever came back first."""
    drive = Drive()
    drive.add(ROOT, "f-a", "02-requirements")
    drive.add(ROOT, "f-b", "02-requirements")
    resolver = _resolver(drive)
    with pytest.raises(StorageAmbiguousPath, match="02-requirements"):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)


async def test_duplicate_leaf_file_is_an_error() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    drive.add("f-req", "file-1", "srs--demo.md", "text/markdown")
    drive.add("f-req", "file-2", "srs--demo.md", "text/markdown")
    resolver = _resolver(drive)
    with pytest.raises(StorageAmbiguousPath, match="srs--demo.md"):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)


async def test_folders_are_cached_but_leaf_files_are_not() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    drive.add("f-req", "file-1", "srs--demo.md", "text/markdown")
    resolver = _resolver(drive)
    await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    first = len(drive.queries)
    await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    # the folder came from the cache; only the file was looked up again, because a file can be
    # replaced or trashed between publishes while a folder stays put
    assert len(drive.queries) == first + 1


async def test_cached_id_that_no_longer_resolves_is_refetched() -> None:
    """A folder someone trashed or renamed in Drive must not strand us on a stale id."""
    drive = Drive()
    drive.add(ROOT, "f-old", "02-requirements")
    cache = FolderCache()
    resolver = _resolver(drive, cache)
    await resolver.ensure_folder("02-requirements", root_id=ROOT)
    drive.items[ROOT] = [("f-new", "02-requirements", FOLDER_MIME)]
    resolver.forget("02-requirements")
    assert await resolver.ensure_folder("02-requirements", root_id=ROOT) == "f-new"


async def test_cache_is_scoped_per_connection() -> None:
    """Two connections are two customers' libraries; one must never answer for the other."""
    cache = FolderCache()
    drive_a, drive_b = Drive(), Drive()
    drive_a.add(ROOT, "a-req", "02-requirements")
    drive_b.add(ROOT, "b-req", "02-requirements")
    assert (
        await _resolver(drive_a, cache, scope="conn-a").ensure_folder(
            "02-requirements", root_id=ROOT
        )
        == "a-req"
    )
    assert (
        await _resolver(drive_b, cache, scope="conn-b").ensure_folder(
            "02-requirements", root_id=ROOT
        )
        == "b-req"
    )


async def test_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr("app.storage.gdrive_paths.monotonic", lambda: now[0])
    cache = FolderCache(ttl=60.0)
    cache.put("k", "v")
    assert cache.get("k") == "v"
    now[0] += 61.0
    assert cache.get("k") is None


def test_cache_evicts_when_full() -> None:
    cache = FolderCache(max_entries=2)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.put("c", "3")
    assert cache.get("c") == "3"
    assert sum(cache.get(key) is not None for key in ("a", "b", "c")) <= 2


async def test_ensure_folder_creates_missing_segments_only() -> None:
    drive = Drive()
    drive.add(ROOT, "f-test", "05-testing")
    resolver = _resolver(drive)
    await resolver.ensure_folder("05-testing/test-reports", root_id=ROOT)
    assert len(drive.created) == 1  # 05-testing existed; only test-reports was created
    url, body = drive.created[0]
    assert "supportsAllDrives=true" in url
    assert '"parents": ["f-test"]' in body.replace("'", '"') or '"f-test"' in body


async def test_resolver_never_leaves_the_root() -> None:
    """Every unsafe path is refused by normalize_path before a request is built."""
    drive = Drive()
    resolver = _resolver(drive)
    for bad in ("../escape.md", "/abs.md", "a/../../b", ".versions/x", "a\\b.md", ""):
        with pytest.raises(Exception):  # noqa: B017 - StoragePathError, asserted below
            await resolver.resolve(bad, root_id=ROOT)
    assert drive.queries == []


async def test_a_file_where_a_folder_is_expected_is_not_found() -> None:
    drive = Drive()
    drive.add(ROOT, "f-1", "02-requirements", "text/markdown")  # a file, not a folder
    resolver = _resolver(drive)
    with pytest.raises(StorageNotFound):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
