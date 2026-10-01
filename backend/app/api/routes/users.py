import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession
from app.db.models import User
from app.schemas.users import (
    CreateUserRequest,
    CreateUserResponse,
    TemporaryPasswordResponse,
    UpdateUserRequest,
    UserOut,
)
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])


async def _get_user(db: DbSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.get("", response_model=list[UserOut])
async def list_users(_: AdminUser, db: DbSession) -> list[UserOut]:
    users = (await db.scalars(select(User).order_by(User.email))).all()
    return [UserOut.model_validate(u) for u in users]


@router.post("", response_model=CreateUserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest, admin: AdminUser, db: DbSession
) -> CreateUserResponse:
    try:
        user, temporary = await users_service.create_user(
            db,
            email=body.email,
            display_name=body.display_name,
            account_type=body.account_type,
            is_admin=body.is_admin,
            actor_id=admin.id,
        )
    except users_service.DuplicateEmail as exc:
        raise HTTPException(
            status_code=409, detail="A user with this e-mail already exists."
        ) from exc
    return CreateUserResponse(user=UserOut.model_validate(user), temporary_password=temporary)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UpdateUserRequest, admin: AdminUser, db: DbSession
) -> UserOut:
    user = await _get_user(db, user_id)
    try:
        updated = await users_service.update_user(
            db,
            user,
            actor=admin,
            display_name=body.display_name,
            is_active=body.is_active,
            is_admin=body.is_admin,
        )
    except users_service.SelfLockout as exc:
        raise HTTPException(
            status_code=409, detail="You cannot deactivate or remove admin rights from yourself."
        ) from exc
    except users_service.InvalidUserChange as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return UserOut.model_validate(updated)


@router.post("/{user_id}/reset-password", response_model=TemporaryPasswordResponse)
async def reset_password(
    user_id: uuid.UUID, admin: AdminUser, db: DbSession
) -> TemporaryPasswordResponse:
    user = await _get_user(db, user_id)
    temporary = await users_service.reset_password(db, user, actor_id=admin.id)
    return TemporaryPasswordResponse(temporary_password=temporary)


@router.post("/{user_id}/reset-mfa", status_code=204)
async def reset_mfa(user_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    user = await _get_user(db, user_id)
    await users_service.reset_mfa(db, user, actor_id=admin.id)
