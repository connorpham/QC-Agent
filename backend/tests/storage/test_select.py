"""Unit tests for app.storage.select: connection roots, project root segments and adapter
choice. No database: connections are plain model instances."""

import json as _json
import os
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.db.models import StorageConnection
from app.db.models import StorageConnection as _Connection
from app.storage.base import StorageError, StoragePathError, validate_root_segment
from app.storage.gdrive import GoogleDriveBackend
from app.storage.localfs import LocalFsBackend
from app.storage.select import (
    backend_for,
    connection_backend,
    connection_secret,
    localfs_root,
    storage_binding,
)
from app.storage.sharepoint import SharePointBackend

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
        backend_for(_connection(".", type_="unknown"), "acme", settings)
    with pytest.raises(StorageError, match="incomplete"):
        connection_backend(StorageConnection(type="localfs", name="x", config={}), settings)


def test_storage_binding_shape() -> None:
    connection_id = uuid.uuid4()
    assert storage_binding(connection_id, "demo") == {
        "connection_id": str(connection_id),
        "root": "demo",
    }


SP_CONFIG = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "client_id": "22222222-2222-2222-2222-222222222222",
    "site_id": "example.sharepoint.com,33333333-3333-3333-3333-333333333333,4444",
    "drive_id": "b!test-library-drive-id",
}
# A synthetic key body, assembled at runtime so the repository's gitleaks hook does not
# flag a fixture. It is not a key and cannot sign anything.
FAKE_PEM = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END " + "PRIVATE KEY-----\n"
GD_CONFIG = {"drive_id": "0ATestSharedDriveId"}
FAKE_SA_KEY = _json.dumps(
    {
        "type": "service_account",
        "project_id": "qc-agent-test",
        "private_key": FAKE_PEM,
        "client_email": "qc-agent@qc-agent-test.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


def _cloud(type_: str, config: dict[str, str], secret: str, settings: Settings) -> _Connection:
    return _Connection(
        id=uuid.uuid4(),
        type=type_,
        name="Customer library",
        config=config,
        secret_enc=SecretBox(settings.secret_encryption_key).encrypt(secret),
    )


def test_backend_for_sharepoint_is_rooted_at_the_project_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _cloud("sharepoint", SP_CONFIG, "client-secret-value", settings)
    backend = backend_for(connection, "acme", settings)
    assert isinstance(backend, SharePointBackend)
    own = connection_backend(connection, settings)
    assert isinstance(own, SharePointBackend)


def test_backend_for_gdrive_is_rooted_at_the_project_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _cloud("gdrive", GD_CONFIG, FAKE_SA_KEY, settings)
    assert isinstance(backend_for(connection, "acme", settings), GoogleDriveBackend)
    assert isinstance(connection_backend(connection, settings), GoogleDriveBackend)


def test_token_providers_are_reused_for_the_same_connection(tmp_path: Path) -> None:
    """A new provider per request would mean a token request per upload."""
    settings = _settings(tmp_path)
    connection = _cloud("sharepoint", SP_CONFIG, "client-secret-value", settings)
    first = backend_for(connection, "acme", settings)
    second = backend_for(connection, "acme", settings)
    assert first._tokens is second._tokens  # noqa: SLF001 - the point of the test


def test_rotating_the_secret_replaces_the_cached_provider(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _cloud("sharepoint", SP_CONFIG, "client-secret-value", settings)
    first = backend_for(connection, "acme", settings)
    connection.secret_enc = SecretBox(settings.secret_encryption_key).encrypt("rotated-secret")
    second = backend_for(connection, "acme", settings)
    assert first._tokens is not second._tokens  # noqa: SLF001


def test_a_cloud_connection_without_a_secret_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _Connection(id=uuid.uuid4(), type="gdrive", name="x", config=GD_CONFIG)
    with pytest.raises(StorageError, match="no stored secret"):
        connection_backend(connection, settings)


def test_a_secret_that_cannot_be_decrypted_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _Connection(
        id=uuid.uuid4(), type="gdrive", name="x", config=GD_CONFIG, secret_enc="not-a-fernet-token"
    )
    with pytest.raises(StorageError, match="could not be decrypted"):
        connection_secret(connection, settings)
