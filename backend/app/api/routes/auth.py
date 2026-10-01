from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.cookies import clear_session_cookie, set_session_cookie
from app.api.deps import AppSettings, DbSession, SessionCtx, auth_rate_limit
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from app.services import audit
from app.services.auth import authenticate
from app.services.context import SessionContext

router = APIRouter(prefix="/auth", tags=["auth"])


def me_response(ctx: SessionContext) -> MeResponse:
    user = ctx.user
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        account_type=user.account_type,
        is_admin=user.is_admin,
        mfa_enabled=user.mfa_enabled,
        mfa_verified=ctx.auth_session.mfa_verified,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(auth_rate_limit)])
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession, settings: AppSettings
) -> LoginResponse:
    result = await authenticate(
        db,
        body.email,
        body.password,
        settings,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid e-mail or password.")
    set_session_cookie(response, result.token, settings)
    return LoginResponse(
        mfa_enrolled=result.user.mfa_enabled,
        must_change_password=result.user.must_change_password,
    )


@router.get("/me", response_model=MeResponse)
async def me(ctx: SessionCtx) -> MeResponse:
    return me_response(ctx)


@router.post("/logout", status_code=204)
async def logout(ctx: SessionCtx, response: Response, db: DbSession, settings: AppSettings) -> None:
    ctx.auth_session.revoked_at = datetime.now(UTC)
    await audit.record(db, "auth.logout", user_id=ctx.user.id)
    await db.commit()
    clear_session_cookie(response, settings)
