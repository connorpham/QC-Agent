import json
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    PipelineDep,
    TaxonomyDep,
    Uploader,
    resolve_role,
)
from app.db.models import Project, Upload, UploadItem, User
from app.ingestion.intake import IntakeLimits, Rejection
from app.schemas.uploads import (
    ConfirmTypeRequest,
    RejectionOut,
    TaskOut,
    UploadItemOut,
    UploadItemSpec,
    UploadOut,
)
from app.services import uploads as uploads_service
from app.services.consent import has_consent
from app.services.pipeline import publish_confirmed_item, run_upload

router = APIRouter(tags=["uploads"])
_SPECS = TypeAdapter(list[UploadItemSpec])
CONSENT_REQUIRED = (
    "The project owner must confirm LLM data processing before documents can be uploaded."
)


def item_out(item: UploadItem, document_id: uuid.UUID | None) -> UploadItemOut:
    return UploadItemOut(
        id=item.id,
        upload_id=item.upload_id,
        original_name=item.original_name,
        ext=item.ext,
        size=item.size,
        sha256=item.sha256,
        selected_doc_type=item.selected_doc_type,
        final_doc_type=item.final_doc_type,
        title=item.title,
        intent=item.intent,
        target_document_id=item.target_document_id,
        visibility=item.visibility,
        status=item.status,
        type_check=item.type_check,
        check_explanation=item.check_explanation,
        suggested_doc_type=item.suggested_doc_type,
        version_hint_document_id=item.version_hint_document_id,
        warnings=list(item.conversion_meta.get("warnings", [])),
        conversion_meta={k: v for k, v in item.conversion_meta.items() if k != "warnings"},
        error=item.error,
        document_id=document_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _upload_out(db: AsyncSession, upload: Upload, rejected: list[Rejection]) -> UploadOut:
    items = await uploads_service.list_items(db, upload.id)
    documents = await uploads_service.published_document_ids(db, [i.id for i in items])
    return UploadOut(
        id=upload.id,
        project_id=upload.project_id,
        uploaded_by=upload.uploaded_by,
        created_at=upload.created_at,
        items=[item_out(item, documents.get(item.id)) for item in items],
        rejected=[RejectionOut(name=r.name, reason=r.reason) for r in rejected],
    )


def _parse_specs(items: str, count: int) -> list[UploadItemSpec]:
    try:
        specs = _SPECS.validate_python(json.loads(items))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="The items part is not valid.") from exc
    if len(specs) != count:
        raise HTTPException(
            status_code=422, detail="The items part must have one entry per uploaded file."
        )
    return specs


@router.post("/projects/{project_id}/uploads", response_model=UploadOut, status_code=201)
async def create_upload(
    ctx: Uploader,
    db: DbSession,
    settings: AppSettings,
    taxonomy: TaxonomyDep,
    pipeline: PipelineDep,
    background: BackgroundTasks,
    files: Annotated[list[UploadFile], File()],
    items: Annotated[str, Form()],
) -> UploadOut:
    if not has_consent(ctx.project):
        raise HTTPException(status_code=409, detail=CONSENT_REQUIRED)
    specs = _parse_specs(items, len(files))
    upload_id = uuid.uuid4()
    limits = IntakeLimits.from_megabytes(settings.max_upload_file_mb, settings.max_upload_batch_mb)
    staged, rejections = await uploads_service.stage_files(
        [uploads_service.IncomingFile(name=f.filename or "file", read=f.read) for f in files],
        specs,
        staging_dir=uploads_service.staging_dir_for(pipeline.staging_root, upload_id),
        limits=limits,
    )
    try:
        upload, rejected = await uploads_service.create_upload(
            db,
            project=ctx.project,
            uploader=ctx.user,
            role=ctx.role,
            upload_id=upload_id,
            staged=staged,
            rejections=rejections,
            taxonomy=taxonomy,
            staging_root=pipeline.staging_root,
        )
    except uploads_service.UploadError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": exc.message,
                "rejected": [{"name": r.name, "reason": r.reason} for r in exc.rejections],
            },
        ) from exc
    background.add_task(run_upload, pipeline, upload.id)
    return await _upload_out(db, upload, rejected)


async def _upload_for(db: AsyncSession, upload_id: uuid.UUID, user: User) -> tuple[Upload, str]:
    upload = await db.get(Upload, upload_id)
    project = None if upload is None else await db.get(Project, upload.project_id)
    role = None if project is None else await resolve_role(db, project, user)
    if upload is None or role is None or (role == "client" and upload.uploaded_by != user.id):
        raise HTTPException(status_code=404, detail="Upload not found.")
    return upload, role


@router.get("/uploads/{upload_id}", response_model=UploadOut)
async def get_upload(upload_id: uuid.UUID, user: CurrentUser, db: DbSession) -> UploadOut:
    upload, _ = await _upload_for(db, upload_id, user)
    return await _upload_out(db, upload, [])


@router.get("/me/tasks", response_model=list[TaskOut])
async def my_tasks(user: CurrentUser, db: DbSession) -> list[TaskOut]:
    return [
        TaskOut(item=item_out(item, None), project_id=project.id, project_name=project.name)
        for item, project in await uploads_service.my_tasks(db, user)
    ]


async def _actionable_item(
    db: AsyncSession, item_id: uuid.UUID, user: User
) -> tuple[UploadItem, Upload]:
    item = await db.get(UploadItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Upload item not found.")
    upload, role = await _upload_for(db, item.upload_id, user)
    if not uploads_service.may_act_on_item(upload, role, user):
        raise HTTPException(status_code=403, detail="You do not have access to this action.")
    return item, upload


@router.post("/upload-items/{item_id}/confirm-type", response_model=UploadItemOut)
async def confirm_type(
    item_id: uuid.UUID,
    body: ConfirmTypeRequest,
    user: CurrentUser,
    db: DbSession,
    taxonomy: TaxonomyDep,
    pipeline: PipelineDep,
    background: BackgroundTasks,
) -> UploadItemOut:
    item, upload = await _actionable_item(db, item_id, user)
    try:
        await uploads_service.confirm_type(
            db,
            item,
            doc_type_key=body.doc_type,
            taxonomy=taxonomy,
            actor=user,
            project_id=upload.project_id,
        )
    except uploads_service.ItemStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    background.add_task(publish_confirmed_item, pipeline, item.id)
    return item_out(item, None)


@router.post("/upload-items/{item_id}/retry", response_model=UploadItemOut)
async def retry_item(
    item_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    pipeline: PipelineDep,
    background: BackgroundTasks,
) -> UploadItemOut:
    item, upload = await _actionable_item(db, item_id, user)
    try:
        await uploads_service.retry_item(db, item, actor=user, project_id=upload.project_id)
    except uploads_service.ItemStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    background.add_task(run_upload, pipeline, upload.id, [item.id])
    return item_out(item, None)
