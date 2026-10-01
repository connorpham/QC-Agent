import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.slugs import slugify, unique_slug
from app.db.locks import acquire_xact_lock
from app.db.models import Project, ProjectMember, StorageConnection, User
from app.ingestion.taxonomy import Taxonomy
from app.schemas.projects import MemberIn, MemberOut, ProjectSettings
from app.services import audit
from app.services.storage_connections import default_connection, get_connection
from app.services.workspace import ensure_workspace
from app.storage.base import StorageError, StoragePathError, validate_root_segment
from app.storage.select import backend_for, storage_binding


class MemberValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProjectValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def resolve_connection(
    db: AsyncSession, connection_id: uuid.UUID | None
) -> StorageConnection:
    """The connection a new project binds to: the requested one (must exist and be active) or
    the default."""
    if connection_id is None:
        connection = await default_connection(db)
        if connection is None:
            raise StorageError("No default storage connection is configured.")
        return connection
    connection = await get_connection(db, connection_id)
    if connection is None:
        raise ProjectValidationError("Storage connection not found.")
    if not connection.is_active:
        raise ProjectValidationError("Storage connection is not active.")
    return connection


async def root_in_use(db: AsyncSession, connection_id: uuid.UUID, root: str) -> bool:
    """True when any project, archived ones included (their files still exist), uses ``root``
    on the connection."""
    found = await db.scalar(
        select(Project.id).where(
            Project.storage.op("->>")("connection_id") == str(connection_id),
            # Case-insensitive: macOS, Windows and the Plan 3b cloud backends treat "Acme" and
            # "acme" as the same folder.
            func.lower(Project.storage.op("->>")("root")) == root.lower(),
        )
    )
    return found is not None


async def create_project(
    db: AsyncSession,
    *,
    name: str,
    client_name: str | None,
    creator: User,
    settings: Settings,
    taxonomy: Taxonomy,
    connection_id: uuid.UUID | None = None,
    root: str | None = None,
) -> Project:
    """Create the project, bind it to a storage connection under ``root`` (default: the slug)
    and provision the workspace (folders, stubs, reports) before committing. A storage failure
    raises ``StorageError`` and nothing is committed; an unknown or inactive connection or a
    bad root raises ``ProjectValidationError``.

    Slug selection and provisioning run under a Postgres advisory transaction lock keyed by the
    base slug, so two concurrent creations of the same name are serialised instead of racing to
    provision the same storage root: the second call blocks until the first commits (or rolls
    back), then sees the first's slug as taken and gets ``<base>-2``. The lock is released
    automatically when the transaction ends.
    """
    connection = await resolve_connection(db, connection_id)
    base = slugify(name)
    await acquire_xact_lock(db, "project-slug", base)
    taken = set((await db.scalars(select(Project.slug).where(Project.slug.startswith(base)))).all())
    slug = unique_slug(base, taken)
    root_folder = root or slug
    try:
        validate_root_segment(root_folder)
    except StoragePathError as exc:
        raise ProjectValidationError(str(exc)) from exc
    # Serialise on (connection, root) too: two different names may ask for the same folder.
    await acquire_xact_lock(db, "project-root", f"{connection.id}:{root_folder.lower()}")
    if await root_in_use(db, connection.id, root_folder):
        raise ProjectValidationError(
            "This root folder is already used by another project on the selected connection."
        )
    project = Project(
        slug=slug,
        name=name,
        client_name=client_name,
        settings=ProjectSettings().model_dump(),
        storage=storage_binding(connection.id, root_folder),
        created_by=creator.id,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=creator.id, role="owner"))
    backend = backend_for(connection, root_folder, settings)
    await ensure_workspace(db, project=project, backend=backend, taxonomy=taxonomy, actor=creator)
    await audit.record(
        db,
        "project.create",
        user_id=creator.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"storage_connection_id": str(connection.id), "root": root_folder},
    )
    await db.commit()
    return project


async def list_projects_for(db: AsyncSession, user: User) -> list[tuple[Project, str]]:
    if user.is_admin:
        projects = (
            await db.scalars(
                select(Project).where(Project.archived_at.is_(None)).order_by(Project.name)
            )
        ).all()
        return [(p, "owner") for p in projects]
    rows = (
        await db.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, Project.archived_at.is_(None))
            .order_by(Project.name)
        )
    ).all()
    return [(project, role) for project, role in rows]


async def replace_members(
    db: AsyncSession, project: Project, members: list[MemberIn], *, actor_id: uuid.UUID
) -> None:
    ids = [m.user_id for m in members]
    if len(set(ids)) != len(ids):
        raise MemberValidationError("Each user may appear only once.")
    if not any(m.role == "owner" for m in members):
        raise MemberValidationError("A project needs at least one owner.")
    users = {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()}
    for member in members:
        user = users.get(member.user_id)
        if user is None or not user.is_active:
            raise MemberValidationError(f"User {member.user_id} does not exist or is inactive.")
        if user.account_type == "customer" and member.role != "client":
            raise MemberValidationError("Customer accounts can only have the client role.")
        if user.account_type == "internal" and member.role == "client":
            raise MemberValidationError("Internal accounts cannot have the client role.")
    await db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
    db.add_all(
        ProjectMember(project_id=project.id, user_id=m.user_id, role=m.role) for m in members
    )
    await audit.record(
        db,
        "project.members_replaced",
        user_id=actor_id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"members": [{"user_id": str(m.user_id), "role": m.role} for m in members]},
    )
    await db.commit()


async def list_members(db: AsyncSession, project_id: uuid.UUID) -> list[MemberOut]:
    rows = (
        await db.execute(
            select(User, ProjectMember.role)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.display_name)
        )
    ).all()
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            account_type=u.account_type,
            role=role,
        )
        for u, role in rows
    ]
