from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, AuthSession, User
from tests.factories import DEFAULT_PASSWORD, make_session_token, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def _login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD):  # type: ignore[no-untyped-def]
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_sets_cookie_and_requires_mfa(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    response = await _login(client, "alice@example.com")
    assert response.status_code == 200
    assert response.json() == {"mfa_enrolled": False, "must_change_password": False}
    assert "qc_session" in client.cookies
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["mfa_verified"] is False
    sessions = (await db.scalars(select(AuthSession))).all()
    assert len(sessions) == 1 and sessions[0].mfa_verified is False
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "auth.login" in actions


async def test_email_case_and_spaces_are_ignored(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    response = await _login(client, "  Alice@Example.COM ")
    assert response.status_code == 200


async def test_wrong_password_and_unknown_email_share_one_message(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    wrong = await _login(client, "alice@example.com", "not-the-password")
    unknown = await _login(client, "bob@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid e-mail or password."}


async def test_lockout_after_five_failures(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    for _ in range(5):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401
    assert (await _login(client, "alice@example.com")).status_code == 401  # locked
    locked = await reload(db, User, user.id)
    assert locked is not None and locked.locked_until is not None
    locked.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert (await _login(client, "alice@example.com")).status_code == 200


async def test_inactive_user_cannot_log_in(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings, is_active=False)
    assert (await _login(client, "alice@example.com")).status_code == 401


async def test_logout_revokes_session(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    await _login(client, "alice@example.com")
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    session = (await db.scalars(select(AuthSession))).one()
    assert session.revoked_at is not None


async def test_revoked_or_expired_token_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    expired = await make_session_token(db, settings, user, expires_in=timedelta(seconds=-1))
    assert (await (await make_client(expired)).get("/api/v1/auth/me")).status_code == 401
    valid = await make_session_token(db, settings, user)
    c = await make_client(valid)
    assert (await c.get("/api/v1/auth/me")).status_code == 200
    assert (await c.post("/api/v1/auth/logout")).status_code == 204
    assert (await (await make_client(valid)).get("/api/v1/auth/me")).status_code == 401


async def test_me_without_cookie_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_login_is_rate_limited(
    make_app: Callable[..., FastAPI], make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    app = make_app(rate_limit_auth_per_5min=3)
    c = await make_client(app_=app)
    for _ in range(3):
        await _login(c, "nobody@example.com")
    response = await _login(c, "nobody@example.com")
    assert response.status_code == 429


async def test_cookie_flags_when_secure(
    make_app: Callable[..., FastAPI], make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    c = await make_client(app_=make_app(cookie_secure=True))
    response = await _login(c, "alice@example.com")
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header
