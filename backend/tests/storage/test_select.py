"""Unit tests for backend_for: choosing and configuring a StorageBackend from a
project's ``storage`` binding."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.storage.base import StorageError
from app.storage.localfs import LocalFsBackend
from app.storage.select import LOCALFS, backend_for, localfs_binding

VALID_SECRET = "s" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        session_secret=VALID_SECRET,
        secret_encryption_key=Fernet.generate_key().decode(),
        local_storage_root=str(tmp_path),
    )


def test_unknown_storage_type_raises(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="not available in this deployment"):
        backend_for({"type": "sharepoint"}, _settings(tmp_path))


def test_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="incomplete"):
        backend_for({"type": LOCALFS}, _settings(tmp_path))


def test_non_string_root_raises(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="incomplete"):
        backend_for({"type": LOCALFS, "root": 123}, _settings(tmp_path))


def test_empty_root_raises(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="incomplete"):
        backend_for({"type": LOCALFS, "root": ""}, _settings(tmp_path))


def test_happy_path_returns_localfs_backend_rooted_under_local_storage_root(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    backend = backend_for(localfs_binding("acme-project"), settings)
    assert isinstance(backend, LocalFsBackend)
    assert backend.root == Path(settings.local_storage_root) / "acme-project"
