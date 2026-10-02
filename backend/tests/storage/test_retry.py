"""Shared retry/backoff for the cloud adapters: both of them go through send_with_retry,
so throttling, 5xx and credential failures behave the same on SharePoint and on Drive."""

import asyncio
from collections.abc import Callable

import httpx
import pytest

from app.storage.base import StorageAuthError, StorageError
from app.storage.retry import (
    DRIVE_POLICY,
    GRAPH_POLICY,
    RetryPolicy,
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
    assert clock.slept[0] <= clock.slept[-1]


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
