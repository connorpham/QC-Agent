"""Shared retry/backoff for the cloud adapters: both of them go through send_with_retry,
so throttling, 5xx and credential failures behave the same on SharePoint and on Drive."""

import asyncio
import logging
from collections.abc import Callable

import httpx
import pytest

from app.storage.base import StorageAuthError, StorageError
from app.storage.retry import (
    DRIVE_POLICY,
    GRAPH_POLICY,
    RetryPolicy,
    backoff_delay,
    raise_for_storage,
    retry_after_seconds,
    send_with_retry,
)

URL = "https://example.invalid/probe"


class Clock:
    """Records what send_with_retry would have slept instead of sleeping."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _builder(client: httpx.AsyncClient) -> Callable[[], httpx.Request]:
    return lambda: client.build_request("GET", URL)


async def test_retries_429_then_succeeds_and_honours_retry_after() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"id": "x"})

    clock = Clock()
    async with _client(handler) as client:
        response = await send_with_retry(
            client, _builder(client), policy=GRAPH_POLICY, context="probe", sleep=clock
        )
    assert response.status_code == 200
    assert calls == 2
    assert clock.slept == [7.0]


async def test_retry_after_is_capped_at_max_delay() -> None:
    response = httpx.Response(429, headers={"Retry-After": "3600"})
    assert retry_after_seconds(response, 30.0) == 30.0


async def test_retry_after_accepts_an_http_date() -> None:
    response = httpx.Response(429, headers={"Retry-After": "Thu, 02 Oct 2026 10:00:30 GMT"})
    seconds = retry_after_seconds(response, 30.0)
    assert seconds is not None and 0.0 <= seconds <= 30.0


async def test_retry_after_ignores_garbage() -> None:
    assert retry_after_seconds(httpx.Response(429, headers={"Retry-After": "soon"}), 30.0) is None


async def test_backoff_grows_and_stays_inside_the_cap() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    clock = Clock()
    policy = RetryPolicy(max_attempts=4, base_delay=1.0, max_delay=5.0)
    async with _client(handler) as client:
        with pytest.raises(StorageError, match="temporarily unavailable"):
            await send_with_retry(
                client, _builder(client), policy=policy, context="probe", sleep=clock
            )
    assert len(clock.slept) == 3  # one sleep between each of the four attempts
    assert all(0.0 < delay <= 5.0 for delay in clock.slept)


async def test_backoff_delay_is_full_jitter_not_equal_jitter() -> None:
    """Full jitter draws from the whole [0, ceiling] range. Equal jitter (ceiling/2..ceiling,
    the brief's original reference code) can never produce a value below the midpoint, so a
    large sample that never dips below it would mean the naive half-range formula crept back
    in."""
    policy = RetryPolicy(base_delay=1.0, max_delay=4.0)
    ceiling = 4.0  # attempt 3: base_delay * 2**2 == 4.0, already at the cap
    samples = [backoff_delay(3, policy) for _ in range(500)]
    assert all(0.0 <= delay <= ceiling for delay in samples)
    assert min(samples) < ceiling / 2


async def test_transport_errors_are_retried_then_reported_as_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    clock = Clock()
    policy = RetryPolicy(max_attempts=3, base_delay=0.1, max_delay=1.0)
    async with _client(handler) as client:
        with pytest.raises(StorageError, match="could not be reached"):
            await send_with_retry(
                client, _builder(client), policy=policy, context="probe", sleep=clock
            )
    assert len(clock.slept) == 2


async def test_status_exhaustion_logs_a_warning_without_the_response_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-token-value"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"Unavailable: {secret}")

    clock = Clock()
    policy = RetryPolicy(max_attempts=2, base_delay=0.1, max_delay=1.0)
    with caplog.at_level(logging.WARNING, logger="app.storage.retry"):
        async with _client(handler) as client:
            with pytest.raises(StorageError, match="temporarily unavailable"):
                await send_with_retry(
                    client, _builder(client), policy=policy, context="probe", sleep=clock
                )
    messages = [record.getMessage() for record in caplog.records]
    assert any("probe" in message and "503" in message for message in messages)
    assert not any(secret in message for message in messages)


async def test_transport_exhaustion_logs_a_warning_without_leaking_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host 10.0.0.1", request=request)

    clock = Clock()
    policy = RetryPolicy(max_attempts=2, base_delay=0.1, max_delay=1.0)
    with caplog.at_level(logging.WARNING, logger="app.storage.retry"):
        async with _client(handler) as client:
            with pytest.raises(StorageError, match="could not be reached"):
                await send_with_retry(
                    client, _builder(client), policy=policy, context="probe", sleep=clock
                )
    messages = [record.getMessage() for record in caplog.records]
    assert any("probe" in message and str(policy.max_attempts) in message for message in messages)
    assert not any("10.0.0.1" in message for message in messages)


async def test_drive_quota_403_is_retried_but_a_plain_403_is_not() -> None:
    quota = {"error": {"errors": [{"reason": "userRateLimitExceeded"}], "code": 403}}
    denied = {"error": {"errors": [{"reason": "insufficientFilePermissions"}], "code": 403}}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("case", ""))
        return httpx.Response(403, json=quota if seen[-1] == "quota" else denied)

    clock = Clock()
    policy = RetryPolicy(
        max_attempts=2,
        base_delay=0.1,
        max_delay=1.0,
        retry_on_response=DRIVE_POLICY.retry_on_response,
    )
    async with _client(handler) as client:
        with pytest.raises(StorageError):
            await send_with_retry(
                client,
                lambda: client.build_request("GET", URL, params={"case": "quota"}),
                policy=policy,
                context="probe",
                sleep=clock,
            )
        assert len(clock.slept) == 1  # retried once, then gave up
        clock.slept.clear()
        with pytest.raises(StorageAuthError):
            await send_with_retry(
                client,
                lambda: client.build_request("GET", URL, params={"case": "denied"}),
                policy=policy,
                context="probe",
                sleep=clock,
            )
        assert clock.slept == []  # a permission failure is not a throttle


@pytest.mark.parametrize("status", [401, 403])
async def test_credential_statuses_raise_storage_auth_error(status: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope"}})

    clock = Clock()
    async with _client(handler) as client:
        with pytest.raises(StorageAuthError, match="credentials"):
            await send_with_retry(
                client, _builder(client), policy=GRAPH_POLICY, context="probe", sleep=clock
            )


@pytest.mark.parametrize("status", [401, 403])
async def test_raise_on_auth_error_false_returns_the_response_instead(status: int) -> None:
    """A staged health probe needs to inspect a 401/403 itself, not have it raised away."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope"}})

    clock = Clock()
    async with _client(handler) as client:
        response = await send_with_retry(
            client,
            _builder(client),
            policy=GRAPH_POLICY,
            context="probe",
            sleep=clock,
            raise_on_auth_error=False,
        )
    assert response.status_code == status
    assert clock.slept == []


