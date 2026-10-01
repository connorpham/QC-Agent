"""The per-item state machine with a scripted analyzer."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import Document, UploadItem
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services.pipeline import publish_confirmed_item, requeue_stale_items
from app.services.uploads import confirm_type
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
