"""Upload events (spec 10 ``events``, spec 11 SSE): one ``item.status`` row per upload-item
state change, added to the same session (and therefore the same transaction) as the change.
Like ``audit.record``, nothing here commits. Below that, the Server-Sent Events stream
that replays and tails those rows."""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    ACTIVE_STATUSES,
    ITEM_STATUS_EVENT,
    DocumentVersion,
    UploadEvent,
    UploadItem,
)

# The only fields a payload may carry besides ``item_id`` and ``status``: ids, verdicts and
# short messages. Never conversion metadata, outlines, file names or document content.
PAYLOAD_FIELDS = frozenset(
    {
        "type_check",
        "check_explanation",
        "suggested_doc_type",
        "final_doc_type",
        "error",
        "document_id",
        "version",
    }
)
EVENT_PAGE = 500


def item_status_payload(
    item_id: uuid.UUID, status: str, fields: Mapping[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {"item_id": str(item_id), "status": status}
    for key, value in fields.items():
        if key in PAYLOAD_FIELDS:
            payload[key] = str(value) if isinstance(value, uuid.UUID) else value
    return payload


async def record_item_status(
    db: AsyncSession, *, upload_id: uuid.UUID, item_id: uuid.UUID, status: str, **fields: Any
) -> None:
    """Queue an ``item.status`` event on ``db``. The caller's commit writes it together with
    the state change it describes."""
    db.add(
        UploadEvent(
            upload_id=upload_id,
            item_id=item_id,
            type=ITEM_STATUS_EVENT,
            payload=item_status_payload(item_id, status, fields),
        )
    )


async def events_after(
    db: AsyncSession, upload_id: uuid.UUID, after_id: int, *, limit: int = EVENT_PAGE
) -> list[UploadEvent]:
    """Events of one upload with ``id > after_id``, oldest first (the SSE replay query)."""
    return list(
        (
            await db.scalars(
                select(UploadEvent)
                .where(UploadEvent.upload_id == upload_id, UploadEvent.id > after_id)
                .order_by(UploadEvent.id)
                .limit(limit)
            )
        ).all()
    )


async def is_settled(db: AsyncSession, upload_id: uuid.UUID) -> bool:
    """True when no item of the upload is still being worked on. Items waiting for the user
    (``needs_confirmation``) count as settled: nothing happens until the user acts."""
    active = await db.scalar(
        select(func.count())
        .select_from(UploadItem)
        .where(UploadItem.upload_id == upload_id, UploadItem.status.in_(list(ACTIVE_STATUSES)))
    )
    return not active


async def item_states(db: AsyncSession, upload_id: uuid.UUID) -> list[dict[str, Any]]:
    """The current state of every item of the upload, in the payload shape of an
    ``item.status`` event, oldest item first.

    This is read straight from the item rows, so it is authoritative: a client that applies it
    is correct whatever it did or did not receive before. ``events.id`` is an identity
    sequence whose value is allocated before commit, so two transactions writing events for
    the same upload can commit out of allocation order and a reader that has advanced past the
    higher id can miss the lower one. ``stream_upload_events`` sends these states on connect
    and again with ``upload.settled`` so that such a miss can never leave the client wrong.
    """
    rows = (
        await db.execute(
            select(UploadItem, DocumentVersion.document_id, DocumentVersion.version)
            .outerjoin(DocumentVersion, DocumentVersion.upload_item_id == UploadItem.id)
            .where(UploadItem.upload_id == upload_id)
            .order_by(UploadItem.created_at, UploadItem.id)
        )
    ).all()
    states: list[dict[str, Any]] = []
    for item, document_id, version in rows:
        fields: dict[str, Any] = {
            "type_check": item.type_check,
            "check_explanation": item.check_explanation,
            "suggested_doc_type": item.suggested_doc_type,
            "final_doc_type": item.final_doc_type,
            "error": item.error,
        }
        if document_id is not None:
            fields["document_id"], fields["version"] = document_id, version
        states.append(item_status_payload(item.id, item.status, fields))
    return states


RETRY_MS = 2000
HEARTBEAT = ": ping\n\n"
SETTLED_EVENT = "upload.settled"
POLL_INTERVAL = 0.5  # spec 17: SSE latency under 2 seconds
HEARTBEAT_INTERVAL = 15.0  # the Next.js rewrite proxy closes a response idle for 30 seconds
# How far behind the newest event row the watermark is kept. An event row is flushed (which
# allocates its id) inside the ``commit()`` that writes it, so the window in which a lower id
# can still appear after a higher one is visible is the length of a single COMMIT round trip —
# milliseconds. Five seconds is three orders of magnitude more, and costs only a few extra
# reads of the same handful of rows at the tip of the stream.
EVENT_LAG = 5.0
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def sse_frame(event_type: str, data: Mapping[str, Any], event_id: int | None = None) -> str:
    lines = [] if event_id is None else [f"id: {event_id}"]
    lines.append(f"event: {event_type}")
    lines.append("data: " + json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    return "\n".join(lines) + "\n\n"


def parse_last_event_id(value: str | None) -> int:
    """The browser's ``Last-Event-ID`` header; anything but a non-negative integer → 0."""
    if value is None or not value.strip().isdigit():
        return 0
    return int(value.strip())


async def stream_upload_events(
    maker: async_sessionmaker[AsyncSession],
    upload_id: uuid.UUID,
    *,
    last_event_id: int = 0,
    poll_interval: float = POLL_INTERVAL,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
    event_lag: float = EVENT_LAG,
) -> AsyncIterator[str]:
    """Send the current item states, then the event rows after ``last_event_id``, then poll
    for new ones until the upload is settled.

    Every poll opens and closes its own session, so no connection is held between polls or for
    the lifetime of the stream; a client disconnect cancels the generator at the next ``await``
    and the ``async with`` closes whatever session is open.

    Three things together make the client's view correct even though ``events.id`` values are
    allocated before commit and can therefore become visible out of order:

    * the first frames after ``retry:`` are the item states read fresh from the database, so
      every connect and reconnect starts from the truth rather than from replayed rows;
    * the watermark ``safe`` — the id below which nothing can still arrive — is advanced only
      past rows first seen at least ``event_lag`` ago, and the ids above it are re-read every
      poll (``sent`` keeps each from being sent twice), so a row that commits late is still
      delivered;
    * ``upload.settled`` carries the final item states, so a row skipped despite all of that
      still cannot leave the client wrong.

    The rows are read *before* the states, so the states are at least as new as the rows: a
    change that commits between the two statements is reflected in the snapshot that
    ``upload.settled`` carries even when its event row was not read.
    """
    safe = last_event_id
    delivered = last_event_id
    sent: dict[int, float] = {}  # ids above ``safe`` -> when they were first read
    last_frame = time.monotonic()
    snapshot_sent = False
    yield f"retry: {RETRY_MS}\n\n"
    while True:
        async with maker() as db:
            rows = await events_after(db, upload_id, safe)
            states = await item_states(db, upload_id)
        settled = not any(state["status"] in ACTIVE_STATUSES for state in states)
        now = time.monotonic()
        frames: list[str] = []
        if not snapshot_sent:
            snapshot_sent = True
            frames.extend(sse_frame(ITEM_STATUS_EVENT, state) for state in states)
        for row in rows:
            if row.id in sent:
                continue
            sent[row.id] = now
            delivered = max(delivered, row.id)
            frames.append(sse_frame(row.type, row.payload, row.id))
        for frame in frames:
            yield frame
        if frames:
            last_frame = time.monotonic()
        if len(rows) == EVENT_PAGE:
            # A full page is backlog, not the tip of the stream: there is more behind it, so
            # these rows are long committed and the watermark can follow them at once.
            safe, sent = rows[-1].id, {}
            continue
        highest = max(sent, default=safe)
        if highest > safe and now - sent[highest] >= event_lag:
            safe, sent = highest, {}
        if settled:
            yield sse_frame(
                SETTLED_EVENT,
                {"upload_id": str(upload_id), "last_event_id": delivered, "items": states},
            )
            return
        if time.monotonic() - last_frame >= heartbeat_interval:
            yield HEARTBEAT
            last_frame = time.monotonic()
        await asyncio.sleep(poll_interval)
