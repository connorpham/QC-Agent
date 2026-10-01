"""Every StorageBackend adapter must pass this suite unchanged."""

import pytest

from app.storage.base import StorageBackend, StorageNotFound, StoragePathError

PATH = "02-requirements/srs--customer-portal.docx"
BAD_PATHS = [
    "../escape.txt",
    "/abs.txt",
    "C:/x.txt",
    "a/../../b",
    "",
    ".",
    "a\\b.txt",
    ".versions/x",
]


async def test_put_get_roundtrip_creates_folders(backend: StorageBackend) -> None:
    stored = await backend.put_file(PATH, b"v1", "application/octet-stream")
    assert stored.item_id and stored.version_id
    assert await backend.get_file(PATH) == b"v1"
    assert await backend.exists(PATH) is True
    assert await backend.exists("02-requirements/missing.docx") is False


async def test_overwrite_keeps_versions(backend: StorageBackend) -> None:
    first = await backend.put_file(PATH, b"v1", "application/octet-stream")
    second = await backend.put_file(PATH, b"v2", "application/octet-stream")
    assert first.version_id != second.version_id
    versions = await backend.list_versions(PATH)
    assert [v.version_id for v in versions] == [first.version_id, second.version_id]
    assert all(v.size > 0 for v in versions)
    assert await backend.get_version(PATH, first.version_id) == b"v1"
    assert await backend.get_version(PATH, second.version_id) == b"v2"
    assert await backend.get_file(PATH) == b"v2"


async def test_ensure_folder_is_idempotent(backend: StorageBackend) -> None:
    await backend.ensure_folder("05-testing/test-reports")
    await backend.ensure_folder("05-testing/test-reports")
    await backend.put_file(
        "05-testing/test-reports/test-report--sprint-1.md", b"# r", "text/markdown"
    )
    assert await backend.exists("05-testing/test-reports/test-report--sprint-1.md")


async def test_missing_file_and_version(backend: StorageBackend) -> None:
    with pytest.raises(StorageNotFound):
        await backend.get_file(PATH)
    await backend.put_file(PATH, b"v1", "application/octet-stream")
    with pytest.raises(StorageNotFound):
        await backend.get_version(PATH, "does-not-exist")
    with pytest.raises(StorageNotFound):
        await backend.move_to_trash("02-requirements/nothing.md")


async def test_move_to_trash(backend: StorageBackend) -> None:
    await backend.put_file(PATH, b"v1", "application/octet-stream")
    await backend.move_to_trash(PATH)
    assert await backend.exists(PATH) is False
    with pytest.raises(StorageNotFound):
        await backend.get_file(PATH)


async def test_unicode_and_spaces_in_names(backend: StorageBackend) -> None:
    path = "01-overview/other--tài liệu (bản cuối).md"
    await backend.put_file(path, "Nội dung".encode(), "text/markdown")
    assert (await backend.get_file(path)).decode() == "Nội dung"


@pytest.mark.parametrize("bad", BAD_PATHS)
async def test_unsafe_paths_are_rejected_everywhere(backend: StorageBackend, bad: str) -> None:
    with pytest.raises(StoragePathError):
        await backend.put_file(bad, b"x", "text/plain")
    with pytest.raises(StoragePathError):
        await backend.get_file(bad)
    with pytest.raises(StoragePathError):
        await backend.exists(bad)
    with pytest.raises(StoragePathError):
        await backend.ensure_folder(bad)
    with pytest.raises(StoragePathError):
        await backend.list_versions(bad)
    with pytest.raises(StoragePathError):
        await backend.get_version(bad, "1")
    with pytest.raises(StoragePathError):
        await backend.move_to_trash(bad)


async def test_health(backend: StorageBackend) -> None:
    status = await backend.health()
    assert status.ok is True
