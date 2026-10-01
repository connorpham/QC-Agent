"""The per-item state machine with a scripted analyzer."""

import asyncio
import logging
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import Document, UploadItem
from app.db.session import get_sessionmaker
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services import pipeline
from app.services.pipeline import (
    check_items,
    convert_item,
    publish_confirmed_item,
    requeue_stale_items,
)
from app.services.uploads import confirm_type, list_items
from tests.factories import make_project, make_user
from tests.helpers.files import docx_bytes, pdf_bytes
from tests.helpers.ingest import ingest, pipeline_context

PLAN = docx_bytes(
    ["Scope of testing: login, upload and publish flows. Entry criteria: build green."]
)
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])


async def test_match_publishes_and_mismatch_waits_for_confirmation(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    fake = FakeAnalyzer(
        {"plan.docx": ScriptedVerdict("mismatch", "This reads like a test plan.", "test-plan")}
    )
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS), ("plan.docx", PLAN)],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="srs", title="Plan")],
        analyzer=fake,
    )
    by_name = {i.original_name: i for i in items}
    assert by_name["srs.docx"].status == "published" and by_name["srs.docx"].type_check == "match"
    waiting = by_name["plan.docx"]
    assert waiting.status == "needs_confirmation"
    assert waiting.check_explanation == "This reads like a test plan."
    assert waiting.suggested_doc_type == "test-plan"
    assert len(fake.batches) == 1 and len(fake.batches[0].items) == 2
    previews = {i.file_name: i.preview for i in fake.batches[0].items}
    assert previews["srs.docx"].startswith("The system shall")
    # the uploader changes the type; the item publishes into 05-testing
    await confirm_type(
        db, waiting, doc_type_key="test-plan", taxonomy=taxonomy, actor=owner, project_id=project.id
    )
    waiting_id = waiting.id  # plain id: the item is expired below
    await publish_confirmed_item(pipeline_context(settings, taxonomy, fake), waiting_id)
    db.expire_all()
    done = await db.get_one(UploadItem, waiting_id)
    assert done.status == "published" and done.type_check == "mismatch_changed"
    assert done.final_doc_type == "test-plan"
    assert (storage_root / "demo/05-testing/test-plan--plan.docx").exists()
    frontmatter = (storage_root / "demo/05-testing/test-plan--plan.md").read_text()
    assert (
        "type_selected_by_user: srs" in frontmatter
        and "type_check: mismatch_changed" in frontmatter
    )


async def test_keeping_the_type_records_mismatch_kept(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Looks wrong.", "test-plan")})
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("plan.docx", PLAN)],
        specs=[UploadItemSpec(doc_type="srs")],
        analyzer=fake,
    )
    await confirm_type(
        db, items[0], doc_type_key="srs", taxonomy=taxonomy, actor=owner, project_id=project.id
    )
    item_id = items[0].id  # plain id: the item is expired below
    await publish_confirmed_item(pipeline_context(settings, taxonomy, fake), item_id)
    db.expire_all()
    done = await db.get_one(UploadItem, item_id)
    assert done.status == "published" and done.type_check == "mismatch_kept"


async def test_analyzer_failure_and_low_text_skip_the_check(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS), ("scan.pdf", pdf_bytes(["", ""]))],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="deploy-guide")],
        analyzer=FakeAnalyzer(error=RuntimeError("agent down")),
    )
    by_name = {i.original_name: i for i in items}
    assert by_name["srs.docx"].status == "published" and by_name["srs.docx"].type_check == "skipped"
    assert (
        by_name["srs.docx"].check_explanation
        == "The type check could not run; the selected type was kept."
    )
    scan = by_name["scan.pdf"]
    assert scan.status == "published" and scan.type_check == "skipped"
    assert "low_text" in scan.conversion_meta["warnings"]


async def test_conversion_failure_marks_item_failed_with_reason(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("broken.docx", b"not really a docx")],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    assert items[0].status == "failed"
    assert items[0].error == "File content does not match its extension."
    assert (await db.scalars(select(Document).where(Document.is_stub.is_(False)))).all() == []


async def test_requeue_restarts_items_left_in_progress(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, taxonomy: Taxonomy
) -> None:
    import asyncio

    async with db_sessionmaker() as db:
        owner = await make_user(db, settings)
        project = await make_project(db, settings, taxonomy, owner=owner)
        _, items, _ = await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=owner,
            role="owner",
            files=[("srs.docx", SRS)],
            specs=[UploadItemSpec(doc_type="srs")],
            run=False,
        )
        items[0].status = "converting"  # as if the process died mid-conversion
        await db.commit()
        item_id = items[0].id
    count = await requeue_stale_items(pipeline_context(settings, taxonomy))
    assert count == 1
    await asyncio.sleep(0)
    for _ in range(100):
        async with db_sessionmaker() as db:
            item = await db.get_one(UploadItem, item_id)
            if item.status in ("published", "failed"):
                break
        await asyncio.sleep(0.05)
    assert item.status == "published"


async def _wait_for_terminal(
    maker: async_sessionmaker[AsyncSession], item_id: uuid.UUID
) -> UploadItem:
    for _ in range(100):
        async with maker() as db:
            item = await db.get_one(UploadItem, item_id)
            if item.status in ("published", "failed", "needs_confirmation"):
                return item
        await asyncio.sleep(0.05)
    return item


