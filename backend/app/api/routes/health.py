from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AppSettings, DbSession
from app.services.storage_health import storage_check

router = APIRouter(tags=["meta"])


async def _check_database(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means the check failed
        return "error"
    return "ok"


@router.get("/health")
async def health(db: DbSession, settings: AppSettings) -> JSONResponse:
    database = await _check_database(db)
    # No database means no connection rows to read, so the storage check has nothing to say.
    storage = await storage_check(db, settings) if database == "ok" else "skipped"
    checks = {"database": database, "storage": storage}
    ok = database == "ok" and storage in ("ok", "skipped")
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks},
        status_code=200 if ok else 503,
    )