async def test_error_message_never_contains_the_response_body() -> None:
    """Provider bodies can echo request headers, so they never reach a message a user sees."""
    secret = "super-secret-token-value"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f"Bad request: {secret}")

    async with _client(handler) as client:
        with pytest.raises(StorageError) as caught:
            raise_for_storage(await client.get(URL), context="Uploading srs--demo.md")
    message = str(caught.value)
    assert secret not in message
    assert "Uploading srs--demo.md" in message and "400" in message


async def test_log_context_reaches_only_the_log_never_the_raised_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``context`` reaches the raised ``StorageError`` message, which a client can read back
    through ``item.error``; ``log_context`` may carry an internal identifier (a Shared Drive id,
    a SharePoint site or library id) but must never leak into that message - only into the log
    line (wave 2 of finding 9)."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    async with _client(handler) as client:
        with caplog.at_level(logging.WARNING), pytest.raises(StorageError) as caught:
            raise_for_storage(
                await client.get(URL),
                context="Uploading a file",
                log_context="Uploading a file (drive shared-drive-test)",
            )
    message = str(caught.value)
    assert "shared-drive-test" not in message
    assert message == "Uploading a file failed (404)."
    logged = [r.getMessage() for r in caplog.records]
    assert any("shared-drive-test" in m for m in logged)


async def test_log_context_defaults_to_context_when_not_given() -> None:
    """A caller with nothing extra to log (no connection identifier involved) need not pass
    ``log_context`` - the log line still identifies the operation."""
    with pytest.raises(StorageError) as caught:
        raise_for_storage(httpx.Response(500), context="Checking the connection")
    assert (
        str(caught.value) == "Checking the connection failed: the storage service is "
        "temporarily unavailable. Try again."
    )


async def test_non_retryable_success_is_returned_untouched() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    clock = Clock()
    async with _client(handler) as client:
        response = await send_with_retry(
            client, _builder(client), policy=GRAPH_POLICY, context="probe", sleep=clock
        )
    assert response.status_code == 404  # the adapter maps 404 to StorageNotFound itself
    assert clock.slept == []


async def test_default_sleep_is_asyncio_sleep() -> None:
    assert send_with_retry.__defaults__ is None  # sleep is keyword-only
    assert send_with_retry.__kwdefaults__["sleep"] is asyncio.sleep
