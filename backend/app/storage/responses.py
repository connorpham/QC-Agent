"""Shared, minimal response parsing for the cloud storage adapters (spec 8, 13).

Neither Microsoft Graph nor Google Drive has ever been exercised against a real tenant on this
branch, so an unexpected response shape - a missing field, a non-JSON body, a missing redirect
header, a timestamp that does not parse - is the expected case here, not a bug to let raise a
bare ``KeyError``, ``IndexError`` or ``ValueError`` out of an adapter (the publish path happens
to catch broadly and degrade to a failed item; the health path does not, and the public
``/health`` route has no such safety net at all - finding 8). Every parse failure here becomes
the same fixed, user-safe storage error; the field name and the response body are never included,
so nothing a provider sends can leak into a log line or a message a user sees (spec 13).
"""

from datetime import datetime
from typing import Any

import httpx

from app.storage.base import StorageError

UNEXPECTED = "{context} failed: the storage service returned an unexpected response."


def parsed_json(response: httpx.Response, *, context: str) -> dict[str, Any]:
    """The response's JSON body, which must parse and must be an object."""
    try:
        data = response.json()
    except ValueError as exc:
        raise StorageError(UNEXPECTED.format(context=context)) from exc
    if not isinstance(data, dict):
        raise StorageError(UNEXPECTED.format(context=context))
    return data


def required_str(data: dict[str, Any], key: str, *, context: str) -> str:
    """A required, non-empty string field of an already-parsed body."""
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise StorageError(UNEXPECTED.format(context=context))
    return value


def required_header(response: httpx.Response, name: str, *, context: str) -> str:
    """A required, non-empty response header - a redirect's ``Location``, for instance."""
    value = response.headers.get(name)
    if not value:
        raise StorageError(UNEXPECTED.format(context=context))
    return str(value)


def parsed_timestamp(value: Any, *, context: str) -> datetime:
    """An ISO-8601 timestamp ending in ``Z``, as both Graph and Drive send one."""
    if not isinstance(value, str) or not value:
        raise StorageError(UNEXPECTED.format(context=context))
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StorageError(UNEXPECTED.format(context=context)) from exc
