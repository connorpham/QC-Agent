"""Run the real intake + pipeline from tests without HTTP: stage bytes, create the upload and
run ``run_upload`` with the given analyzer (SkipAnalyzer by default)."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.analyzer import Analyzer, SkipAnalyzer
from app.core.config import Settings
from app.db.models import Project, Upload, UploadItem, User
from app.ingestion.intake import IntakeLimits, Rejection
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services.pipeline import PipelineContext, run_upload
from app.services.uploads import (
    IncomingFile,
    create_upload,
    list_items,
    stage_files,
    staging_dir_for,
)
from tests.helpers.files import bytes_reader

__all__ = ["bytes_reader", "ingest", "pipeline_context"]


def pipeline_context(
    settings: Settings, taxonomy: Taxonomy, analyzer: Analyzer | None = None
) -> PipelineContext:
    return PipelineContext(
        settings=settings, taxonomy=taxonomy, analyzer=analyzer or SkipAnalyzer()
    )


async def ingest(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    *,
    project: Project,
    uploader: User,
    role: str,
    files: Sequence[tuple[str, bytes]],
    specs: Sequence[UploadItemSpec],
    analyzer: Analyzer | None = None,
    run: bool = True,
) -> tuple[Upload, list[UploadItem], list[Rejection]]:
    ctx = pipeline_context(settings, taxonomy, analyzer)
    upload_id = uuid.uuid4()
    limits = IntakeLimits.from_megabytes(settings.max_upload_file_mb, settings.max_upload_batch_mb)
    staged, rejections = await stage_files(
        [IncomingFile(name=name, read=bytes_reader(data)) for name, data in files],
        specs,
        staging_dir=staging_dir_for(ctx.staging_root, upload_id),
        limits=limits,
    )
    upload, rejected = await create_upload(
        db,
        project=project,
        uploader=uploader,
        role=role,
        upload_id=upload_id,
        staged=staged,
        rejections=rejections,
        taxonomy=taxonomy,
        staging_root=ctx.staging_root,
    )
    if run:
        await run_upload(ctx, upload.id)
    db.expire_all()  # the pipeline wrote through its own sessions
    # Reload what callers keep using: touching an expired attribute later would lazy-load
    # outside an await (MissingGreenlet under asyncpg).
    for instance in (upload, project, uploader):
        await db.refresh(instance)
    return upload, await list_items(db, upload.id), rejected
