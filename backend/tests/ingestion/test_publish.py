"""Publish rules at the service level: naming, frontmatter, versions, no-change, stub removal,
reports, idempotency. Files go through the real intake and pipeline with the SkipAnalyzer."""

import asyncio
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, Document, DocumentVersion, Project, UploadItem, User
from app.db.session import get_sessionmaker
from app.ingestion.naming import split_frontmatter
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services import publish as publish_module
from app.services.pipeline import (
    NO_CHANGE_ERROR,
    check_items,
    convert_item,
    publish_item_by_id,
    run_upload,
)
from app.services.uploads import list_items
from app.storage.base import StorageError
from app.storage.localfs import LocalFsBackend
from tests.factories import make_project, make_user
from tests.helpers.files import docx_bytes
from tests.helpers.ingest import ingest, pipeline_context

SRS_V1 = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
SRS_V2 = docx_bytes(
    ["The system shall allow users to log in with a password, a one-time code and MFA."]
)


async def _setup(db: AsyncSession, settings: Settings, taxonomy: Taxonomy) -> tuple[User, Project]:
    owner = await make_user(db, settings, display_name="Nguyen Van A")
    return owner, await make_project(db, settings, taxonomy, owner=owner, name="Demo")


async def test_new_document_is_published_with_naming_and_frontmatter(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, rejected = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("Customer Portal SRS.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    assert rejected == [] and [i.status for i in items] == ["published"]
    assert items[0].type_check == "skipped" and items[0].title == "Customer Portal SRS"
    document = (
        await db.scalars(
            select(Document).where(Document.doc_type == "srs", Document.is_stub.is_(False))
        )
    ).one()
    assert document.slug == "customer-portal-srs" and document.current_version == 1
    version = (
        await db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id))
    ).one()
    assert version.original_path == "02-requirements/srs--customer-portal-srs.docx"
    assert version.markdown_path == "02-requirements/srs--customer-portal-srs.md"
    assert version.sha256 == hashlib.sha256(SRS_V1).hexdigest()
    assert version.upload_item_id == items[0].id
    root = storage_root / "demo"
    assert (root / version.original_path).read_bytes() == SRS_V1
    markdown = (root / version.markdown_path).read_text()
    frontmatter, body = split_frontmatter(markdown)
    assert frontmatter["qc_agent"] == 2 and frontmatter["document_id"] == str(document.id)
    assert frontmatter["doc_type"] == "srs" and frontmatter["folder"] == "02-requirements"
    assert frontmatter["uploaded_by"] == "Nguyen Van A" and frontmatter["type_check"] == "skipped"
    assert frontmatter["source_sha256"] == version.sha256 and frontmatter["language"] == "en"
    assert "one-time code" in body and version.markdown_text == markdown
    # the SRS stub is gone, the gap report says present
    assert not (root / "02-requirements/srs.md").exists()
    assert (root / ".trash/02-requirements/srs.md").exists()
    stubs = (await db.scalars(select(Document).where(Document.is_stub.is_(True)))).all()
    assert len(stubs) == 9
    report = json.loads((root / "_reports/gap-report.json").read_text())
    assert report["required_present"] == 1
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "upload.created" in actions and "upload_item.published" in actions


async def test_new_version_overwrites_paths_and_identical_file_is_no_change(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs", title="Portal SRS")],
    )
    document = (await db.scalars(select(Document).where(Document.slug == "portal-srs"))).one()
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs-v2.docx", SRS_V2)],
        specs=[UploadItemSpec(doc_type="srs", intent="version", target_document_id=document.id)],
    )
    assert items[0].status == "published"
    await db.refresh(document)
    assert document.current_version == 2
    versions = (
        await db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version)
        )
    ).all()
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].original_path == versions[1].original_path
    assert versions[0].original_storage_version != versions[1].original_storage_version
    root = storage_root / "demo"
    assert (root / versions[1].original_path).read_bytes() == SRS_V2
    assert (
        root / ".versions" / versions[0].original_path / versions[0].original_storage_version
    ).read_bytes() == SRS_V1
    # identical bytes again: rejected early at intake
    _, items, rejected = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("same.docx", SRS_V2), ("notes.md", b"# Notes\n")],
        specs=[
            UploadItemSpec(doc_type="srs", intent="version", target_document_id=document.id),
            UploadItemSpec(doc_type="overview/other"),
        ],
    )
    assert [r.reason for r in rejected] == [
        "No change: this file is identical to the current version."
    ]
    assert [i.original_name for i in items] == ["notes.md"]
    await db.refresh(document)
    assert document.current_version == 2


