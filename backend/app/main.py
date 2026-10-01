from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes import auth, health
from app.core.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.db.session import dispose_engine, init_engine, is_initialised

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-qc-agent"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not is_initialised():
            init_engine(app_settings.database_url)
        yield
        await dispose_engine()

    app = FastAPI(title="QC-Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.auth_limiter = SlidingWindowLimiter(
        limit=app_settings.rate_limit_auth_per_5min, window_seconds=300
    )

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "Missing CSRF header."}, status_code=403)
        return await call_next(request)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    return app
