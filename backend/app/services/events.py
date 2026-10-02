"""Upload events (spec 10 ``events``, spec 11 SSE): one ``item.status`` row per upload-item
state change, added to the same session (and therefore the same transaction) as the change.
Like ``audit.record``, nothing here commits. Task 3 adds the Server-Sent Events stream."""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ACTIVE_STATUSES, ITEM_STATUS_EVENT, UploadEvent, UploadItem

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
