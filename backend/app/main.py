import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.agent.analyzer import Analyzer, SkipAnalyzer
from app.api.routes import (
    auth,
    documents,
    health,
    projects,
    storage_connections,
    uploads,
    users,
)
from app.api.routes import taxonomy as taxonomy_routes
from app.core.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.db.session import dispose_engine, get_sessionmaker, init_engine, is_initialised
from app.ingestion.taxonomy import load_taxonomy
from app.services.pipeline import PipelineContext, cancel_background, requeue_stale_items
from app.services.storage_connections import ensure_default_connection

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-qc-agent"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, analyzer: Analyzer | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    templates_dir = Path(app_settings.templates_dir) if app_settings.templates_dir else None
    taxonomy = load_taxonomy(templates_dir)  # validates the taxonomy at startup
    pipeline = PipelineContext(
        settings=app_settings, taxonomy=taxonomy, analyzer=analyzer or SkipAnalyzer()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not is_initialised():
            init_engine(app_settings.database_url)
        async with get_sessionmaker()() as db:
            await ensure_default_connection(db)
        requeued = await requeue_stale_items(pipeline)
        if requeued:
            logger.info("Re-queued %d upload items left in progress", requeued)
        yield
        await cancel_background()  # requeued work must not outlive the engine
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
    app.state.analyzer = pipeline.analyzer
    app.state.pipeline = pipeline
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
    app.include_router(storage_connections.router, prefix=API_PREFIX)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(taxonomy_routes.router, prefix=API_PREFIX)
    app.include_router(uploads.router, prefix=API_PREFIX)
    app.include_router(documents.router, prefix=API_PREFIX)
    return app
