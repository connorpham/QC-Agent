from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.config import Settings
from app.core.passwords import verify_password
from app.db.models import User
from tests.factories import DEFAULT_PASSWORD, make_session_token, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]
NEW_PASSWORD = "a-brand-new-passphrase"


def _with_probe_routes(app: FastAPI) -> FastAPI:
    @app.get("/api/v1/_probe/user")
    async def probe_user(user: CurrentUser) -> dict[str, str]:
        return {"email": user.email}

    @app.get("/api/v1/_probe/admin")
    async def probe_admin(user: AdminUser) -> dict[str, str]:
        return {"email": user.email}

    return app


async def test_current_user_requires_mfa_and_password_change(
    app: FastAPI, make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _with_probe_routes(app)
    user = await make_user(db, settings, must_change_password=True)
    no_mfa = await make_client(await make_session_token(db, settings, user, mfa_verified=False))
    assert (await no_mfa.get("/api/v1/_probe/user")).status_code == 401
    mfa = await make_client(await make_session_token(db, settings, user))
    response = await mfa.get("/api/v1/_probe/user")
    assert response.status_code == 403
    assert response.json() == {"detail": "Password change required."}


async def test_require_admin(
    app: FastAPI, make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _with_probe_routes(app)
    member = await make_user(db, settings)
    admin = await make_user(db, settings, email="root@example.com", is_admin=True)
    assert (
        await (await make_client(await make_session_token(db, settings, member))).get(
            "/api/v1/_probe/admin"
        )
    ).status_code == 403
    assert (
        await (await make_client(await make_session_token(db, settings, admin))).get(
            "/api/v1/_probe/admin"
        )
    ).status_code == 200


async def test_change_password_success_revokes_other_sessions(
    app: FastAPI, make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _with_probe_routes(app)
    user = await make_user(db, settings, must_change_password=True)
    other = await make_client(await make_session_token(db, settings, user))
    current = await make_client(await make_session_token(db, settings, user))
    response = await current.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204
    assert (await current.get("/api/v1/_probe/user")).status_code == 200
    assert (await other.get("/api/v1/auth/me")).status_code == 401
    refreshed = await reload(db, User, user.id)
    assert refreshed is not None
    assert refreshed.must_change_password is False
    assert verify_password(refreshed.password_hash, NEW_PASSWORD)


async def test_change_password_rejects_wrong_current(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, user))
    response = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": ["Current password is incorrect."]}


async def test_change_password_enforces_policy_and_difference(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, user))
    weak = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 400
    assert "Password must be at least 12 characters." in weak.json()["detail"]
    same = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD},
    )
    assert same.status_code == 400
    assert "New password must differ from the current password." in same.json()["detail"]


async def test_change_password_requires_mfa(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, user, mfa_verified=False))
    response = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401
