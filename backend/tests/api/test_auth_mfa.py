from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, User
from tests.factories import DEFAULT_PASSWORD, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def test_enrol_and_confirm(client: AsyncClient, db: AsyncSession, settings: Settings) -> None:
    await make_user(db, settings)
    await _login(client)
    enrol = await client.post("/api/v1/auth/mfa/enroll")
    assert enrol.status_code == 200
    secret = enrol.json()["secret"]
    assert "issuer=QC-Agent" in enrol.json()["otpauth_uri"]
    confirm = await client.post("/api/v1/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert confirm.status_code == 200
    assert len(confirm.json()["recovery_codes"]) == 10
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["mfa_enabled"] is True and me["mfa_verified"] is True
    user = (await db.scalars(select(User))).one()
    assert user.mfa_secret_enc is not None and secret not in user.mfa_secret_enc
    assert user.mfa_pending_secret_enc is None


async def test_confirm_with_wrong_code_fails(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    await _login(client)
    await client.post("/api/v1/auth/mfa/enroll")
    response = await client.post("/api/v1/auth/mfa/confirm", json={"code": "123456x"})
    assert response.status_code == 400


async def test_confirm_without_enrolment_is_conflict(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    await _login(client)
    response = await client.post("/api/v1/auth/mfa/confirm", json={"code": "123456"})
    assert response.status_code == 409


async def test_enrol_when_already_enabled_is_conflict(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings, mfa_secret=SECRET)
    await _login(client)
    assert (await client.post("/api/v1/auth/mfa/enroll")).status_code == 409


async def test_verify_marks_session(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings, mfa_secret=SECRET)
    await _login(client)
    response = await client.post("/api/v1/auth/mfa/verify", json={"code": pyotp.TOTP(SECRET).now()})
    assert response.status_code == 200
    assert response.json()["mfa_verified"] is True
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "auth.mfa_verified" in actions


async def test_replayed_code_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings, mfa_secret=SECRET)
    code = pyotp.TOTP(SECRET).now()
    first, second = await make_client(), await make_client()
    await _login(first)
    await _login(second)
    assert (await first.post("/api/v1/auth/mfa/verify", json={"code": code})).status_code == 200
    assert (await second.post("/api/v1/auth/mfa/verify", json={"code": code})).status_code == 401


async def test_recovery_code_works_once(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    enrolling = await make_client()
    await _login(enrolling)
    secret = (await enrolling.post("/api/v1/auth/mfa/enroll")).json()["secret"]
    codes = (
        await enrolling.post("/api/v1/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    ).json()["recovery_codes"]
    a, b = await make_client(), await make_client()
    await _login(a)
    await _login(b)
    assert (await a.post("/api/v1/auth/mfa/verify", json={"code": codes[0]})).status_code == 200
    assert (await b.post("/api/v1/auth/mfa/verify", json={"code": codes[0]})).status_code == 401
    user = (await db.scalars(select(User))).one()
    await db.refresh(user)
    assert len(user.recovery_codes_hash) == 9


async def test_five_bad_codes_lock_account_and_revoke_session(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings, mfa_secret=SECRET)
    await _login(client)
    valid = pyotp.TOTP(SECRET).now()
    bad = "000000" if valid != "000000" else "111111"
    for _ in range(5):
        response = await client.post("/api/v1/auth/mfa/verify", json={"code": bad})
        assert response.status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    locked = await reload(db, User, user.id)
    assert locked is not None and locked.locked_until is not None
    assert locked.locked_until > datetime.now(UTC) + timedelta(minutes=10)


async def test_correct_password_does_not_reset_mfa_failure_count(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings, mfa_secret=SECRET)
    await _login(client)
    valid = pyotp.TOTP(SECRET).now()
    bad = "000000" if valid != "000000" else "111111"
    for _ in range(4):
        assert (await client.post("/api/v1/auth/mfa/verify", json={"code": bad})).status_code == 401
    await _login(client)
    assert (await client.post("/api/v1/auth/mfa/verify", json={"code": bad})).status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    locked = await reload(db, User, user.id)
    assert locked is not None and locked.locked_until is not None