async def test_slug_collision_other_type_and_multi_subdir(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("a.md", b"# ADR 1\n"), ("b.md", b"# ADR 1 again\n"), ("notes.txt", b"free text\n")],
        specs=[
            UploadItemSpec(doc_type="adr", title="Use PostgreSQL"),
            UploadItemSpec(doc_type="adr", title="Use PostgreSQL"),
            UploadItemSpec(doc_type="design/other", title="Whiteboard notes"),
        ],
    )
    assert [i.status for i in items] == ["published"] * 3
    paths = sorted(
        str(p.relative_to(storage_root / "demo"))
        for p in (storage_root / "demo").rglob("*--*")
        if p.is_file()
    )
    assert paths == [
        "03-design/other--whiteboard-notes.md",
        "03-design/other--whiteboard-notes.txt",
        "04-source/adr/adr--use-postgresql-2.md",
        "04-source/adr/adr--use-postgresql.md",
    ]


async def test_edited_stub_is_kept(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    stub = storage_root / "demo/06-deployment/runbook.md"
    stub.write_text(stub.read_text() + "\nSomeone started writing here.\n")
    await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("runbook.md", b"# Runbook\n\nRestart the service.\n")],
        specs=[UploadItemSpec(doc_type="runbook")],
    )
    assert stub.exists() and "Someone started writing here." in stub.read_text()
    runbooks = (await db.scalars(select(Document).where(Document.doc_type == "runbook"))).all()
    assert {d.is_stub for d in runbooks} == {True, False}


async def test_publish_is_idempotent_on_retry(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    item = items[0]
    item_id = item.id  # plain id: the item is expired below
    item.status = "publishing"  # as if the process died after committing the version row
    await db.commit()
    await publish_item_by_id(pipeline_context(settings, taxonomy), get_sessionmaker(), item_id)
    db.expire_all()
    refreshed = await db.get_one(UploadItem, item_id)
    assert refreshed.status == "published"
    versions = (
        await db.scalars(select(DocumentVersion).where(DocumentVersion.upload_item_id == item_id))
    ).all()
    assert len(versions) == 1


async def test_title_equal_to_type_name_does_not_collide_with_stub(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("Readme.md", b"# Project\n\nWhat it does.\n")],
        specs=[UploadItemSpec(doc_type="readme")],
    )
    assert items[0].status == "published" and items[0].title == "Readme"
    document = (
        await db.scalars(select(Document).where(Document.doc_type == "readme"))
    ).one()  # the stub row is gone, only the real document remains
    assert document.slug == "readme" and document.is_stub is False
    assert (storage_root / "demo/01-overview/readme--readme.md").exists()
    assert not (storage_root / "demo/01-overview/readme.md").exists()


async def test_concurrent_publishes_in_one_project_get_distinct_slugs(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    ctx = pipeline_context(settings, taxonomy)
    upload_ids = []  # plain ids: each ingest expires the previously returned upload
    for data in (SRS_V1, SRS_V2):
        upload, _, _ = await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=owner,
            role="owner",
            files=[("srs.docx", data)],
            specs=[UploadItemSpec(doc_type="srs", title="Portal SRS")],
            run=False,
        )
        upload_ids.append(upload.id)
    await asyncio.gather(*(run_upload(ctx, upload_id) for upload_id in upload_ids))
    db.expire_all()
    documents = (
        await db.scalars(
            select(Document).where(Document.doc_type == "srs", Document.is_stub.is_(False))
        )
    ).all()
    assert sorted(d.slug for d in documents) == ["portal-srs", "portal-srs-2"]
    statuses = [i.status for upload_id in upload_ids for i in await list_items(db, upload_id)]
    assert statuses == ["published", "published"]


async def _to_publishing(settings: Settings, taxonomy: Taxonomy, upload_id: uuid.UUID) -> None:
    """Convert and check (SkipAnalyzer) the items of an upload, leaving them in ``publishing``."""
    ctx = pipeline_context(settings, taxonomy)
    maker = get_sessionmaker()
    async with maker() as session:
        ids = [i.id for i in await list_items(session, upload_id)]
    converted = [i for i in ids if await convert_item(ctx, maker, i)]
    assert await check_items(ctx, maker, upload_id, converted) == converted


