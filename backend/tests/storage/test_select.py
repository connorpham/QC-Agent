"""Unit tests for app.storage.select: connection roots, project root segments and adapter
choice. No database: connections are plain model instances."""

import os
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.db.models import StorageConnection
from app.storage.base import StorageError, StoragePathError, validate_root_segment
from app.storage.localfs import LocalFsBackend
from app.storage.select import backend_for, connection_backend, localfs_root, storage_binding

VALID_SECRET = "s" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        session_secret=VALID_SECRET,
        secret_encryption_key=Fernet.generate_key().decode(),
        local_storage_root=str(tmp_path / "workspace"),
    )


def _connection(root_path: str, type_: str = "localfs") -> StorageConnection:
    return StorageConnection(type=type_, name="Test", config={"root_path": root_path})


@pytest.mark.parametrize(
    ("root_path", "expected"), [(".", ""), ("archive", "archive"), ("clients/acme", "clients/acme")]
)
def test_localfs_root_resolves_inside_the_storage_root(
    tmp_path: Path, root_path: str, expected: str
) -> None:
    assert (
        localfs_root(root_path, _settings(tmp_path))
        == (tmp_path / "workspace" / expected).resolve()
    )


def test_localfs_root_accepts_an_absolute_path_inside_the_storage_root(tmp_path: Path) -> None:
    inside = tmp_path / "workspace" / "abs"
    assert localfs_root(str(inside), _settings(tmp_path)) == inside.resolve()


@pytest.mark.parametrize("root_path", ["..", "../outside", "/etc/qc", "archive/../../x"])
def test_localfs_root_rejects_paths_outside_the_storage_root(
    tmp_path: Path, root_path: str
) -> None:
    with pytest.raises(StorageError, match="inside LOCAL_STORAGE_ROOT"):
        localfs_root(root_path, _settings(tmp_path))


def test_localfs_root_rejects_a_symlink_pointing_outside(tmp_path: Path) -> None:
    (tmp_path / "workspace").mkdir()
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "workspace" / "link")
    with pytest.raises(StorageError, match="inside LOCAL_STORAGE_ROOT"):
        localfs_root("link", _settings(tmp_path))


@pytest.mark.parametrize("root", ["demo", "acme-2026", "a", "x.y_z", "0start", "A" * 80])
def test_valid_root_segments(root: str) -> None:
    assert validate_root_segment(root) == root


@pytest.mark.parametrize(
    "root",
    ["", ".hidden", "../x", "a/b", "/abs", "with space", "x" * 81, "dự-án", ".trash", "-dash"],
)
def test_invalid_root_segments(root: str) -> None:
    with pytest.raises(StoragePathError):
        validate_root_segment(root)


def test_backend_for_localfs_is_rooted_under_the_connection_root(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    backend = backend_for(_connection("archive"), "acme", settings)
    assert isinstance(backend, LocalFsBackend)
    assert backend.root == (tmp_path / "workspace" / "archive" / "acme").resolve()
    own = connection_backend(_connection("archive"), settings)
    assert isinstance(own, LocalFsBackend)
    assert own.root == (tmp_path / "workspace" / "archive").resolve()


def test_backend_for_rejects_bad_segments_and_unknown_types(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(StoragePathError):
        backend_for(_connection("."), "a/b", settings)
    with pytest.raises(StorageError, match="not available in this deployment"):
        backend_for(_connection(".", type_="sharepoint"), "acme", settings)
    with pytest.raises(StorageError, match="incomplete"):
        connection_backend(StorageConnection(type="localfs", name="x", config={}), settings)


def test_storage_binding_shape() -> None:
    connection_id = uuid.uuid4()
    assert storage_binding(connection_id, "demo") == {
        "connection_id": str(connection_id),
        "root": "demo",
    }
