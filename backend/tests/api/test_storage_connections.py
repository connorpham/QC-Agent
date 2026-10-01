"""Admin storage-connection API: create, update, default, deactivation rules, test; and the
``available`` list internal users read when creating a project."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.db.models import AuditLog, StorageConnection, User
from app.ingestion.taxonomy import Taxonomy
from app.services.storage_connections import set_default
from tests.factories import make_connection, make_project, make_session_token, make_user

MakeClient = Callable[..., Awaitable[AsyncClient]]
URL = "/api/v1/storage-connections"


async def _admin(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> tuple[User, AsyncClient]:
    admin = await make_user(
        db, settings, email="root@example.com", display_name="Root", is_admin=True
    )
    return admin, await make_client(await make_session_token(db, settings, admin))


async def _actions(db: AsyncSession) -> list[str]:
    return list((await db.scalars(select(AuditLog.action))).all())


async def test_non_admins_are_forbidden_and_available_is_for_internal_users(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    member = await make_user(db, settings)
    customer = await make_user(db, settings, email="c@client.com", account_type="customer")
    member_c = await make_client(await make_session_token(db, settings, member))
    customer_c = await make_client(await make_session_token(db, settings, customer))
    payload = {"type": "localfs", "name": "X", "config": {"root_path": "x"}}
    assert (await member_c.get(URL)).status_code == 403
    assert (await member_c.post(URL, json=payload)).status_code == 403
    assert (await customer_c.get(f"{URL}/available")).status_code == 403
    inactive = await make_connection(db, name="Old", root_path="old", is_active=False)
    await make_connection(db, name="Archive", root_path="archive")
    available = await member_c.get(f"{URL}/available")
    assert available.status_code == 200
    rows = available.json()
    assert [r["name"] for r in rows] == ["Local storage", "Archive"]  # default first
    assert rows[0]["is_default"] is True and rows[1]["is_default"] is False
    assert set(rows[0]) == {"id", "name", "type", "is_default"}  # no config, no secrets
    assert str(inactive.id) not in {r["id"] for r in rows}


async def test_admin_lists_the_default_connection(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    response = await admin.get(URL)
    assert response.status_code == 200
    (row,) = response.json()
    assert row["name"] == "Local storage" and row["type"] == "localfs"
    assert row["config"] == {"root_path": "."} and row["is_default"] is True
    assert row["is_active"] is True and row["has_secret"] is False
    assert "secret" not in row and "secret_enc" not in row


async def test_create_connection_and_test_it(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    _, admin = await _admin(make_client, db, settings)
    created = await admin.post(
        URL,
        json={"type": "localfs", "name": "  Archive  2026 ", "config": {"root_path": "archive"}},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Archive 2026" and body["is_default"] is False
    assert body["is_active"] is True and body["has_secret"] is False
    assert body["config"] == {"root_path": "archive"}
    tested = await admin.post(f"{URL}/{body['id']}/test")
    assert tested.status_code == 200
    assert tested.json() == {"ok": True, "detail": "ok"}
    assert (storage_root / "archive").is_dir()  # the health probe created the folder
    actions = await _actions(db)
    assert "storage_connection.created" in actions and "storage_connection.tested" in actions


async def test_secret_is_stored_encrypted_and_never_returned(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    created = await admin.post(
        URL,
        json={
            "type": "localfs",
            "name": "With secret",
            "config": {"root_path": "s"},
            "secret": "super-secret-value",
        },
    )
    assert created.status_code == 201 and created.json()["has_secret"] is True
    assert "super-secret-value" not in created.text
    row = await db.get(StorageConnection, uuid.UUID(created.json()["id"]))
    assert row is not None and row.secret_enc is not None
    assert "super-secret-value" not in row.secret_enc
    box = SecretBox(settings.secret_encryption_key)
    assert box.decrypt(row.secret_enc) == "super-secret-value"
    assert "super-secret-value" not in (await admin.get(URL)).text
    replaced = await admin.patch(f"{URL}/{row.id}", json={"secret": "another-value"})
    assert replaced.status_code == 200 and replaced.json()["has_secret"] is True
    await db.refresh(row)
    assert row.secret_enc is not None and box.decrypt(row.secret_enc) == "another-value"


async def test_root_path_outside_allowlist_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    _, admin = await _admin(make_client, db, settings)
    outside = ("/etc/qc", "../outside", str(storage_root.parent / "elsewhere"))
    for index, root_path in enumerate(outside):
        response = await admin.post(
            URL,
            json={"type": "localfs", "name": f"Bad {index}", "config": {"root_path": root_path}},
        )
        assert response.status_code == 422, root_path
        assert "inside LOCAL_STORAGE_ROOT" in response.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(StorageConnection)) == 1


async def test_validation_rules(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    cases = {
        "unsupported type": {"type": "sharepoint", "name": "SP", "config": {"site": "x"}},
        "unknown type": {"type": "ftp", "name": "F", "config": {}},
        "extra config key": {
            "type": "localfs",
            "name": "L",
            "config": {"root_path": "x", "bucket": "y"},
        },
        "missing root_path": {"type": "localfs", "name": "M", "config": {}},
        "blank name": {"type": "localfs", "name": "   ", "config": {"root_path": "x"}},
    }
    for name, payload in cases.items():
        assert (await admin.post(URL, json=payload)).status_code == 422, name
    duplicate = {"type": "localfs", "name": "Local storage", "config": {"root_path": "x"}}
    assert (await admin.post(URL, json=duplicate)).status_code == 409
    assert (await admin.patch(f"{URL}/{uuid.uuid4()}", json={"name": "Nope"})).status_code == 404


async def test_set_default_moves_the_flag(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    moved = await admin.patch(f"{URL}/{archive.id}", json={"is_default": True})
    assert moved.status_code == 200 and moved.json()["is_default"] is True
    rows = {r["name"]: r for r in (await admin.get(URL)).json()}
    assert rows["Local storage"]["is_default"] is False and rows["Archive"]["is_default"] is True
    assert "storage_connection.default_changed" in await _actions(db)
    assert (await admin.patch(f"{URL}/{archive.id}", json={"is_default": False})).status_code == 422
    inactive = await make_connection(db, name="Old", root_path="old", is_active=False)
    assert (await admin.patch(f"{URL}/{inactive.id}", json={"is_default": True})).status_code == 409
    available = (await admin.get(f"{URL}/available")).json()
    assert [r["name"] for r in available] == ["Archive", "Local storage"]


async def test_deactivation_rules(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    admin_user, admin = await _admin(make_client, db, settings)
    default_id = (await admin.get(URL)).json()[0]["id"]
    refused = await admin.patch(f"{URL}/{default_id}", json={"is_active": False})
    assert refused.status_code == 409 and "default" in refused.json()["detail"]
    archive = await make_connection(db, name="Archive", root_path="archive")
    project = await make_project(
        db, settings, taxonomy, owner=admin_user, name="On archive", connection_id=archive.id
    )
    in_use = await admin.patch(f"{URL}/{archive.id}", json={"is_active": False})
    assert in_use.status_code == 409 and "1 active project" in in_use.json()["detail"]
    assert (await admin.delete(f"/api/v1/projects/{project.id}")).status_code == 204  # archive it
    deactivated = await admin.patch(f"{URL}/{archive.id}", json={"is_active": False})
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    available_ids = {r["id"] for r in (await admin.get(f"{URL}/available")).json()}
    assert str(archive.id) not in available_ids
    reactivated = await admin.patch(f"{URL}/{archive.id}", json={"is_active": True})
    assert reactivated.status_code == 200 and reactivated.json()["is_active"] is True
    assert (await _actions(db)).count("storage_connection.updated") == 2


async def test_update_name_and_config(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    updated = await admin.patch(
        f"{URL}/{archive.id}", json={"name": "Archive 2", "config": {"root_path": "archive-2"}}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Archive 2"
    assert updated.json()["config"] == {"root_path": "archive-2"}
    taken = await admin.patch(f"{URL}/{archive.id}", json={"name": "Local storage"})
    assert taken.status_code == 409
    bad = await admin.patch(f"{URL}/{archive.id}", json={"config": {"root_path": "../x"}})
    assert bad.status_code == 422
    entry = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "storage_connection.updated"))
    ).one()
    assert entry.details == {"fields": ["config", "name"]}


async def test_concurrent_set_default_leaves_exactly_one_default(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with db_sessionmaker() as setup:
        admin = await make_user(setup, settings, email="root@example.com", is_admin=True)
        a = await make_connection(setup, name="A", root_path="a")
        b = await make_connection(setup, name="B", root_path="b")
        admin_id, a_id, b_id = admin.id, a.id, b.id
    async with db_sessionmaker() as db_a, db_sessionmaker() as db_b:
        conn_a = await db_a.get_one(StorageConnection, a_id)
        conn_b = await db_b.get_one(StorageConnection, b_id)
        actor_a = await db_a.get_one(User, admin_id)
        actor_b = await db_b.get_one(User, admin_id)
        await asyncio.gather(
            set_default(db_a, conn_a, actor=actor_a), set_default(db_b, conn_b, actor=actor_b)
        )
    async with db_sessionmaker() as check:
        defaults = (
            await check.scalars(
                select(StorageConnection).where(StorageConnection.is_default.is_(True))
            )
        ).all()
        assert len(defaults) == 1 and defaults[0].name in {"A", "B"}
