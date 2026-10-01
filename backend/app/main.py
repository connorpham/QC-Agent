from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes import auth, health, projects, users
from app.api.routes import taxonomy as taxonomy_routes
from app.core.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.db.session import dispose_engine, init_engine, is_initialised
from app.ingestion.taxonomy import load_taxonomy

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-qc-agent"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    templates_dir = Path(app_settings.templates_dir) if app_settings.templates_dir else None
    taxonomy = load_taxonomy(templates_dir)  # validates the taxonomy at startup

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not is_initialised():
            init_engine(app_settings.database_url)
        yield
        await dispose_engine()

    app = FastAPI(
        title="QC-Agent",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs" if app_settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if app_settings.expose_docs else None,
    )
    app.state.settings = app_settings
    app.state.taxonomy = taxonomy
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
    app.include_router(users.router, prefix=API_PREFIX)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(taxonomy_routes.router, prefix=API_PREFIX)
    return app
