from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, User
from tests.factories import make_session_token, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def _admin_client(  # type: ignore[no-untyped-def]
    make_client: MakeClient, db: AsyncSession, settings: Settings
):
    admin = await make_user(
        db, settings, email="root@example.com", display_name="Root", is_admin=True
    )
    return admin, await make_client(await make_session_token(db, settings, admin))


async def test_non_admin_is_forbidden(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    member = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, member))
    assert (await c.get("/api/v1/users")).status_code == 403


async def test_create_user_returns_temporary_password_that_works(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    response = await admin.post(
        "/api/v1/users",
        json={"email": "  Bob@Example.com ", "display_name": "Bob", "account_type": "internal"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "bob@example.com"
    assert body["user"]["must_change_password"] is True
    login = await (await make_client()).post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": body["temporary_password"]},
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    assert "user.create" in (await db.scalars(select(AuditLog.action))).all()


async def test_duplicate_email_is_case_insensitive(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    payload = {"display_name": "Bob", "account_type": "internal"}
    created = await admin.post("/api/v1/users", json={"email": "bob@example.com", **payload})
    assert created.status_code == 201
    dup = await admin.post("/api/v1/users", json={"email": "BOB@example.com", **payload})
    assert dup.status_code == 409


async def test_validation_errors(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    bad_email = await admin.post(
        "/api/v1/users", json={"email": "bob", "display_name": "Bob", "account_type": "internal"}
    )
    customer_admin = await admin.post(
        "/api/v1/users",
        json={
            "email": "c@client.com",
            "display_name": "C",
            "account_type": "customer",
            "is_admin": True,
        },
    )
    assert bad_email.status_code == 422
    assert customer_admin.status_code == 422


async def test_reset_password_revokes_sessions_and_unlocks(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    user = await make_user(db, settings)
    old = await make_client(await make_session_token(db, settings, user))
    assert (await old.get("/api/v1/auth/me")).status_code == 200
    response = await admin.post(f"/api/v1/users/{user.id}/reset-password")
    assert response.status_code == 200
    assert len(response.json()["temporary_password"]) >= 12
    assert (await old.get("/api/v1/auth/me")).status_code == 401
    refreshed = await reload(db, User, user.id)
    assert refreshed is not None and refreshed.must_change_password is True
    assert refreshed.locked_until is None


async def test_deactivate_revokes_sessions_and_blocks_login(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    user = await make_user(db, settings)
    old = await make_client(await make_session_token(db, settings, user))
    response = await admin.patch(f"/api/v1/users/{user.id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (await old.get("/api/v1/auth/me")).status_code == 401


async def test_admin_cannot_lock_themselves_out(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    root, admin = await _admin_client(make_client, db, settings)
    deactivate = await admin.patch(f"/api/v1/users/{root.id}", json={"is_active": False})
    assert deactivate.status_code == 409
    demote = await admin.patch(f"/api/v1/users/{root.id}", json={"is_admin": False})
    assert demote.status_code == 409


async def test_cannot_promote_customer_to_admin(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    customer = await make_user(db, settings, email="c@client.com", account_type="customer")
    response = await admin.patch(f"/api/v1/users/{customer.id}", json={"is_admin": True})
    assert response.status_code == 422


async def test_reset_mfa(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    user = await make_user(db, settings, mfa_secret="JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
    old = await make_client(await make_session_token(db, settings, user))
    assert (await admin.post(f"/api/v1/users/{user.id}/reset-mfa")).status_code == 204
    assert (await old.get("/api/v1/auth/me")).status_code == 401
    refreshed = await reload(db, User, user.id)
    assert refreshed is not None
    assert refreshed.mfa_enabled is False
    assert refreshed.mfa_secret_enc is None
    assert refreshed.recovery_codes_hash == []


async def test_unknown_user_is_404(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    response = await admin.post("/api/v1/users/00000000-0000-0000-0000-000000000000/reset-mfa")
    assert response.status_code == 404
