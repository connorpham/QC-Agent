from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession

router = APIRouter(tags=["meta"])


async def _check_database(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means the check failed
        return "error"
    return "ok"


@router.get("/health")
async def health(db: DbSession) -> JSONResponse:
    checks = {"database": await _check_database(db)}
    ok = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks},
        status_code=200 if ok else 503,
    )
