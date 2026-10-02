import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import (
    AnyMember,
    AppSettings,
    DbSession,
    DocumentAccess,
    InternalMember,
    TaxonomyDep,
    Uploader,
)
from app.db.models import Document
from app.ingestion.gaps import build_gap_report
from app.ingestion.intake import content_type_for
from app.schemas.documents import (
    DocumentContentOut,
    DocumentOut,
    DocumentUpdate,
    DocumentVersionOut,
    GapReportOut,
    VersionSuggestionOut,
)
from app.services import documents as documents_service
from app.services.workspace import document_facts
from app.storage.base import StorageError, StorageNotFound
from app.storage.select import project_backend

router = APIRouter(tags=["documents"])


def _attachment(filename: str) -> dict[str, str]:
    fallback = filename.encode("ascii", "replace").decode().replace('"', "")
    encoded = quote(filename)
    return {
        "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}",
        "X-Content-Type-Options": "nosniff",
    }


def _document_out(
    document: Document, meta: Mapping[uuid.UUID, documents_service.VersionMeta]
) -> DocumentOut:
    current = meta.get(document.id)
    return DocumentOut.model_validate(document).model_copy(
        update={
            "uploaded_by_name": current.uploaded_by_name if current else None,
            "version_created_at": current.created_at if current else None,
        }
    )


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    ctx: AnyMember,
    db: DbSession,
    taxonomy: TaxonomyDep,
    folder: str | None = Query(default=None, max_length=40),
    doc_type: str | None = Query(default=None, max_length=80),
    visibility: str | None = Query(default=None, pattern="^(internal|shared)$"),
    q: str | None = Query(default=None, max_length=200),
) -> list[DocumentOut]:
    documents = await documents_service.list_documents(
        db,
        ctx.project.id,
        ctx.role,
        taxonomy,
        folder=folder,
        doc_type=doc_type,
        visibility=visibility,
        q=q,
    )
    meta = await documents_service.current_version_meta(db, (d.id for d in documents))
    return [_document_out(d, meta) for d in documents]


@router.get("/projects/{project_id}/gap-report", response_model=GapReportOut)
async def gap_report(ctx: InternalMember, db: DbSession, taxonomy: TaxonomyDep) -> GapReportOut:
    report = build_gap_report(
        taxonomy,
        await document_facts(db, ctx.project.id),
        project_slug=ctx.project.slug,
        project_name=ctx.project.name,
        generated_at=datetime.now(UTC),
    )
    return GapReportOut.model_validate(report.to_dict())


@router.get("/projects/{project_id}/version-suggestions", response_model=list[VersionSuggestionOut])
async def version_suggestions(
    ctx: Uploader,
    db: DbSession,
    doc_type: str = Query(max_length=80),
    title: str = Query(min_length=1, max_length=200),
) -> list[VersionSuggestionOut]:
    suggestions = await documents_service.version_suggestions(
        db, ctx.project.id, ctx.role, doc_type=doc_type, title=title
    )
    return [
        VersionSuggestionOut(
            document_id=s.document_id,
            title=s.title,
            current_version=s.current_version,
            similarity=s.similarity,
        )
        for s in suggestions
    ]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(ctx: DocumentAccess, db: DbSession) -> DocumentOut:
    meta = await documents_service.current_version_meta(db, [ctx.document.id])
    return _document_out(ctx.document, meta)


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_versions(ctx: DocumentAccess, db: DbSession) -> list[DocumentVersionOut]:
    return [
        DocumentVersionOut(
            version=v.version,
            sha256=v.sha256,
            original_path=v.original_path,
            markdown_path=v.markdown_path,
            uploaded_by=name,
            upload_item_id=v.upload_item_id,
            created_at=v.created_at,
        )
        for v, name in await documents_service.list_versions(db, ctx.document.id)
    ]


@router.get("/documents/{document_id}/versions/{version}/original")
async def download_original(
    version: int, ctx: DocumentAccess, db: DbSession, settings: AppSettings
) -> Response:
    row = await documents_service.get_version(db, ctx.document.id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    if row.original_path is None or row.original_storage_version is None:
        raise HTTPException(status_code=404, detail="Stub documents have no original file.")
    try:
        backend = await project_backend(db, ctx.project, settings)
        data = await backend.get_version(row.original_path, row.original_storage_version)
    except StorageNotFound as exc:
        raise HTTPException(status_code=404, detail="File is not available in storage.") from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Storage is unavailable.") from exc
    filename = PurePosixPath(row.original_path).name
    ext = filename.rsplit(".", 1)[-1].lower()
    return Response(content=data, media_type=content_type_for(ext), headers=_attachment(filename))


@router.get("/documents/{document_id}/versions/{version}/markdown")
async def download_markdown(version: int, ctx: DocumentAccess, db: DbSession) -> Response:
    row = await documents_service.get_version(db, ctx.document.id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    filename = PurePosixPath(row.markdown_path).name
    return Response(
        content=row.markdown_text,
        media_type="text/markdown; charset=utf-8",
        headers=_attachment(filename),
    )


@router.get(
    "/documents/{document_id}/versions/{version}/content", response_model=DocumentContentOut
)
async def version_content(version: int, ctx: DocumentAccess, db: DbSession) -> DocumentContentOut:
    row = await documents_service.get_version(db, ctx.document.id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    frontmatter, body = documents_service.split_content(row.markdown_text)
    return DocumentContentOut(
        version=row.version,
        frontmatter=frontmatter,
        body=body,
        markdown_name=PurePosixPath(row.markdown_path).name,
        original_name=PurePosixPath(row.original_path).name if row.original_path else None,
    )


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(body: DocumentUpdate, ctx: DocumentAccess, db: DbSession) -> DocumentOut:
    try:
        await documents_service.update_document(
            db,
            ctx.document,
            actor=ctx.user,
            role=ctx.role,
            title=body.title,
            visibility=body.visibility,
        )
    except documents_service.DocumentPermissionError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    meta = await documents_service.current_version_meta(db, [ctx.document.id])
    return _document_out(ctx.document, meta)
