"""Server-Sent Events for one upload: the authoritative state snapshot on connect, replay
after Last-Event-ID, authorisation like GET /uploads/{id}, live delivery, heartbeat,
termination, and no session held between polls.

``httpx.ASGITransport`` returns the body only when the app finishes, so the HTTP tests use
uploads whose stream terminates (settled uploads replay and close at once); live delivery,
heartbeats, out-of-order commits and disconnects are tested on the generator itself with a
counting session maker."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType

from httpx import AsyncClient
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import ITEM_STATUS_EVENT, Project, UploadEvent, UploadItem, User
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services import events
from app.services.pipeline import run_upload
from tests.factories import add_member, make_project, make_session_token, make_user
from tests.helpers.files import docx_bytes
from tests.helpers.ingest import ingest, pipeline_context

MakeClient = Callable[..., Awaitable[AsyncClient]]
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
PLAN = docx_bytes(["Scope of testing: login, upload and publish flows. Entry criteria: build."])


def _frames(text: str) -> list[dict[str, str]]:
    """Parse an SSE body into frames of field -> value (comments kept under ``comment``)."""
    frames: list[dict[str, str]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        frame: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            else:
                field, _, value = line.partition(":")
                frame[field] = value.strip()
        frames.append(frame)
    return frames


def _rows(frames: list[dict[str, str]]) -> list[dict[str, str]]:
    """The replayed/live event frames: the ones carrying an ``id:`` line."""
    return [f for f in frames if "id" in f]


def _snapshot(frames: list[dict[str, str]]) -> list[dict[str, object]]:
    """The state frames sent on connect: ``item.status`` without an ``id:`` line."""
    return [
        json.loads(f["data"])
        for f in frames
        if f.get("event") == ITEM_STATUS_EVENT and "id" not in f
    ]


def _status(frame: dict[str, str]) -> str:
    return str(json.loads(frame["data"])["status"])


def _assert_snapshot_is_last_word(frames: list[dict[str, str]]) -> None:
    """The connect snapshot must come *after* every replayed row.

    The states are read after the rows, so a transition committing between the two statements
    is in the snapshot but not in the rows. Sent first, the snapshot would be overwritten by a
    replay ending on the older status and the client would show a stale value until the next
    poll; sent last, it is the correction it is meant to be.
    """
    positions = [i for i, f in enumerate(frames) if f.get("event") == ITEM_STATUS_EVENT]
    snapshot = [i for i in positions if "id" not in frames[i]]
    rows = [i for i in positions if "id" in frames[i]]
    assert snapshot, "the stream sent no state snapshot"
    assert min(snapshot) > max(rows, default=-1)
    assert snapshot == list(range(min(snapshot), min(snapshot) + len(snapshot)))  # contiguous


async def _next_frame(stream: AsyncIterator[str], limit: float = 5.0) -> dict[str, str]:
    """The next frame of a stream, failing the test rather than hanging if none arrives."""
    async with asyncio.timeout(limit):
        return _frames(await anext(stream))[0]


def _event(upload_id: uuid.UUID, item_id: uuid.UUID, status: str) -> UploadEvent:
    return UploadEvent(
        upload_id=upload_id,
        item_id=item_id,
        type=ITEM_STATUS_EVENT,
        payload=events.item_status_payload(item_id, status, {}),
    )


class CountingMaker:
    """Wraps a sessionmaker so a test can see how many sessions are open at any moment, and at
    what isolation level each one ran."""

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self.maker = maker
        self.opened = 0
        self.closed = 0
        self.max_open = 0
        self.isolation: list[str] = []

    @property
    def open(self) -> int:
        return self.opened - self.closed

    def __call__(self) -> "CountingMaker._Ctx":
        return CountingMaker._Ctx(self)

    class _Ctx:
        def __init__(self, counter: "CountingMaker") -> None:
            self.counter = counter
            self.session: AsyncSession | None = None

        async def __aenter__(self) -> AsyncSession:
            self.counter.opened += 1
            self.counter.max_open = max(self.counter.max_open, self.counter.open)
            self.session = self.counter.maker()
            return self.session

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            self.counter.closed += 1
            assert self.session is not None
            if exc_type is None:  # still inside the poll's transaction
                self.counter.isolation.append(
                    str(await self.session.scalar(text("SHOW transaction_isolation")))
                )
            await self.session.close()


async def _world(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> tuple[Project, dict[str, User]]:
    owner = await make_user(db, settings, email="owner@example.com", display_name="Owner")
    editor = await make_user(db, settings, email="editor@example.com", display_name="Editor")
    viewer = await make_user(db, settings, email="viewer@example.com", display_name="Viewer")
    client_a = await make_user(
        db, settings, email="a@client.com", display_name="Client A", account_type="customer"
    )
    client_b = await make_user(
        db, settings, email="b@client.com", display_name="Client B", account_type="customer"
    )
    outsider = await make_user(db, settings, email="out@example.com", display_name="Out")
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    for user, role in (
        (editor, "editor"),
        (viewer, "viewer"),
        (client_a, "client"),
        (client_b, "client"),
    ):
        await add_member(db, project, user, role)
    return project, {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "client_a": client_a,
        "client_b": client_b,
        "outsider": outsider,
    }


async def _client(
    make_client: MakeClient, db: AsyncSession, settings: Settings, user: User
) -> AsyncClient:
    return await make_client(await make_session_token(db, settings, user))


def test_parse_last_event_id() -> None:
    assert events.parse_last_event_id(None) == 0
    assert events.parse_last_event_id("") == 0
    assert events.parse_last_event_id("abc") == 0
    assert events.parse_last_event_id("-1") == 0
    assert events.parse_last_event_id("42") == 42


def test_sse_frame_format() -> None:
    assert (
        events.sse_frame("item.status", {"a": 1}, 7)
        == 'id: 7\nevent: item.status\ndata: {"a":1}\n\n'
    )
    assert (
        events.sse_frame("upload.settled", {"x": "y"})
        == 'event: upload.settled\ndata: {"x":"y"}\n\n'
    )


async def test_settled_upload_replays_everything_and_terminates(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _world(db, settings, taxonomy)
    upload, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=users["editor"],
        role="editor",
        files=[("srs.docx", SRS)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    editor = await _client(make_client, db, settings, users["editor"])
    response = await editor.get(f"/api/v1/uploads/{upload.id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    frames = _frames(response.text)
    assert frames[0] == {"retry": "2000"}
    # The fresh state snapshot is the last word before ``upload.settled`` (rulings P5-4a, P5-6).
    _assert_snapshot_is_last_word(frames)
    snapshot = _snapshot(frames)
    assert frames[-2]["event"] == ITEM_STATUS_EVENT and "id" not in frames[-2]
    assert [s["item_id"] for s in snapshot] == [str(items[0].id)]
    assert [s["status"] for s in snapshot] == ["published"]
    assert snapshot[0]["document_id"] and "version" not in snapshot[0]
    rows = _rows(frames)
    assert [_status(f) for f in rows] == ["converting", "checking", "publishing", "published"]
    ids = [int(f["id"]) for f in rows]
    assert ids == sorted(ids) and len(set(ids)) == 4
    assert frames[-1]["event"] == "upload.settled" and "id" not in frames[-1]
    settled = json.loads(frames[-1]["data"])
    assert settled["upload_id"] == str(upload.id) and settled["last_event_id"] == ids[-1]
    assert settled["items"] == snapshot  # the settled frame carries the final states (P5-4c)
    assert json.loads(rows[0]["data"])["item_id"] == str(items[0].id)


async def test_last_event_id_replays_only_later_events_once(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _world(db, settings, taxonomy)
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=users["editor"],
        role="editor",
        files=[("srs.docx", SRS)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    editor = await _client(make_client, db, settings, users["editor"])
    full = _frames((await editor.get(f"/api/v1/uploads/{upload.id}/events")).text)
    ids = [int(f["id"]) for f in _rows(full)]
    resumed = _frames(
        (
            await editor.get(
                f"/api/v1/uploads/{upload.id}/events", headers={"Last-Event-ID": str(ids[1])}
            )
        ).text
    )
    assert [int(f["id"]) for f in _rows(resumed)] == ids[2:]
    # Every reconnect replays the unseen rows and then re-sends the current states (P5-6).
    assert [f["event"] for f in resumed if "event" in f] == [
        ITEM_STATUS_EVENT,
        ITEM_STATUS_EVENT,
        ITEM_STATUS_EVENT,
        "upload.settled",
    ]
    _assert_snapshot_is_last_word(resumed)
    assert [s["status"] for s in _snapshot(resumed)] == ["published"]
    beyond = _frames(
        (
            await editor.get(
                f"/api/v1/uploads/{upload.id}/events", headers={"Last-Event-ID": str(ids[-1])}
            )
        ).text
    )
    assert [f.get("event") for f in beyond] == [None, ITEM_STATUS_EVENT, "upload.settled"]
    _assert_snapshot_is_last_word(beyond)
    garbage = _frames(
        (
            await editor.get(f"/api/v1/uploads/{upload.id}/events", headers={"Last-Event-ID": "x"})
        ).text
    )
    assert [int(f["id"]) for f in _rows(garbage)] == ids  # unparsable → from the start
    _assert_snapshot_is_last_word(garbage)


async def test_stream_is_authorised_like_get_upload(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _world(db, settings, taxonomy)
    expected = {
        "client_a": 200,
        "owner": 200,
        "editor": 200,
        "viewer": 200,
        "client_b": 404,
        "outsider": 404,
    }
    # Sign everyone in before ``ingest``: it expires the shared ``db`` session and only
    # refreshes the instances it returns, so ``users`` cannot be read afterwards.
    clients = {name: await _client(make_client, db, settings, users[name]) for name in expected}
    anonymous = await make_client()
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=users["client_a"],
        role="client",
        files=[("brd.docx", SRS)],
        specs=[UploadItemSpec(doc_type="brd")],
    )
    url = f"/api/v1/uploads/{upload.id}/events"
    for name, status in expected.items():
        response = await clients[name].get(url)
        assert response.status_code == status, (name, response.status_code)
    assert (await anonymous.get(url)).status_code == 401
    assert (await clients["owner"].get(f"/api/v1/uploads/{uuid.uuid4()}/events")).status_code == 404


async def test_live_events_are_delivered_as_they_are_committed(
    db: AsyncSession,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Looks wrong.", "test-plan")})
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS), ("plan.docx", PLAN)],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="srs", title="Plan")],
        analyzer=fake,
        run=False,
    )
    counter = CountingMaker(db_sessionmaker)
    stream = events.stream_upload_events(
        counter, upload.id, poll_interval=0.02, heartbeat_interval=60
    )
    assert await anext(stream) == "retry: 2000\n\n"
    snapshot = [await _next_frame(stream), await _next_frame(stream)]
    assert [_status(f) for f in snapshot] == ["uploaded", "uploaded"]
    collected: list[str] = []

    async def collect() -> None:
        async for frame in stream:
            collected.append(frame)
            assert counter.open == 0, "a session stayed open while a frame was yielded"

    collector = asyncio.create_task(collect())
    await asyncio.sleep(0.1)  # the stream is polling an upload with two ``uploaded`` items
    assert collected == [] and not collector.done()
    await run_upload(pipeline_context(settings, taxonomy, fake), upload.id)
    await asyncio.wait_for(collector, timeout=10)
    frames = _frames("".join(collected))
    assert sorted(_status(f) for f in _rows(frames)) == sorted(
        [
            "converting",
            "checking",
            "publishing",
            "published",
            "converting",
            "checking",
            "needs_confirmation",
        ]
    )
    assert frames[-1]["event"] == "upload.settled"
    assert sorted(s["status"] for s in json.loads(frames[-1]["data"])["items"]) == [
        "needs_confirmation",
        "published",
    ]
    assert counter.max_open == 1 and counter.open == 0
    # One snapshot per poll, so a transition committing between the two reads can neither be
    # skipped nor settle the stream over its own row (controller ruling P5-6).
    assert set(counter.isolation) == {"repeatable read"}


async def test_heartbeat_while_idle_and_close_releases_sessions(
    db: AsyncSession,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
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
    items[0].status = "checking"  # stuck mid-flight: the stream must wait, not end
    await db.commit()
    counter = CountingMaker(db_sessionmaker)
    stream: AsyncIterator[str] = events.stream_upload_events(
        counter, upload.id, poll_interval=0.01, heartbeat_interval=0.03
    )
    assert await anext(stream) == "retry: 2000\n\n"
    assert _status(await _next_frame(stream)) == "checking"
    assert await asyncio.wait_for(anext(stream), timeout=2) == events.HEARTBEAT
    assert await asyncio.wait_for(anext(stream), timeout=2) == events.HEARTBEAT
    assert counter.opened >= 2 and counter.open == 0  # one session per poll, none kept
    await stream.aclose()  # the client went away
    assert counter.open == 0
    item = await db.get_one(UploadItem, items[0].id)
    assert item.status == "checking"  # the stream only reads


async def test_an_event_committed_out_of_id_order_is_still_delivered(
    db: AsyncSession,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
) -> None:
    """``events.id`` is allocated before commit, so a lower id can commit after a higher one
    has been streamed. The watermark lags behind the newest row, so the straggler is still
    picked up (controller ruling P5-4b)."""
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
    item_id = items[0].id
    items[0].status = "checking"
    await db.commit()
    stream = events.stream_upload_events(
        db_sessionmaker, upload.id, poll_interval=0.01, heartbeat_interval=60
    )
    assert await anext(stream) == "retry: 2000\n\n"
    assert _status(await _next_frame(stream)) == "checking"
    async with db_sessionmaker() as slow, db_sessionmaker() as fast:
        slow.add(_event(upload.id, item_id, "converting"))
        await slow.flush()  # the lower id is allocated but not committed
        fast.add(_event(upload.id, item_id, "publishing"))
        await fast.commit()  # the higher id commits first and is streamed first
        higher = await _next_frame(stream)
        assert _status(higher) == "publishing"
        await slow.commit()  # the lower id lands afterwards, inside the lag window
    lower = await _next_frame(stream)
    assert _status(lower) == "converting"
    assert int(lower["id"]) < int(higher["id"])
    await stream.aclose()


async def test_a_skipped_event_cannot_leave_the_client_wrong(
    db: AsyncSession,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
) -> None:
    """Even with the lag defeated (``event_lag=0``) so the straggler row is skipped for good,
    the client still ends with the true states: the settled frame carries them (P5-4c), and so
    does the snapshot every connect ends with (P5-4a).

    The committing transaction carries both the event row and the item's new status, and a poll
    reads rows and states in one snapshot, so that row is always delivered before the stream
    settles (P5-6) — only the straggler held open behind it is lost."""
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
    item_id = items[0].id
    items[0].status = "checking"
    await db.commit()
    stream = events.stream_upload_events(
        db_sessionmaker, upload.id, poll_interval=0.01, heartbeat_interval=60, event_lag=0.0
    )
    assert await anext(stream) == "retry: 2000\n\n"
    assert _status(await _next_frame(stream)) == "checking"
    delivered: list[dict[str, str]] = []
    async with db_sessionmaker() as slow, db_sessionmaker() as fast:
        slow.add(_event(upload.id, item_id, "publishing"))
        await slow.flush()  # the lower id is allocated but not committed
        fast.add(_event(upload.id, item_id, "needs_confirmation"))
        await fast.execute(
            update(UploadItem).where(UploadItem.id == item_id).values(status="needs_confirmation")
        )
        await fast.commit()  # the higher id, and the state change it describes
        delivered.append(await _next_frame(stream))
        await slow.commit()  # too late: the watermark has already moved past this id
    settled = await _next_frame(stream)
    # The atomically committed row is delivered; the straggler behind it never is.
    assert [_status(f) for f in delivered] == ["needs_confirmation"]
    assert settled["event"] == events.SETTLED_EVENT
    states = json.loads(settled["data"])["items"]
    assert [s["status"] for s in states] == ["needs_confirmation"]  # the truth, not the stream
