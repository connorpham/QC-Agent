import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import AdminUser, AppSettings, Box, CurrentUser, DbSession
from app.db.models import StorageConnection
from app.schemas.storage import (
    StorageConnectionAvailable,
    StorageConnectionCreate,
    StorageConnectionOut,
    StorageConnectionUpdate,
    StorageTestResult,
)
from app.services import storage_connections as connections_service

router = APIRouter(prefix="/storage-connections", tags=["storage"])


def _out(connection: StorageConnection) -> StorageConnectionOut:
    return StorageConnectionOut(
        id=connection.id,
        type=connection.type,
        name=connection.name,
        config=connection.config,
        is_default=connection.is_default,
        is_active=connection.is_active,
        has_secret=connection.secret_enc is not None,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


async def _get(db: DbSession, connection_id: uuid.UUID) -> StorageConnection:
    connection = await connections_service.get_connection(db, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Storage connection not found.")
    return connection


@router.get("", response_model=list[StorageConnectionOut])
async def list_connections(_: AdminUser, db: DbSession) -> list[StorageConnectionOut]:
    return [_out(c) for c in await connections_service.list_connections(db)]


@router.get("/available", response_model=list[StorageConnectionAvailable])
async def available_connections(
    user: CurrentUser, db: DbSession
) -> list[StorageConnectionAvailable]:
    """Active connections an internal user may pick for a new project, default first."""
    if user.account_type != "internal":
        raise HTTPException(
            status_code=403, detail="Only internal users can list storage connections."
        )
    active = [c for c in await connections_service.list_connections(db) if c.is_active]
    active.sort(key=lambda c: (not c.is_default, c.name))
    return [
        StorageConnectionAvailable(id=c.id, name=c.name, type=c.type, is_default=c.is_default)
        for c in active
    ]


@router.post("", response_model=StorageConnectionOut, status_code=201)
async def create_connection(
    body: StorageConnectionCreate,
    admin: AdminUser,
    db: DbSession,
    box: Box,
    settings: AppSettings,
) -> StorageConnectionOut:
    try:
        connection = await connections_service.create_connection(
            db,
            type_=body.type,
            name=body.name,
            config=body.config,
            secret=body.secret,
            is_default=body.is_default,
            actor=admin,
            box=box,
            settings=settings,
        )
    except connections_service.StorageConnectionError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except connections_service.StorageConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return _out(connection)


@router.patch("/{connection_id}", response_model=StorageConnectionOut)
async def update_connection(
    connection_id: uuid.UUID,
    body: StorageConnectionUpdate,
    admin: AdminUser,
    db: DbSession,
    box: Box,
    settings: AppSettings,
) -> StorageConnectionOut:
    connection = await _get(db, connection_id)
    if body.is_default is False:
        raise HTTPException(
            status_code=422, detail="Set another connection as the default instead."
        )
    # One route, one commit: the default move and the field update share a transaction, so a
    # refusal from either part leaves the connection — and the default — exactly as it was.
    try:
        changed = False
        if body.is_default:
            await connections_service.set_default(db, connection, actor=admin, commit=False)
            changed = True
        if body.model_fields_set & {"name", "config", "secret", "is_active"}:
            await connections_service.update_connection(
                db,
                connection,
                actor=admin,
                box=box,
                settings=settings,
                name=body.name,
                config=body.config,
                secret=body.secret,
                is_active=body.is_active,
                commit=False,
            )
            changed = True
    except connections_service.StorageConnectionError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except connections_service.StorageConnectionConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.message) from exc
    if changed:
        await db.commit()
        await db.refresh(connection)
    return _out(connection)


@router.post("/{connection_id}/test", response_model=StorageTestResult)
async def test_connection(
    connection_id: uuid.UUID, admin: AdminUser, db: DbSession, settings: AppSettings
) -> StorageTestResult:
    connection = await _get(db, connection_id)
    status = await connections_service.test_connection(
        db, connection, actor=admin, settings=settings
    )
    return StorageTestResult(ok=status.ok, detail=status.detail, field=status.field)
