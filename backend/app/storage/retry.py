"""Retry and backoff shared by the SharePoint and Google Drive adapters (spec 14).

Microsoft Graph throttles with 429 plus ``Retry-After``; Google Drive throttles with 403 and a
quota reason in the body. Both are handled here so neither adapter invents its own backoff, and
so every user-visible message is built from the status code alone — provider bodies can echo
request data and must never reach a log line or an error a user sees (spec 13).
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.storage.base import StorageAuthError, StorageError

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, 509})
DRIVE_QUOTA_REASONS = frozenset({"userRateLimitExceeded", "rateLimitExceeded", "quotaExceeded"})

UNAVAILABLE = "{context} failed: the storage service is temporarily unavailable. Try again."
UNREACHABLE = "{context} failed: the storage service could not be reached."
DENIED = "{context} failed: the storage credentials were rejected or lack permission."
GENERIC = "{context} failed ({status})."


def _drive_quota_response(response: httpx.Response) -> bool:
    if response.status_code != 403:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    errors = payload.get("error", {}).get("errors", []) if isinstance(payload, dict) else []
    return any(
        isinstance(item, dict) and item.get("reason") in DRIVE_QUOTA_REASONS for item in errors
    )


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 0.5
    max_delay: float = 30.0
    statuses: frozenset[int] = field(default=RETRYABLE_STATUSES)
    retry_on_response: Callable[[httpx.Response], bool] | None = None


GRAPH_POLICY = RetryPolicy()
DRIVE_POLICY = RetryPolicy(retry_on_response=_drive_quota_response)


def retry_after_seconds(response: httpx.Response, max_delay: float) -> float | None:
    """``Retry-After`` as seconds, from a number or an HTTP-date, capped at ``max_delay``.
    Returns None when the header is missing or unparseable."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(tz=UTC)).total_seconds()
    return max(0.0, min(seconds, max_delay))


def backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    """Exponential backoff with full jitter; ``attempt`` is 1 for the first retry.

    Full jitter draws from the whole ``[0, ceiling]`` window, not just its top half, so retrying
    clients spread out instead of clustering in a shared half-window and re-creating the
    reconnect storm this project has already had to fix once.
    """
    ceiling = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
    # Jitter spreads concurrent publishes; it is scheduling, not cryptography.
    return max(0.05, random.uniform(0, ceiling))  # noqa: S311


def _should_retry(response: httpx.Response, policy: RetryPolicy) -> bool:
    if response.status_code in policy.statuses:
        return True
    return policy.retry_on_response is not None and policy.retry_on_response(response)


def raise_for_storage(response: httpx.Response, *, context: str) -> None:
    """Turn a failed response into a storage error with a message safe to show a user."""
    status = response.status_code
    if status < 400:
        return
    logger.warning("%s failed with status %s", context, status)  # status only, never the body
    if status in (401, 403):
        raise StorageAuthError(DENIED.format(context=context))
    if status in RETRYABLE_STATUSES:
        raise StorageError(UNAVAILABLE.format(context=context))
    raise StorageError(GENERIC.format(context=context, status=status))


async def send_with_retry(
    client: httpx.AsyncClient,
    build_request: Callable[[], httpx.Request],
    *,
    policy: RetryPolicy,
    context: str,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.Response:
    """Send the request, retrying throttling and transient failures.

    ``build_request`` is a factory, not a request, so each attempt gets a fresh body. A response
    that is not retryable is returned as it is: the caller decides whether 404 means
    ``StorageNotFound`` or something else. Exhausting the attempts raises a storage error.
    """
    last: httpx.Response | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            response = await client.send(build_request())
        except httpx.TransportError:
            if attempt == policy.max_attempts:
                logger.warning("%s: transport error, giving up after %s attempts", context, attempt)
                raise StorageError(UNREACHABLE.format(context=context)) from None
            logger.warning("%s: transport error, attempt %s", context, attempt)
            await sleep(backoff_delay(attempt, policy))
            continue
        if not _should_retry(response, policy):
            if response.status_code in (401, 403):
                raise_for_storage(response, context=context)
            return response
        last = response
        if attempt == policy.max_attempts:
            break
        delay = retry_after_seconds(response, policy.max_delay)
        await sleep(delay if delay is not None else backoff_delay(attempt, policy))
    assert last is not None  # noqa: S101 - the loop only breaks after a retryable response
    # status only, never the body: the same secrecy rule as raise_for_storage
    logger.warning(
        "%s: giving up after %s attempts, last status %s",
        context,
        policy.max_attempts,
        last.status_code,
    )
    raise StorageError(UNAVAILABLE.format(context=context))
