import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.api.deps import (
    AnyMember,
    AppSettings,
    CurrentUser,
    DbSession,
    InternalMember,
    ProjectOwner,
    TaxonomyDep,
)
from app.db.models import INTERNAL_ROLES, Project, StorageConnection
from app.schemas.projects import (
    LlmConsentOut,
    LlmConsentRequest,
    MemberIn,
    MemberOut,
    ProjectCreate,
    ProjectOut,
    ProjectSettings,
    ProjectStorageOut,
    ProjectUpdate,
)
from app.services import audit
from app.services import consent as consent_service
from app.services import projects as projects_service
from app.services import storage_connections as connections_service
from app.storage.base import StorageError

router = APIRouter(prefix="/projects", tags=["projects"])


def _consent_out(project: Project) -> LlmConsentOut | None:
    if not project.llm_consent:
        return None
    return LlmConsentOut(
        confirmed_by_name=project.llm_consent["confirmed_by_name"],
        confirmed_at=project.llm_consent["confirmed_at"],
    )


def _connection_id(project: Project) -> uuid.UUID | None:
    raw = project.storage.get("connection_id")
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def storage_out(
    project: Project, connections: Mapping[uuid.UUID, StorageConnection]
) -> ProjectStorageOut | None:
    """The binding as internal roles see it; None when the connection row is gone."""
    connection_id = _connection_id(project)
    root = project.storage.get("root")
    connection = connections.get(connection_id) if connection_id is not None else None
    if connection is None or not isinstance(root, str):
        return None
    return ProjectStorageOut(
        connection_id=connection.id,
        connection_name=connection.name,
        type=connection.type,
        root=root,
    )


def _out(
    project: Project, role: str, connections: Mapping[uuid.UUID, StorageConnection]
) -> ProjectOut:
    internal = role in INTERNAL_ROLES
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        client_name=project.client_name,
        created_at=project.created_at,
        my_role=role,
        settings=ProjectSettings(**project.settings) if internal else None,
        storage=storage_out(project, connections) if internal else None,
        llm_consent=_consent_out(project),
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DbSession) -> list[ProjectOut]:
    connections = await connections_service.connections_by_id(db)
    return [
        _out(p, role, connections) for p, role in await projects_service.list_projects_for(db, user)
    ]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    taxonomy: TaxonomyDep,
) -> ProjectOut:
    if user.account_type != "internal":
        raise HTTPException(status_code=403, detail="Only internal users can create projects.")
    try:
        project = await projects_service.create_project(
            db,
            name=body.name,
            client_name=body.client_name,
            creator=user,
            settings=settings,
            taxonomy=taxonomy,
        )
    except projects_service.ProjectValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail="Storage is unavailable; the project was not created."
        ) from exc
    await db.refresh(project)
    return _out(project, "owner", await connections_service.connections_by_id(db))


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(ctx: AnyMember, db: DbSession) -> ProjectOut:
    return _out(ctx.project, ctx.role, await connections_service.connections_by_id(db))


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(body: ProjectUpdate, ctx: ProjectOwner, db: DbSession) -> ProjectOut:
    project = ctx.project
    if body.name is not None:
        project.name = body.name
    if "client_name" in body.model_fields_set:
        project.client_name = body.client_name
    if body.settings is not None:
        merged = {**project.settings, **body.settings.model_dump(exclude_none=True)}
        project.settings = ProjectSettings(**merged).model_dump()
    await audit.record(
        db,
        "project.update",
        user_id=ctx.user.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"fields": sorted(body.model_fields_set)},
    )
    await db.commit()
    return _out(project, ctx.role, await connections_service.connections_by_id(db))


@router.delete("/{project_id}", status_code=204)
async def archive_project(ctx: ProjectOwner, db: DbSession) -> None:
    ctx.project.archived_at = datetime.now(UTC)
    await audit.record(
        db,
        "project.archive",
        user_id=ctx.user.id,
        project_id=ctx.project.id,
        target_type="project",
        target_id=str(ctx.project.id),
    )
    await db.commit()


@router.get("/{project_id}/members", response_model=list[MemberOut])
async def get_members(ctx: InternalMember, db: DbSession) -> list[MemberOut]:
    return await projects_service.list_members(db, ctx.project.id)


@router.put("/{project_id}/members", response_model=list[MemberOut])
async def put_members(members: list[MemberIn], ctx: ProjectOwner, db: DbSession) -> list[MemberOut]:
    try:
        await projects_service.replace_members(db, ctx.project, members, actor_id=ctx.user.id)
    except projects_service.MemberValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return await projects_service.list_members(db, ctx.project.id)


@router.post("/{project_id}/llm-consent", response_model=LlmConsentOut, status_code=201)
async def record_llm_consent(
    body: LlmConsentRequest, ctx: ProjectOwner, db: DbSession
) -> LlmConsentOut:
    try:
        await consent_service.record_consent(
            db, ctx.project, actor=ctx.user, confirmed_by_name=body.confirmed_by_name
        )
    except consent_service.ConsentError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    consent = _consent_out(ctx.project)
    assert consent is not None  # noqa: S101 - just recorded
    return consent
