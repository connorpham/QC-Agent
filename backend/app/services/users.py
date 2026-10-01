import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.emails import normalize_email
from app.core.passwords import generate_temporary_password, hash_password
from app.db.models import User
from app.services import audit
from app.services.auth import revoke_user_sessions


class DuplicateEmail(Exception):
    pass


class SelfLockout(Exception):
    pass


class InvalidUserChange(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    display_name: str,
    account_type: str,
    is_admin: bool,
    actor_id: uuid.UUID | None,
) -> tuple[User, str]:
    normalized = normalize_email(email)
    if await db.scalar(select(User.id).where(User.email == normalized)) is not None:
        raise DuplicateEmail(normalized)
    temporary = generate_temporary_password()
    user = User(
        email=normalized,
        password_hash=hash_password(temporary),
        display_name=display_name.strip(),
        account_type=account_type,
        is_admin=is_admin,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    await audit.record(
        db, "user.create", user_id=actor_id, target_type="user", target_id=str(user.id)
    )
    await db.commit()
    return user, temporary


async def update_user(
    db: AsyncSession,
    user: User,
    *,
    actor: User,
    display_name: str | None = None,
    is_active: bool | None = None,
    is_admin: bool | None = None,
) -> User:
    if user.id == actor.id and (is_active is False or is_admin is False):
        raise SelfLockout()
    if is_admin is True and user.account_type == "customer":
        raise InvalidUserChange("Customer accounts cannot be administrators.")
    changes: dict[str, object] = {}
    if display_name is not None:
        user.display_name = display_name.strip()
        changes["display_name"] = True
    if is_admin is not None:
        user.is_admin = is_admin
        changes["is_admin"] = is_admin
    if is_active is not None:
        user.is_active = is_active
        changes["is_active"] = is_active
        if not is_active:
            await revoke_user_sessions(db, user.id)
    await audit.record(
        db,
        "user.update",
        user_id=actor.id,
        target_type="user",
        target_id=str(user.id),
        details=changes,
    )
    await db.commit()
    return user


async def reset_password(db: AsyncSession, user: User, *, actor_id: uuid.UUID) -> str:
    temporary = generate_temporary_password()
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    await revoke_user_sessions(db, user.id)
    await audit.record(
        db, "user.reset_password", user_id=actor_id, target_type="user", target_id=str(user.id)
    )
    await db.commit()
    return temporary


async def reset_mfa(db: AsyncSession, user: User, *, actor_id: uuid.UUID) -> None:
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_pending_secret_enc = None
    user.mfa_last_counter = None
    user.recovery_codes_hash = []
    await revoke_user_sessions(db, user.id)
    await audit.record(
        db, "user.reset_mfa", user_id=actor_id, target_type="user", target_id=str(user.id)
    )
    await db.commit()