async def test_requeue_publishes_a_confirmed_item_without_rechecking(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, taxonomy: Taxonomy
) -> None:
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Looks wrong.", "test-plan")})
    async with db_sessionmaker() as db:
        owner = await make_user(db, settings)
        project = await make_project(db, settings, taxonomy, owner=owner)
        _, items, _ = await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=owner,
            role="owner",
            files=[("plan.docx", PLAN)],
            specs=[UploadItemSpec(doc_type="srs")],
            analyzer=fake,
        )
        item_id = items[0].id
        await confirm_type(
            db,
            items[0],
            doc_type_key="test-plan",
            taxonomy=taxonomy,
            actor=owner,
            project_id=project.id,
        )  # the process dies before publish_confirmed_item runs
    count = await requeue_stale_items(pipeline_context(settings, taxonomy, fake))
    assert count == 1
    item = await _wait_for_terminal(db_sessionmaker, item_id)
    assert item.status == "published" and item.type_check == "mismatch_changed"
    assert item.final_doc_type == "test-plan"
    assert len(fake.batches) == 1  # not checked again


async def test_missing_converted_text_at_check_fails_only_that_item(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, staging_root: Path
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    upload, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS), ("plan.docx", PLAN)],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="test-plan")],
        run=False,
    )
    ctx = pipeline_context(settings, taxonomy)
    maker = get_sessionmaker()
    by_name = {i.original_name: i.id for i in items}
    for item in items:
        assert await convert_item(ctx, maker, item.id)
    lost = next(i for i in items if i.original_name == "srs.docx")
    staged = staging_root / lost.staging_path
    staged.with_name(staged.name + ".md").unlink()
    ready = await check_items(ctx, maker, upload.id, [i.id for i in items])
    assert ready == [by_name["plan.docx"]]
    upload_id = upload.id  # plain id: the upload is expired below
    db.expire_all()
    failed = await db.get_one(UploadItem, by_name["srs.docx"])
    assert failed.status == "failed"
    assert failed.error == "Staged file is no longer available; upload the file again."
    statuses = {i.original_name: i.status for i in await list_items(db, upload_id)}
    assert statuses == {"srs.docx": "failed", "plan.docx": "publishing"}


async def test_requeued_task_crash_is_logged_with_ids_only(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with db_sessionmaker() as db:
        owner = await make_user(db, settings)
        project = await make_project(db, settings, taxonomy, owner=owner)
        upload, items, _ = await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=owner,
            role="owner",
            files=[("srs.docx", SRS)],
            specs=[UploadItemSpec(doc_type="srs")],
            run=False,
        )
        items[0].status = "checking"
        await db.commit()
        upload_id = upload.id

    async def crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret document text")

    monkeypatch.setattr(pipeline, "run_upload", crash)
    with caplog.at_level(logging.ERROR, logger="app.services.pipeline"):
        assert await requeue_stale_items(pipeline_context(settings, taxonomy)) == 1
        for _ in range(50):
            if caplog.records:
                break
            await asyncio.sleep(0.02)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert str(upload_id) in record.getMessage()
    assert "secret document text" not in record.getMessage()
    assert record.exc_info is None  # the exception class is named; its message is not logged
    assert "RuntimeError" in record.getMessage()


async def test_crash_logs_name_the_error_class_without_message_or_traceback(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)

    def leaky(*args: object, **kwargs: object) -> None:
        raise RuntimeError("SECRET-CONTENT")

    async def leaky_async(*args: object, **kwargs: object) -> None:
        leaky()

    scenarios = [
        # conversion crash
        ({"convert": leaky}, None, ("a.docx", SRS)),
        # analyzer crash (the type check is skipped, the item still publishes)
        ({}, FakeAnalyzer(error=RuntimeError("SECRET-CONTENT")), ("b.docx", PLAN)),
        # publish crash
        ({"publish": leaky_async}, None, ("c.md", b"# C\n\nSome text for the check.\n")),
    ]
    for patches, analyzer, file in scenarios:
        with monkeypatch.context() as patch:
            if "convert" in patches:
                patch.setattr(pipeline, "convert_file", patches["convert"])
            if "publish" in patches:
                patch.setattr(pipeline, "_publish_item", patches["publish"])
            caplog.clear()
            with caplog.at_level(logging.DEBUG, logger="app.services.pipeline"):
                await ingest(
                    db,
                    settings,
                    taxonomy,
                    project=project,
                    uploader=owner,
                    role="owner",
                    files=[file],
                    specs=[UploadItemSpec(doc_type="srs")],
                    analyzer=analyzer,
                )
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1, file[0]
        assert "RuntimeError" in errors[0].getMessage()
        assert all("SECRET-CONTENT" not in r.getMessage() for r in caplog.records)
        assert all(r.exc_info is None for r in caplog.records)


async def test_convert_item_reports_a_lost_second_transition(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS)],
        specs=[UploadItemSpec(doc_type="srs")],
        run=False,
    )
    item_id = (await list_items(db, upload.id))[0].id
    real_transition = pipeline.transition

    async def lost_race(
        session: AsyncSession,
        target: uuid.UUID,
        from_statuses: object,
        to_status: str,
        **kw: object,
    ) -> bool:
        if to_status == "checking":
            return False  # someone else moved the item meanwhile
        return await real_transition(session, target, from_statuses, to_status, **kw)

    monkeypatch.setattr(pipeline, "transition", lost_race)
    ctx = pipeline_context(settings, taxonomy)
    assert await convert_item(ctx, get_sessionmaker(), item_id) is False


async def test_cancel_background_stops_pending_tasks() -> None:
    started = asyncio.Event()

    async def forever() -> None:
        started.set()
        await asyncio.sleep(3600)

    pipeline._spawn(forever(), "upload", uuid.uuid4())
    await started.wait()
    tasks = set(pipeline._background)
    assert tasks
    await pipeline.cancel_background()
    assert pipeline._background == set()
    assert all(task.cancelled() for task in tasks)