async def _boom(*args: object, **kwargs: object) -> None:
    raise RuntimeError("simulated failure after the storage writes")


async def test_failed_new_document_publish_leaves_no_files(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    monkeypatch.setattr(publish_module, "refresh_reports", _boom)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs", title="Portal SRS")],
    )
    assert items[0].status == "failed"
    assert items[0].error == "Publishing failed unexpectedly."
    root = storage_root / "demo"
    assert not (root / "02-requirements/srs--portal-srs.docx").exists()
    assert not (root / "02-requirements/srs--portal-srs.md").exists()
    # the trashed stub is put back, matching the stub row that the rollback restored
    assert (root / "02-requirements/srs.md").exists()
    assert (await db.scalars(select(Document).where(Document.is_stub.is_(False)))).all() == []


async def test_failed_version_publish_restores_previous_files(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs", title="Portal SRS")],
    )
    document = (await db.scalars(select(Document).where(Document.slug == "portal-srs"))).one()
    root = storage_root / "demo"
    markdown_before = (root / "02-requirements/srs--portal-srs.md").read_bytes()
    monkeypatch.setattr(publish_module, "refresh_reports", _boom)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs-v2.docx", SRS_V2)],
        specs=[UploadItemSpec(doc_type="srs", intent="version", target_document_id=document.id)],
    )
    assert items[0].status == "failed"
    await db.refresh(document)
    assert document.current_version == 1
    assert (root / "02-requirements/srs--portal-srs.docx").read_bytes() == SRS_V1
    assert (root / "02-requirements/srs--portal-srs.md").read_bytes() == markdown_before


async def test_concurrent_publish_of_one_item_publishes_once(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs")],
        run=False,
    )
    await _to_publishing(settings, taxonomy, upload.id)
    item_id = (await list_items(db, upload.id))[0].id
    ctx = pipeline_context(settings, taxonomy)
    await asyncio.gather(
        publish_item_by_id(ctx, get_sessionmaker(), item_id),
        publish_item_by_id(ctx, get_sessionmaker(), item_id),
    )
    db.expire_all()
    assert (await db.get_one(UploadItem, item_id)).status == "published"
    versions = await db.scalar(
        select(func.count())
        .select_from(DocumentVersion)
        .where(DocumentVersion.upload_item_id == item_id)
    )
    published = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "upload_item.published")
    )
    failed = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "upload_item.failed")
    )
    assert versions == 1 and published == 1 and failed == 0


async def test_no_change_detected_under_the_lock_fails_the_item(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs", title="Portal SRS")],
    )
    document = (await db.scalars(select(Document).where(Document.slug == "portal-srs"))).one()
    document_id = document.id  # plain id: each ingest expires the document
    upload_ids = []  # both pass intake: neither equals the current version (v1) yet
    for _ in range(2):
        upload, _, _ = await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=owner,
            role="owner",
            files=[("srs-v2.docx", SRS_V2)],
            specs=[
                UploadItemSpec(doc_type="srs", intent="version", target_document_id=document_id)
            ],
            run=False,
        )
        upload_ids.append(upload.id)
    ctx = pipeline_context(settings, taxonomy)
    for upload_id in upload_ids:
        await run_upload(ctx, upload_id)
    db.expire_all()
    first, second = [(await list_items(db, upload_id))[0] for upload_id in upload_ids]
    assert first.status == "published"
    assert second.status == "failed" and second.error == NO_CHANGE_ERROR
    await db.refresh(document)
    assert document.current_version == 2


async def test_storage_error_during_publish_fails_the_item(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, project = await _setup(db, settings, taxonomy)

    async def unavailable(*args: object, **kwargs: object) -> None:
        raise StorageError("Storage is unavailable.")

    monkeypatch.setattr(LocalFsBackend, "put_file", unavailable)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    assert items[0].status == "failed" and items[0].error == "Storage is unavailable."
    assert (await db.scalars(select(Document).where(Document.is_stub.is_(False)))).all() == []
    failed = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "upload_item.failed"))
    ).all()
    assert len(failed) == 1
