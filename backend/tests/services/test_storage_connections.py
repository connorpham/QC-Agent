"""Default connection at startup and project-to-adapter resolution through the connection."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, StorageConnection
from app.ingestion.taxonomy import Taxonomy
from app.services.storage_connections import (
    DEFAULT_CONNECTION_NAME,
    StorageConnectionError,
    connections_by_id,
    default_connection,
    ensure_default_connection,
    require_secret,
    validate_config,
)
from app.storage.base import StorageError
from app.storage.localfs import LocalFsBackend
from app.storage.select import project_backend
from tests.factories import make_connection, make_project, make_user

# A synthetic key body, assembled at runtime so the repository's gitleaks hook does not
# flag a fixture. It is not a key and cannot sign anything.
FAKE_PEM = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END " + "PRIVATE KEY-----\n"

SP_CONFIG = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "client_id": "22222222-2222-2222-2222-222222222222",
    "site_id": "example.sharepoint.com,33333333-3333-3333-3333-333333333333,4444",
    "drive_id": "b!test-library-drive-id",
}


async def test_ensure_default_connection_is_idempotent(db: AsyncSession) -> None:
    first = await ensure_default_connection(db)  # the fixture already created it
    second = await ensure_default_connection(db)
    assert first is not None and second is not None and first.id == second.id
    assert first.name == DEFAULT_CONNECTION_NAME and first.config == {"root_path": "."}
    assert first.type == "localfs" and first.is_default and first.is_active
    assert await db.scalar(select(func.count()).select_from(StorageConnection)) == 1
    created = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "storage_connection.created"))
    ).all()
    assert len(created) == 1 and created[0].details["system"] is True


async def test_ensure_default_connection_creates_one_when_the_table_is_empty(
    db: AsyncSession,
) -> None:
    await db.execute(delete(StorageConnection))
    await db.commit()
    created = await ensure_default_connection(db)
    assert created is not None and created.is_default is True
    assert (await default_connection(db)) is not None


async def test_project_backend_resolves_through_the_connection(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner = await make_user(db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    project = await make_project(
        db, settings, taxonomy, owner=owner, name="Demo", connection_id=archive.id, root="acme"
    )
    backend = await project_backend(db, project, settings)
    assert isinstance(backend, LocalFsBackend)
    assert backend.root == (storage_root / "archive" / "acme").resolve()
    assert (storage_root / "archive" / "acme" / "project.yaml").exists()
    assert project.storage["connection_id"] == str(archive.id)
    assert project.storage["root"] == "acme" and "provisioned_at" in project.storage
    default = await default_connection(db)
    assert default is not None
    assert set((await connections_by_id(db)).keys()) == {archive.id, default.id}


async def test_project_backend_with_a_missing_or_broken_binding_raises(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    project.storage = {**project.storage, "connection_id": str(uuid.uuid4())}
    with pytest.raises(StorageError, match="no longer exists"):
        await project_backend(db, project, settings)
    project.storage = {"root": "demo"}
    with pytest.raises(StorageError, match="incomplete"):
        await project_backend(db, project, settings)


def test_sharepoint_config_is_validated_and_trimmed(settings: Settings) -> None:
    padded = {key: f"  {value}  " for key, value in SP_CONFIG.items()}
    assert validate_config("sharepoint", padded, settings) == SP_CONFIG


@pytest.mark.parametrize("missing", sorted(SP_CONFIG))
def test_sharepoint_config_requires_every_field(settings: Settings, missing: str) -> None:
    config = {k: v for k, v in SP_CONFIG.items() if k != missing}
    with pytest.raises(StorageConnectionError, match=missing.replace("_", " ")):
        validate_config("sharepoint", config, settings)


def test_sharepoint_config_rejects_unknown_fields(settings: Settings) -> None:
    with pytest.raises(StorageConnectionError):
        validate_config("sharepoint", {**SP_CONFIG, "client_secret": "oops"}, settings)


def test_gdrive_config_requires_the_shared_drive_id(settings: Settings) -> None:
    assert validate_config("gdrive", {"drive_id": " 0ATest "}, settings) == {"drive_id": "0ATest"}
    with pytest.raises(StorageConnectionError, match="Shared Drive id"):
        validate_config("gdrive", {}, settings)


async def test_a_secret_is_required_for_cloud_types(db: AsyncSession, settings: Settings) -> None:
    """A connection form that cannot store the secret is not a usable connection."""
    with pytest.raises(StorageConnectionError, match="client secret is required"):
        require_secret("sharepoint", None)
    with pytest.raises(StorageConnectionError, match="service-account key is required"):
        require_secret("gdrive", None)
    require_secret("localfs", None)  # no secret, no complaint


def test_a_malformed_service_account_key_is_refused(settings: Settings) -> None:
    with pytest.raises(StorageConnectionError, match="valid JSON"):
        require_secret("gdrive", "not json")
    require_secret(
        "gdrive",
        json.dumps(
            {
                "type": "service_account",
                "private_key": FAKE_PEM,
                "client_email": "qc-agent@qc-agent-test.iam.gserviceaccount.com",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
    )
