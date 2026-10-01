import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, Project, ProjectMember, User
from tests.factories import make_connection, make_session_token, make_user

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def _client_for(
    make_client: MakeClient, db: AsyncSession, settings: Settings, user: User
) -> AsyncClient:
    return await make_client(await make_session_token(db, settings, user))


async def _project_with_roles(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> dict[str, object]:
    owner = await make_user(db, settings, email="owner@example.com", display_name="Owner")
    editor = await make_user(db, settings, email="editor@example.com", display_name="Editor")
    viewer = await make_user(db, settings, email="viewer@example.com", display_name="Viewer")
    client_user = await make_user(
        db, settings, email="c@client.com", display_name="Client", account_type="customer"
    )
    outsider = await make_user(db, settings, email="out@example.com", display_name="Out")
    owner_c = await _client_for(make_client, db, settings, owner)
    created = await owner_c.post("/api/v1/projects", json={"name": "Dự án Cổng Khách hàng"})
    assert created.status_code == 201
    pid = created.json()["id"]
    members = [
        {"user_id": str(owner.id), "role": "owner"},
        {"user_id": str(editor.id), "role": "editor"},
        {"user_id": str(viewer.id), "role": "viewer"},
        {"user_id": str(client_user.id), "role": "client"},
    ]
    assert (await owner_c.put(f"/api/v1/projects/{pid}/members", json=members)).status_code == 200
    return {
        "pid": pid,
        "owner": owner_c,
        "editor": await _client_for(make_client, db, settings, editor),
        "viewer": await _client_for(make_client, db, settings, viewer),
        "client": await _client_for(make_client, db, settings, client_user),
        "outsider": await _client_for(make_client, db, settings, outsider),
        "users": {"owner": owner, "editor": editor, "viewer": viewer, "client": client_user},
    }


async def test_create_project_with_vietnamese_name(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    first = await c.post(
        "/api/v1/projects", json={"name": "Dự án Cổng Khách hàng", "client_name": "ACME"}
    )
    second = await c.post("/api/v1/projects", json={"name": "Dự án Cổng Khách hàng"})
    assert first.status_code == second.status_code == 201
    assert first.json()["slug"] == "du-an-cong-khach-hang"
    assert second.json()["slug"] == "du-an-cong-khach-hang-2"
    assert first.json()["my_role"] == "owner"
    assert first.json()["settings"] == {
        "model": "claude-opus-5",
        "check_budget_usd": 1.0,
        "normalize_budget_usd": 2.0,
    }
    member = (await db.scalars(select(ProjectMember))).first()
    assert member is not None and member.role == "owner"
    assert "project.create" in (await db.scalars(select(AuditLog.action))).all()


async def test_blank_name_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    c = await _client_for(make_client, db, settings, await make_user(db, settings))
    assert (await c.post("/api/v1/projects", json={"name": "   "})).status_code == 422


async def test_customer_cannot_create_project(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    customer = await make_user(db, settings, email="c@client.com", account_type="customer")
    c = await _client_for(make_client, db, settings, customer)
    assert (await c.post("/api/v1/projects", json={"name": "X"})).status_code == 403


async def test_role_matrix(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    pid = ctx["pid"]
    url = f"/api/v1/projects/{pid}"
    for role in ("owner", "editor", "viewer", "client"):
        response = await ctx[role].get(url)  # type: ignore[attr-defined]
        assert response.status_code == 200, role
        assert response.json()["my_role"] == role
    assert (await ctx["client"].get(url)).json()["settings"] is None  # type: ignore[attr-defined]
    assert (await ctx["client"].get(url)).json()["storage"] is None  # type: ignore[attr-defined]
    assert (await ctx["outsider"].get(url)).status_code == 404  # type: ignore[attr-defined]
    for role in ("editor", "viewer", "client"):
        response = await ctx[role].patch(url, json={"name": "Renamed"})  # type: ignore[attr-defined]
        assert response.status_code == 403, role
    assert (await ctx["client"].get(f"{url}/members")).status_code == 403  # type: ignore[attr-defined]
    assert (await ctx["viewer"].get(f"{url}/members")).status_code == 200  # type: ignore[attr-defined]


async def test_owner_updates_settings_with_merge_and_validation(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    owner: AsyncClient = ctx["owner"]  # type: ignore[assignment]
    url = f"/api/v1/projects/{ctx['pid']}"
    ok = await owner.patch(url, json={"settings": {"check_budget_usd": 0.5}, "client_name": None})
    assert ok.status_code == 200
    assert ok.json()["settings"]["check_budget_usd"] == 0.5
    assert ok.json()["settings"]["normalize_budget_usd"] == 2.0
    assert ok.json()["client_name"] is None
    assert (await owner.patch(url, json={"settings": {"check_budget_usd": 0}})).status_code == 422
    assert (await owner.patch(url, json={"settings": {"unknown": 1}})).status_code == 422


async def test_list_projects_scoped_by_membership_and_admin_sees_all(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    outsider: AsyncClient = ctx["outsider"]  # type: ignore[assignment]
    assert (await outsider.get("/api/v1/projects")).json() == []
    client_list = (await ctx["client"].get("/api/v1/projects")).json()  # type: ignore[attr-defined]
    assert [p["id"] for p in client_list] == [ctx["pid"]]
    admin = await make_user(db, settings, email="root@example.com", is_admin=True)
    admin_c = await _client_for(make_client, db, settings, admin)
    admin_list = (await admin_c.get("/api/v1/projects")).json()
    assert [p["my_role"] for p in admin_list] == ["owner"]


async def test_archive_hides_project(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    owner: AsyncClient = ctx["owner"]  # type: ignore[assignment]
    url = f"/api/v1/projects/{ctx['pid']}"
    assert (await ctx["editor"].delete(url)).status_code == 403  # type: ignore[attr-defined]
    assert (await owner.delete(url)).status_code == 204
    assert (await owner.get(url)).status_code == 404
    assert (await owner.get("/api/v1/projects")).json() == []
    project = (await db.scalars(select(Project))).one()
    await db.refresh(project)
    assert project.archived_at is not None


async def test_member_rules(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    owner: AsyncClient = ctx["owner"]  # type: ignore[assignment]
    users = ctx["users"]  # type: ignore[assignment]
    url = f"/api/v1/projects/{ctx['pid']}/members"
    o, e, c = (str(users[k].id) for k in ("owner", "editor", "client"))  # type: ignore[index]
    cases = {
        "no owner": [{"user_id": e, "role": "editor"}],
        "customer as editor": [{"user_id": o, "role": "owner"}, {"user_id": c, "role": "editor"}],
        "internal as client": [{"user_id": o, "role": "owner"}, {"user_id": e, "role": "client"}],
        "duplicate": [{"user_id": o, "role": "owner"}, {"user_id": o, "role": "viewer"}],
        "unknown user": [
            {"user_id": o, "role": "owner"},
            {"user_id": "00000000-0000-0000-0000-000000000000", "role": "viewer"},
        ],
    }
    for name, payload in cases.items():
        response = await owner.put(url, json=payload)
        assert response.status_code == 422, name
    inactive = await make_user(db, settings, email="gone@example.com", is_active=False)
    response = await owner.put(
        url, json=[{"user_id": o, "role": "owner"}, {"user_id": str(inactive.id), "role": "viewer"}]
    )
    assert response.status_code == 422
    final = await owner.put(
        url, json=[{"user_id": o, "role": "owner"}, {"user_id": e, "role": "viewer"}]
    )
    assert final.status_code == 200
    assert {m["role"] for m in final.json()} == {"owner", "viewer"}
    assert (await ctx["client"].get(f"/api/v1/projects/{ctx['pid']}")).status_code == 404  # type: ignore[attr-defined]


async def test_create_project_on_a_chosen_connection_with_a_custom_root(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    user = await make_user(db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    c = await _client_for(make_client, db, settings, user)
    response = await c.post(
        "/api/v1/projects",
        json={
            "name": "Customer Portal",
            "storage_connection_id": str(archive.id),
            "storage_root": "cp-2026",
        },
    )
    assert response.status_code == 201
    assert response.json()["storage"] == {
        "connection_id": str(archive.id),
        "connection_name": "Archive",
        "type": "localfs",
        "root": "cp-2026",
    }
    assert (storage_root / "archive" / "cp-2026" / "project.yaml").exists()
    assert not (storage_root / "customer-portal").exists()


async def test_create_project_defaults_to_the_default_connection_and_slug(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    response = await c.post("/api/v1/projects", json={"name": "Plain", "storage_root": "  "})
    assert response.status_code == 201
    storage = response.json()["storage"]
    assert storage["connection_name"] == "Local storage" and storage["root"] == "plain"
    assert (storage_root / "plain" / "project.yaml").exists()


async def test_unknown_or_inactive_connection_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    unknown = await c.post(
        "/api/v1/projects", json={"name": "X", "storage_connection_id": str(uuid.uuid4())}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "Storage connection not found."
    inactive = await make_connection(db, name="Old", root_path="old", is_active=False)
    response = await c.post(
        "/api/v1/projects", json={"name": "Y", "storage_connection_id": str(inactive.id)}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Storage connection is not active."
    assert (await db.scalars(select(Project))).all() == []


async def test_invalid_root_folders_are_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    for root in ("../x", "a/b", ".hidden", "x y", "/abs", "a" * 81, ".trash", "-dash"):
        response = await c.post("/api/v1/projects", json={"name": "X", "storage_root": root})
        assert response.status_code == 422, root
    assert (await db.scalars(select(Project))).all() == []


async def test_duplicate_root_on_same_connection_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    c = await _client_for(make_client, db, settings, user)
    first = await c.post("/api/v1/projects", json={"name": "First", "storage_root": "shared"})
    assert first.status_code == 201
    second = await c.post("/api/v1/projects", json={"name": "Second", "storage_root": "shared"})
    assert second.status_code == 422 and "already used" in second.json()["detail"]
    # the same root on another connection is a different folder
    elsewhere = await c.post(
        "/api/v1/projects",
        json={"name": "Third", "storage_connection_id": str(archive.id), "storage_root": "shared"},
    )
    assert elsewhere.status_code == 201
    # a custom root equal to a project's default root (its slug) is refused as well
    assert (await c.post("/api/v1/projects", json={"name": "Plain"})).status_code == 201
    clash = await c.post("/api/v1/projects", json={"name": "Clash", "storage_root": "plain"})
    assert clash.status_code == 422
    names = sorted(p.name for p in (await db.scalars(select(Project))).all())
    assert names == ["First", "Plain", "Third"]


async def test_root_uniqueness_ignores_case(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    """macOS, Windows and the Plan 3b cloud backends treat 'Acme' and 'acme' as one folder."""
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    first = await c.post("/api/v1/projects", json={"name": "First", "storage_root": "Acme"})
    assert first.status_code == 201
    second = await c.post("/api/v1/projects", json={"name": "Second", "storage_root": "acme"})
    assert second.status_code == 422 and "already used" in second.json()["detail"]
    names = sorted(p.name for p in (await db.scalars(select(Project))).all())
    assert names == ["First"]
