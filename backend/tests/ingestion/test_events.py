"""Every upload-item transition writes one ``item.status`` event row in the same transaction
as the change, so a replay can never disagree with the item."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import DocumentVersion, UploadEvent, UploadItem, User
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services import events
from app.services.pipeline import publish_confirmed_item, requeue_stale_items, run_upload
from app.services.uploads import confirm_type, retry_item
from tests.factories import make_project, make_user
from tests.helpers.files import docx_bytes
from tests.helpers.ingest import ingest, pipeline_context

PLAN = docx_bytes(
    ["Scope of testing: login, upload and publish flows. Entry criteria: build green."]
)
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
ALLOWED_KEYS = {"item_id", "status", *events.PAYLOAD_FIELDS}


async def _rows(db: AsyncSession, upload_id: uuid.UUID) -> list[UploadEvent]:
    db.expire_all()
    return list(
        (
            await db.scalars(
                select(UploadEvent)
                .where(UploadEvent.upload_id == upload_id)
                .order_by(UploadEvent.id)
            )
        ).all()
    )


def _statuses(rows: list[UploadEvent], item_id: uuid.UUID) -> list[str]:
    return [r.payload["status"] for r in rows if r.item_id == item_id]


async def test_every_transition_writes_one_event_in_order(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    fake = FakeAnalyzer(
        {"plan.docx": ScriptedVerdict("mismatch", "Reads like a plan.", "test-plan")}
    )
    upload, items, _ = await ingest(
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
    # Plain ids: _rows() below expires every previously loaded object in the session (needed so
    # it sees item/upload rows that other sessions committed), so touching an ORM attribute of
    # ``items``/``upload`` afterwards would try to lazy-load outside an await (MissingGreenlet).
    upload_id, srs_id, plan_id = upload.id, by_name["srs.docx"].id, by_name["plan.docx"].id
    rows = await _rows(db, upload_id)
    assert all(r.type == "item.status" for r in rows)
    assert [r.id for r in rows] == sorted(r.id for r in rows)
    assert _statuses(rows, srs_id) == [
        "converting",
        "checking",
        "publishing",
        "published",
    ]
    assert _statuses(rows, plan_id) == [
        "converting",
        "checking",
        "needs_confirmation",
    ]
    published = [r for r in rows if r.payload["status"] == "published"][0]
    version = await db.scalar(
        select(DocumentVersion).where(DocumentVersion.upload_item_id == srs_id)
    )
    assert version is not None
    assert published.payload["document_id"] == str(version.document_id)
    assert published.payload["version"] == 1
    publishing = [r for r in rows if r.item_id == srs_id and r.payload["status"] == "publishing"][0]
    assert publishing.payload["type_check"] == "match"  # the verdict travels with that transition
    waiting = [r for r in rows if r.payload["status"] == "needs_confirmation"][0]
    assert waiting.payload["suggested_doc_type"] == "test-plan"
    assert waiting.payload["check_explanation"] == "Reads like a plan."
    for row in rows:
        assert set(row.payload) <= ALLOWED_KEYS, row.payload  # never content or metadata
        assert row.payload["item_id"] == str(row.item_id)


async def test_confirm_publish_and_retry_record_events(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Looks wrong.", "test-plan")})
    upload, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("plan.docx", PLAN), ("broken.docx", b"not a docx")],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="srs")],
        analyzer=fake,
    )
    by_name = {i.original_name: i for i in items}
    waiting, broken = by_name["plan.docx"], by_name["broken.docx"]
    # Plain ids: _rows() below expires every previously loaded object in the session, so touching
    # an ORM attribute of ``upload``/``project``/``owner`` afterwards would try to lazy-load
    # outside an await (MissingGreenlet); ``actor`` needs a live (non-expired) User, so it is
    # re-fetched with ``db.get_one`` right before its second use, same as ``broken`` below.
    upload_id, project_id, owner_id = upload.id, project.id, owner.id
    assert await events.is_settled(db, upload_id)  # waiting + failed: nothing in progress
    await confirm_type(
        db, waiting, doc_type_key="test-plan", taxonomy=taxonomy, actor=owner, project_id=project_id
    )
    assert not await events.is_settled(db, upload_id)
    waiting_id, broken_id = waiting.id, broken.id
    rows = await _rows(db, upload_id)
    confirmed = [r for r in rows if r.item_id == waiting_id][-1]
    assert confirmed.payload["status"] == "publishing"
    assert confirmed.payload["final_doc_type"] == "test-plan"
    assert confirmed.payload["type_check"] == "mismatch_changed"
    await publish_confirmed_item(pipeline_context(settings, taxonomy, fake), waiting_id)
    rows = await _rows(db, upload_id)
    assert _statuses(rows, waiting_id)[-2:] == ["publishing", "published"]
    assert await events.is_settled(db, upload_id)
    failed = [r for r in rows if r.item_id == broken_id][-1]
    assert failed.payload["status"] == "failed"
    assert failed.payload["error"] == "File content does not match its extension."
    broken = await db.get_one(UploadItem, broken_id)
    owner = await db.get_one(User, owner_id)
    await retry_item(db, broken, actor=owner, project_id=project_id)
    rows = await _rows(db, upload_id)
    retried = [r for r in rows if r.item_id == broken_id][-1]
    assert retried.payload == {"item_id": str(broken_id), "status": "uploaded", "error": None}


async def test_events_after_returns_only_later_rows(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
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
    )
    upload_id = upload.id  # plain id: _rows() below expires it
    rows = await _rows(db, upload_id)
    assert len(rows) == 4
    later = await events.events_after(db, upload_id, rows[1].id)
    assert [r.id for r in later] == [rows[2].id, rows[3].id]
    assert await events.events_after(db, upload_id, rows[-1].id) == []
    assert [r.id for r in await events.events_after(db, upload_id, 0, limit=2)] == [
        rows[0].id,
        rows[1].id,
    ]


async def test_failed_conversion_records_failed_in_the_same_commit(
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
        files=[("srs.docx", SRS)],
        specs=[UploadItemSpec(doc_type="srs")],
        run=False,
    )
    item_id = items[0].id  # plain id: _rows() below expires it
    staged = staging_root / items[0].staging_path
    staged.unlink()  # the staged file disappears before conversion
    await run_upload(pipeline_context(settings, taxonomy), upload.id)
    rows = await _rows(db, upload.id)
    assert _statuses(rows, item_id) == ["converting", "failed"]
    assert rows[-1].payload["error"].startswith("Staged file is no longer available")
    item = await db.get_one(UploadItem, item_id)
    assert item.status == "failed"  # the row and the status were committed together


async def test_requeue_records_the_restart(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, taxonomy: Taxonomy
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
        items[0].status = "converting"  # as if the process died mid-conversion
        await db.commit()
        item_id, upload_id = items[0].id, upload.id
    assert await requeue_stale_items(pipeline_context(settings, taxonomy)) == 1
    for _ in range(100):
        async with db_sessionmaker() as db:
            item = await db.get_one(UploadItem, item_id)
            if item.status in ("published", "failed"):
                break
        await asyncio.sleep(0.05)
    async with db_sessionmaker() as db:
        rows = await _rows(db, upload_id)
    statuses: list[Any] = _statuses(rows, item_id)
    assert statuses[0] == "uploaded"  # the restart itself is an event
    assert statuses[-1] == "published"
