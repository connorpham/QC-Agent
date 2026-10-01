from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.api.deps import (
    INTERNAL_ROLES,
    AnyMember,
    CurrentUser,
    DbSession,
    InternalMember,
    ProjectOwner,
)
from app.db.models import Project
from app.schemas.projects import (
    MemberIn,
    MemberOut,
    ProjectCreate,
    ProjectOut,
    ProjectSettings,
    ProjectUpdate,
)
from app.services import audit
from app.services import projects as projects_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _out(project: Project, role: str) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        client_name=project.client_name,
        created_at=project.created_at,
        my_role=role,
        settings=ProjectSettings(**project.settings) if role in INTERNAL_ROLES else None,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DbSession) -> list[ProjectOut]:
    return [_out(p, role) for p, role in await projects_service.list_projects_for(db, user)]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, user: CurrentUser, db: DbSession) -> ProjectOut:
    if user.account_type != "internal":
        raise HTTPException(status_code=403, detail="Only internal users can create projects.")
    project = await projects_service.create_project(
        db, name=body.name, client_name=body.client_name, creator=user
    )
    await db.refresh(project)
    return _out(project, "owner")


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(ctx: AnyMember) -> ProjectOut:
    return _out(ctx.project, ctx.role)


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
    return _out(project, ctx.role)


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
