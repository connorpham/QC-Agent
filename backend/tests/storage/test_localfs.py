import os
from pathlib import Path

import pytest

from app.storage.base import StoragePathError
from app.storage.localfs import LocalFsBackend


async def test_layout_on_disk(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path / "root")
    await backend.put_file("02-requirements/srs--a.md", b"one", "text/markdown")
    await backend.put_file("02-requirements/srs--a.md", b"two", "text/markdown")
    assert (tmp_path / "root/02-requirements/srs--a.md").read_bytes() == b"two"
    assert (tmp_path / "root/.versions/02-requirements/srs--a.md/1").read_bytes() == b"one"
    await backend.move_to_trash("02-requirements/srs--a.md")
    assert (tmp_path / "root/.trash/02-requirements/srs--a.md").read_bytes() == b"two"
    assert not list((tmp_path / "root/02-requirements").glob("*.tmp-*"))


async def test_symlink_inside_root_cannot_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "03-design")
    backend = LocalFsBackend(root)
    with pytest.raises(StoragePathError):
        await backend.put_file("03-design/leak.md", b"x", "text/markdown")
    assert not (outside / "leak.md").exists()


async def test_health_reports_unwritable_root(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    status = await LocalFsBackend(blocker / "root").health()
    assert status.ok is False and "not writable" in status.detail
