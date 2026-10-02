# Plan 3b — Cloud Storage Adapters: SharePoint (Microsoft Graph) and Google Drive

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** QC-Agent stores project documents on SharePoint (Microsoft Graph, app-only `Sites.Selected`) and on Google Drive (Drive API v3, service account), configured by an administrator in the Admin → Storage page, with the same `StorageBackend` contract, shared retry/backoff, and health checks that name the two failures that actually happen in production: an expired credential and a library whose version history is off.

**Architecture:** Both adapters speak HTTP through one shared `httpx.AsyncClient` and one shared retry layer (`app/storage/retry.py`) that honours `Retry-After`, so neither adapter invents its own backoff. SharePoint is path-addressed natively, so `SharePointBackend` maps `StorageBackend` paths onto `/drives/{drive-id}/root:/{path}:` addresses and never touches a second library. Google Drive is id-addressed, so `DriveResolver` (`app/storage/gdrive_paths.py`) walks each path segment to a file id with a per-connection TTL cache and raises on a duplicate name instead of guessing; `GoogleDriveBackend` sits on top of it. Credentials stay where Plan 3a put them: Fernet-encrypted in `storage_connections.secret_enc`, decrypted only inside `app/storage/select.py`, never returned by an API and never logged. `health()` is a staged probe that returns a field-level diagnosis — which input is wrong, not just pass or fail — so a mistyped id is caught on Test connection instead of at the first upload. The frontend gains two type-specific field sets inside the existing connection dialog, driven by one descriptor module, so an administrator configures a connection entirely by typing into that dialog: no config file edit, no server restart. The existing shared contract suite runs against the real services only when `QC_AGENT_LIVE_STORAGE=1`.

**Tech Stack:** Python 3.12 with uv; new runtime dependencies `httpx` (promoted from the dev group), `msal` (Entra client-credentials token), `google-auth` (service-account token). Existing: FastAPI 0.142, SQLAlchemy 2.1 asyncio, cryptography/Fernet, pytest + pytest-asyncio, ruff, mypy strict. Frontend unchanged: Next.js 16.3, React 19.2, TypeScript 5.9 strict, Tailwind 4, Vitest 5 + Testing Library, pnpm 11.

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` v2.3 — section 8 in full (8.1 interface, 8.2 SharePoint, 8.3 Google Drive, 8.4 local FS, 8.5 connections, 8.6 access and secret expiry), 13 (security), 14 (error handling), 15 (testing strategy), 16 + 16.1 (`/health`, configuration), and the Decision Log in section 3 (one shared SharePoint site, one document library per customer; both adapters built together). Roadmap row: `docs/superpowers/plans/2026-10-01-phase1-roadmap.md`, line 15.

**Scope note (2026-10-02):** the stakeholder chose to build both adapters in this plan rather than one first. Plan 3c (changing a project's storage with migration) and Plan 4 (agent) are unaffected and depend on nothing added here.

## Two prerequisites no form can satisfy

Everything else in this plan is typed into the Admin → Storage dialog. These two are grants a
tenant administrator makes outside QC-Agent, and no field in any form can stand in for them. A
connection whose fields are all correct will still fail `Test connection` until they are done,
and the message says so:

1. **SharePoint — the `Sites.Selected` grant.** A Microsoft 365 administrator must register the
   Entra ID application, consent to the application permission `Sites.Selected`, and then grant
   that application `write` on the one shared SharePoint site. Without the grant, Graph answers
   403 for every request, however correct the tenant id, client id, client secret, site id and
   library id are. Diagnosis shown: *"No write permission on this site. A Microsoft 365
   administrator must grant this application write access to the site (Sites.Selected)."*
2. **Google Drive — Shared Drive membership.** A Google Workspace administrator must enable the
   Drive API for the project and add the service account to the Shared Drive as **Content
   manager**. A service-account key alone grants nothing: the account must be a member of that
   specific Shared Drive. Diagnosis shown: *"The service account is not a member of this Shared
   Drive, or has no permission to add files. Add it as Content manager."*

Both are already tracked in `docs/PENDING.md` section 3 as items owned by IT.

QC-Agent never changes storage permissions (spec 8.6). Team members reach a customer's documents
through the grant IT makes on that document library or Shared Drive; customers never get storage
access and read through the web app. Every permission the application enforces is its own, in the
database, and nothing in this plan reads or writes outside the one library or Shared Drive its
connection names.

## Changes from the spec, and why

- **Drive is called over REST with `httpx`, not with `google-api-python-client`.** Spec 8.3 names that library. It is synchronous and discovery-based, which would mean a second HTTP stack, a second retry implementation and `asyncio.to_thread` around every call, in a codebase whose rule is "no blocking I/O directly in `async def`". Calling `https://www.googleapis.com/drive/v3/...` with the shared `httpx.AsyncClient` gives both adapters one retry layer, as the plan brief requires. `google-auth` is still used — for service-account credentials and token minting only, in a worker thread. Everything else spec 8.3 asks for is unchanged: Drive API v3, service account, `supportsAllDrives=true` on every call, resumable uploads, `files.update` on the existing file id, revisions with `keepForever`.
- **`StorageBackend` keeps the `exists()` method** that Plan 2 added and spec 8.1 does not list. The contract suite already exercises it; removing it would break `app/services/workspace.py`. Both new adapters implement it.
- **`health()` proves SharePoint versioning by writing a probe file twice**, because Graph v1.0 does not expose a document library's `EnableVersioning` setting. The probe writes one small file (`.qc-agent-health.txt`) in the connection's own library, counts its versions, and deletes it. The result is cached in-process for 10 minutes so repeated checks do not churn the library.
- **`keepForever` is not set on `project.yaml` or anything under `_reports/`.** Those files are rewritten on every publish, and Drive caps `keepForever` revisions per file. Setting it on churn files would burn the cap on bookkeeping instead of on document versions. This resolves the open item "Plan 3b: version policy for gap report and `project.yaml`" in `docs/PENDING.md`.
- **No pipeline change is needed for an expired credential.** `StorageAuthError` inherits `StorageError`, which `app/services/pipeline.py` already turns into a failed item carrying the message, so spec 14's "uploads to affected projects blocked with a clear message" is satisfied by the message text alone ("...check the tenant id, client id and client secret, and whether the secret has expired in Entra ID").
- **`/health` reports storage as a single `ok`/`error` value with no names or details**, because the endpoint is unauthenticated (`app/api/routes/health.py` has no auth dependency). Connection names, site ids, drive ids and provider error text are admin-only and stay in `POST /storage-connections/{id}/test`.

## Global Constraints

- Backend commands run from `backend/`; frontend commands from `frontend/`. Python `>=3.12,<3.13` via uv. After every backend task `uv run ruff format .`, `uv run ruff check .`, `uv run mypy app` (strict) and `uv run pytest` pass. After every frontend task `pnpm lint`, `pnpm format`, `pnpm typecheck`, `pnpm test`, `pnpm api:check` and `pnpm build` pass; run `pnpm format:write` before committing.
- All Plan 1, 2, 3a and 5 Global Constraints still apply: API prefix `/api/v1`; all UI and API copy in English; CSRF header `X-QC-Agent: 1` on every state-changing request; `Annotated` dependencies; services never import `app.api`; audit rows through `app.services.audit.record` (which never commits); one route, one commit; PostgreSQL 16 on `localhost:5434`, tests against `qc_agent_test`, never SQLite; no blocking I/O directly in `async def`.
- Storage types are exactly `localfs`, `sharepoint`, `gdrive` (`StorageType` in `app/schemas/storage.py`). Exactly one connection is the default, enforced by the partial unique index `uq_storage_connections_single_default`. Connections are never deleted.
- **Secrets.** Storage secrets live only in `storage_connections.secret_enc`, Fernet-encrypted with `SECRET_ENCRYPTION_KEY` via `app.core.crypto.SecretBox`. They are write-only: no API response ever contains one, only `has_secret: bool`. A secret is decrypted in exactly one place, `app/storage/select.py`, and is passed straight to a token provider. No secret, access token, `Authorization` header, tenant id, client id, site id, drive id or service-account `private_key`/`client_email` may appear in a log line, an exception message, an API response body, a test fixture, a committed `.json`, or this plan. Error messages are built from the HTTP status and a fixed sentence, never from the provider's response body.
- **Customer isolation.** All projects share one SharePoint site and each customer has its own document library (spec 8.2, Decision Log 3.1). A `sharepoint` connection carries exactly one `drive_id`, and every Graph request the adapter makes at runtime starts with `https://graph.microsoft.com/v1.0/drives/{drive_id}/`. The adapter never enumerates the site's libraries, never calls `/sites/{site-id}/drives`, and never accepts a drive id from a path. `health()` may additionally read `/sites/{site_id}?$select=id,webUrl` once, to confirm the configured library belongs to the configured site by comparing `webUrl` prefixes — it reads no other library's name, id or content. A `gdrive` connection carries exactly one `drive_id` (a Shared Drive) and every Drive query is scoped with `driveId=<that drive>`, `corpora=drive`, `includeItemsFromAllDrives=true`, `supportsAllDrives=true`.
- **Configuration is typed, not deployed.** A new connection of either type is created entirely in the Admin → Storage dialog, takes effect for the next request, and requires no `.env` change, no file on the server and no restart. The field sets are exactly these, and the API schema, the form and this plan use the same names:
  - `sharepoint`: display name, tenant id, client id, client secret (write-only, encrypted), site id, document library (drive) id. One connection per customer library on the single shared site.
  - `gdrive`: display name, Shared Drive id, service-account JSON key (write-only, encrypted).
- **`Test connection` diagnoses the field, not just the outcome.** `HealthStatus` carries `field: str | None` alongside `ok` and `detail`, and `StorageTestResult` returns it, so the dialog can point at the wrong input. The staged probe distinguishes at least: credentials rejected, site id not found, document library (drive) id not found, library does not belong to the configured site, no write permission granted (the `Sites.Selected` grant or the Shared Drive membership is missing), and version history disabled on the library. Every message names the input or the grant at fault and contains no token, secret, or provider response body.
- Microsoft Graph: app-only client credentials via `msal`, scope `https://graph.microsoft.com/.default`, permission `Sites.Selected`. Files of 4 MiB (`4 * 1024 * 1024`) or less upload with a single `PUT …:/content`; larger files use `createUploadSession` with chunks that are a multiple of 320 KiB (`CHUNK_BYTES = 5 * 320 * 1024`). Versions come from `driveItem/versions`.
- Google Drive: Drive API v3 at `https://www.googleapis.com/drive/v3`, uploads at `https://www.googleapis.com/upload/drive/v3`, scope `https://www.googleapis.com/auth/drive`. `supportsAllDrives=true` on every call. Files of 5 MiB (`5 * 1024 * 1024`) or less use `uploadType=multipart`; larger files use `uploadType=resumable`. A new version is `files.update` on the existing file id, never a second `files.create`. Published versions get `keepForever` except `project.yaml` and anything under `_reports/`.
- Retries live in `app/storage/retry.py` and are shared: both adapters pass a `RetryPolicy` to `send_with_retry`. Retryable: a transport error, status 429, 500, 502, 503, 504, 509, and a Drive 403 whose body reason is `userRateLimitExceeded`, `rateLimitExceeded` or `quotaExceeded`. `Retry-After` (seconds or HTTP-date) is honoured and capped at `max_delay`. Default policy: 5 attempts, 0.5 s base, 30 s cap, full jitter.
- Tests: no customer data, no real tenant id, site id, drive id, client id, secret or service-account key anywhere in the repository. The repository's gitleaks pre-commit hook rejects a literal `-----BEGIN PRIVATE KEY-----`, so every synthetic service-account fixture builds its `private_key` from the `FAKE_PEM` constant defined in that test file rather than writing the header out. Offline tests drive both adapters with `httpx.MockTransport` and a fake token provider; `msal` and `google-auth` are never called offline. The default `uv run pytest` run makes no network call and costs nothing.
- Live tests are opt-in: the storage contract suite runs against real SharePoint and Google Drive only when `QC_AGENT_LIVE_STORAGE=1`. CI never sets it.
- Generated files `frontend/openapi.json` and `frontend/src/lib/api/schema.d.ts` are never hand-edited. Regenerate with `uv run python -m app.openapi_export ../frontend/openapi.json` (from `backend/`) and `pnpm api:generate` (from `frontend/`).

## Review Focus

1. `/health` is unauthenticated, so a storage failure must never leak a connection name, tenant id, site id, drive id or provider error text to an anonymous caller, and must not fire one outbound API call per request → `test_health_reports_storage_without_any_detail` and `test_the_result_is_cached` (Task 6).
2. An expired or revoked client secret / service-account key (spec 8.6 "Secret expiry") must surface as a failing connection with a user-safe sentence, and the secret and the bearer token must never reach a log line or an exception message → `test_health_diagnoses_each_failure_stage` and `test_health_message_never_contains_a_token_or_a_provider_body` (Tasks 3 and 4), `test_error_message_never_contains_the_response_body` (Task 1).
3. A duplicate name at any Drive path segment must raise instead of picking one, including when a cached folder id has been trashed or renamed behind our back → `test_duplicate_segment_is_an_error`, `test_cached_id_that_no_longer_resolves_is_refetched` (Task 2).
4. A mistyped site id, a library id from another site, a missing `Sites.Selected` grant and a library with version history disabled must each produce their own diagnosis naming the field or grant at fault, rather than one "connection failed" → `test_health_diagnoses_each_failure_stage` and `test_health_reports_versioning_disabled` (Task 4), `test_health_diagnoses_each_failure_stage` (Task 3).
5. An unsafe path (`../`, absolute, `.versions`, backslash) must be rejected before any network call, and no path may resolve outside the connection's own library or Shared Drive root — a cross-customer write — → `test_unsafe_paths_make_no_request` (Tasks 3 and 4), `test_every_request_stays_inside_the_configured_drive` (Task 3), `test_every_request_stays_inside_the_configured_library` (Task 4), `test_resolver_never_leaves_the_root` (Task 2).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/storage/http.py` (new) | One process-wide `httpx.AsyncClient` with timeouts and limits; the `TokenProvider` protocol; shutdown hook. |
| `backend/app/storage/retry.py` (new) | `RetryPolicy`, `send_with_retry`, `Retry-After` parsing, jittered backoff, status → storage-error mapping with safe messages. |
| `backend/app/storage/gdrive_paths.py` (new) | `DriveResolver` + `FolderCache`: path segment → file id, duplicate detection, Drive query escaping. Nothing else knows Drive's query language. |
| `backend/app/storage/gdrive.py` (new) | `GoogleDriveBackend` and `ServiceAccountTokenProvider`. |
| `backend/app/storage/sharepoint.py` (new) | `SharePointBackend` and `GraphTokenProvider`. |
| `backend/app/storage/base.py` (modify) | Two new error classes (`StorageAuthError`, `StorageAmbiguousPath`) and `HealthStatus.field` for the field-level diagnosis. |
| `backend/app/storage/select.py` (modify) | Decrypt the secret, cache token providers per connection, build the two new adapters. |
| `backend/app/schemas/storage.py` (modify) | `SharePointConfig`, `GDriveConfig`. |
| `backend/app/services/storage_connections.py` (modify) | Accept the two new types, dispatch config validation, require a secret for them. |
| `backend/app/services/storage_health.py` (new) | Per-connection health summary with a short TTL cache, used by the public `/health` route only. |
| `backend/app/api/routes/health.py` (modify) | Add the detail-free `storage` check. |
| `backend/tests/storage/conftest.py` (modify) | `sharepoint` and `gdrive` params for the contract suite behind `QC_AGENT_LIVE_STORAGE=1`. |
| `backend/tests/storage/live.py` (new) | Live-credential loading and the throwaway test folder for the live params. |
| `frontend/src/features/admin/connectionTypes.ts` (new) | One descriptor per storage type: fields, defaults, config builder, list summary. |
| `frontend/src/features/admin/ConnectionDialog.tsx` (modify) | Render the fields of the chosen type; require a secret where the type needs one. |
| `frontend/src/features/admin/StorageAdmin.tsx` (modify) | Show a type-appropriate location summary instead of `config.root_path`. |

---

### Task 1: Shared HTTP client, retry/backoff and cloud storage errors

**Needs live credentials:** no. Everything here is proven offline with `httpx.MockTransport` and an injected sleep.

**Files:**
- Create: `backend/app/storage/http.py`
- Create: `backend/app/storage/retry.py`
- Modify: `backend/app/storage/base.py` (add two error classes after `StorageNotFound`)
- Modify: `backend/app/storage/__init__.py` (export them)
- Modify: `backend/app/main.py` (close the shared client on shutdown)
- Modify: `backend/pyproject.toml` (move `httpx` into runtime dependencies)
- Test: `backend/tests/storage/test_retry.py`

**Interfaces:**
- Consumes: `StorageError` from `app/storage/base.py`.
- Produces:
  - `app.storage.base.StorageAuthError(StorageError)`, `app.storage.base.StorageAmbiguousPath(StorageError)`, `HealthStatus(ok: bool, detail: str = "", field: str | None = None)`
  - `app.storage.http.get_client() -> httpx.AsyncClient`, `app.storage.http.aclose_client() -> None`, `class TokenProvider(Protocol): async def token(self) -> str`
  - `app.storage.retry.RetryPolicy(max_attempts: int = 5, base_delay: float = 0.5, max_delay: float = 30.0, statuses: frozenset[int] = RETRYABLE_STATUSES, retry_on_response: Callable[[httpx.Response], bool] | None = None)`
  - `app.storage.retry.GRAPH_POLICY: RetryPolicy`, `app.storage.retry.DRIVE_POLICY: RetryPolicy`
  - `async app.storage.retry.send_with_retry(client: httpx.AsyncClient, build_request: Callable[[], httpx.Request], *, policy: RetryPolicy, context: str, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> httpx.Response`
  - `app.storage.retry.raise_for_storage(response: httpx.Response, *, context: str) -> None`
  - `app.storage.retry.retry_after_seconds(response: httpx.Response, max_delay: float) -> float | None`

- [ ] **Step 1: Add the dependencies**

Run from `backend/`:

```bash
uv add httpx
uv remove --group dev httpx
```

`httpx` is already pinned `>=0.28.1` in the dev group; it becomes a runtime dependency because the adapters import it. Check that `pyproject.toml` now lists `"httpx>=0.28.1",` under `[project] dependencies` and no longer under `[dependency-groups] dev`.

- [ ] **Step 2: Write the failing test**

`backend/tests/storage/test_retry.py`:

```python
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
        max_attempts=2, base_delay=0.1, max_delay=1.0, retry_on_response=DRIVE_POLICY.retry_on_response
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
            raise_for_storage(
                await client.get(URL), context="Uploading srs--demo.md"
            )
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/storage/test_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.storage.retry'`.

- [ ] **Step 4: Add the two error classes**

In `backend/app/storage/base.py`, immediately after `class StorageNotFound(StorageError)`:

```python
class StorageAuthError(StorageError):
    """The storage credentials were rejected, expired or lack permission (spec 8.6)."""


class StorageAmbiguousPath(StorageError):
    """Two items share a name where the path interface assumes one (Google Drive, spec 8.3)."""
```

In the same file, give `HealthStatus` the field-level diagnosis slot. The default keeps every
existing caller and the local adapter unchanged:

```python
@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str = ""
    field: str | None = None  # the connection field at fault, for Test connection (spec 8.5)
```

In `backend/app/storage/__init__.py`, add `StorageAmbiguousPath` and `StorageAuthError` to both the import block and `__all__`, keeping both lists alphabetical.

- [ ] **Step 5: Write the shared HTTP client**

`backend/app/storage/http.py`:

```python
"""One httpx client for every cloud storage adapter.

A new client per request would mean a new TLS handshake per upload, so the client is created
once per process and closed by the application lifespan. Adapters accept an injected client so
tests can hand them an ``httpx.MockTransport`` and make no network call.
"""

from typing import Protocol

import httpx

TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)
LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=TIMEOUT, limits=LIMITS, follow_redirects=False)
    return _client


async def aclose_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class TokenProvider(Protocol):
    """Supplies a bearer token for one connection. Implementations cache and refresh it, and
    never log it or put it in an exception message."""

    async def token(self) -> str: ...
```

- [ ] **Step 6: Write the retry layer**

`backend/app/storage/retry.py`:

```python
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
    """Exponential backoff with full jitter; ``attempt`` is 1 for the first retry."""
    ceiling = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
    # Jitter spreads concurrent publishes; it is scheduling, not cryptography.
    return max(0.05, random.uniform(ceiling / 2, ceiling))  # noqa: S311


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
    raise StorageError(UNAVAILABLE.format(context=context))
```

- [ ] **Step 7: Close the client on shutdown**

In `backend/app/main.py`, add the import next to the other storage imports:

```python
from app.storage.http import aclose_client
```

and in the lifespan, between `cancel_background()` and `dispose_engine()`:

```python
        await cancel_background()  # requeued work must not outlive the engine
        await aclose_client()  # the shared storage HTTP client
        await dispose_engine()
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/storage/test_retry.py -v`
Expected: PASS, every test.

Run: `uv run ruff format . && uv run ruff check . && uv run mypy app && uv run pytest`
Expected: clean; the whole suite still passes.

- [ ] **Step 9: Commit**

```bash
git add app/storage/http.py app/storage/retry.py app/storage/base.py app/storage/__init__.py app/main.py pyproject.toml uv.lock tests/storage/test_retry.py
git commit -m "feat(storage): shared HTTP client and retry/backoff for cloud adapters

Retry-After aware backoff, Drive quota reasons, and storage errors whose
messages are built from the status code so provider bodies never reach a
user-visible message or a log line.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Google Drive path-to-id resolution and cache

**Needs live credentials:** no. The resolver is driven by `httpx.MockTransport` returning scripted `files.list` pages.

This is the sharpest impedance mismatch in the plan: `StorageBackend` is path-addressed and assumes one item per name, while Drive addresses items by id and happily holds two files called `srs--demo.md` in one folder. The resolver turns a path into an id, caches the mapping per connection, and refuses to guess.

**Files:**
- Create: `backend/app/storage/gdrive_paths.py`
- Test: `backend/tests/storage/test_gdrive_paths.py`

**Interfaces:**
- Consumes: `send_with_retry`, `DRIVE_POLICY`, `raise_for_storage` (Task 1); `TokenProvider` (Task 1); `StorageAmbiguousPath`, `StorageNotFound`, `normalize_path` (`app/storage/base.py`).
- Produces:
  - `app.storage.gdrive_paths.FOLDER_MIME: str`
  - `@dataclass(frozen=True) DriveEntry(id: str, name: str, mime_type: str)` with `is_folder: bool` property
  - `class FolderCache(ttl: float = 600.0, max_entries: int = 2000)` with `get(key: str) -> str | None`, `put(key: str, file_id: str) -> None`, `invalidate(key: str) -> None`, `invalidate_scope(scope: str) -> None`
  - `escape_query_value(value: str) -> str`
  - `class DriveResolver(client: httpx.AsyncClient, tokens: TokenProvider, drive_id: str, *, scope: str, cache: FolderCache, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep)` with
    `async find_child(parent_id: str, name: str) -> DriveEntry | None`,
    `async resolve(relative: str, *, root_id: str) -> DriveEntry`,
    `async resolve_optional(relative: str, *, root_id: str) -> DriveEntry | None`,
    `async ensure_folder(relative: str, *, root_id: str) -> str`,
    `async create_folder(parent_id: str, name: str) -> str`,
    `forget(relative: str) -> None`

- [ ] **Step 1: Write the failing test**

`backend/tests/storage/test_gdrive_paths.py`:

```python
"""Path -> file id for Google Drive. Drive has no paths and allows duplicate names, so this
module is where that mismatch is resolved; nothing else in the adapter speaks Drive's query
language."""

from collections.abc import Callable

import httpx
import pytest

from app.storage.base import StorageAmbiguousPath, StorageNotFound
from app.storage.gdrive_paths import (
    FOLDER_MIME,
    DriveResolver,
    FolderCache,
    escape_query_value,
)

DRIVE_ID = "shared-drive-test"
ROOT = "root-folder-id"


class FakeTokens:
    async def token(self) -> str:
        return "test-token"


class Drive:
    """A tiny in-memory Drive: folders and files by (parent, name), answering files.list."""

    def __init__(self) -> None:
        self.items: dict[str, list[tuple[str, str, str]]] = {}  # parent -> [(id, name, mime)]
        self.queries: list[str] = []
        self.created: list[tuple[str, str]] = []

    def add(self, parent: str, file_id: str, name: str, mime: str = FOLDER_MIME) -> None:
        self.items.setdefault(parent, []).append((file_id, name, mime))

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = request.read().decode()
            self.created.append((str(request.url), body))
            return httpx.Response(200, json={"id": "new-folder", "name": "x", "mimeType": FOLDER_MIME})
        query = request.url.params.get("q", "")
        self.queries.append(query)
        assert request.url.params["driveId"] == DRIVE_ID
        assert request.url.params["corpora"] == "drive"
        assert request.url.params["supportsAllDrives"] == "true"
        assert request.url.params["includeItemsFromAllDrives"] == "true"
        parent = query.split("'")[1] if "' in parents" in query else ""
        name = query.split("name = '")[1].split("'")[0] if "name = '" in query else ""
        matches = [
            {"id": i, "name": n, "mimeType": m}
            for i, n, m in self.items.get(parent, [])
            if n == name.replace("\\'", "'").replace("\\\\", "\\")
        ]
        return httpx.Response(200, json={"files": matches[:2], "incompleteSearch": False})


def _resolver(drive: Drive, cache: FolderCache | None = None, scope: str = "conn-1") -> DriveResolver:
    client = httpx.AsyncClient(transport=httpx.MockTransport(drive.handler))
    return DriveResolver(
        client,
        FakeTokens(),
        DRIVE_ID,
        scope=scope,
        cache=cache or FolderCache(),
        sleep=_no_sleep,
    )


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("plain", "plain"), ("it's", "it\\'s"), ("back\\slash", "back\\\\slash"), ("a'b\\c", "a\\'b\\\\c")],
)
def test_escape_query_value(raw: str, expected: str) -> None:
    """A name with a quote must not be able to change the meaning of the query."""
    assert escape_query_value(raw) == expected


async def test_resolves_a_nested_path_to_an_id() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    drive.add("f-req", "file-1", "srs--demo.md", "text/markdown")
    resolver = _resolver(drive)
    entry = await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    assert entry.id == "file-1"
    assert entry.is_folder is False


async def test_missing_segment_raises_not_found() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    resolver = _resolver(drive)
    with pytest.raises(StorageNotFound):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    assert await resolver.resolve_optional("02-requirements/srs--demo.md", root_id=ROOT) is None


async def test_duplicate_segment_is_an_error() -> None:
    """Two folders of the same name: refuse rather than write into whichever came back first."""
    drive = Drive()
    drive.add(ROOT, "f-a", "02-requirements")
    drive.add(ROOT, "f-b", "02-requirements")
    resolver = _resolver(drive)
    with pytest.raises(StorageAmbiguousPath, match="02-requirements"):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)


async def test_duplicate_leaf_file_is_an_error() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    drive.add("f-req", "file-1", "srs--demo.md", "text/markdown")
    drive.add("f-req", "file-2", "srs--demo.md", "text/markdown")
    resolver = _resolver(drive)
    with pytest.raises(StorageAmbiguousPath, match="srs--demo.md"):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)


async def test_folders_are_cached_but_leaf_files_are_not() -> None:
    drive = Drive()
    drive.add(ROOT, "f-req", "02-requirements")
    drive.add("f-req", "file-1", "srs--demo.md", "text/markdown")
    resolver = _resolver(drive)
    await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    first = len(drive.queries)
    await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
    # the folder came from the cache; only the file was looked up again, because a file can be
    # replaced or trashed between publishes while a folder stays put
    assert len(drive.queries) == first + 1


async def test_cached_id_that_no_longer_resolves_is_refetched() -> None:
    """A folder someone trashed or renamed in Drive must not strand us on a stale id."""
    drive = Drive()
    drive.add(ROOT, "f-old", "02-requirements")
    cache = FolderCache()
    resolver = _resolver(drive, cache)
    await resolver.ensure_folder("02-requirements", root_id=ROOT)
    drive.items[ROOT] = [("f-new", "02-requirements", FOLDER_MIME)]
    resolver.forget("02-requirements")
    assert await resolver.ensure_folder("02-requirements", root_id=ROOT) == "f-new"


async def test_cache_is_scoped_per_connection() -> None:
    """Two connections are two customers' libraries; one must never answer for the other."""
    cache = FolderCache()
    drive_a, drive_b = Drive(), Drive()
    drive_a.add(ROOT, "a-req", "02-requirements")
    drive_b.add(ROOT, "b-req", "02-requirements")
    assert await _resolver(drive_a, cache, scope="conn-a").ensure_folder(
        "02-requirements", root_id=ROOT
    ) == "a-req"
    assert await _resolver(drive_b, cache, scope="conn-b").ensure_folder(
        "02-requirements", root_id=ROOT
    ) == "b-req"


async def test_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr("app.storage.gdrive_paths.monotonic", lambda: now[0])
    cache = FolderCache(ttl=60.0)
    cache.put("k", "v")
    assert cache.get("k") == "v"
    now[0] += 61.0
    assert cache.get("k") is None


def test_cache_evicts_when_full() -> None:
    cache = FolderCache(max_entries=2)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.put("c", "3")
    assert cache.get("c") == "3"
    assert sum(cache.get(key) is not None for key in ("a", "b", "c")) <= 2


async def test_ensure_folder_creates_missing_segments_only() -> None:
    drive = Drive()
    drive.add(ROOT, "f-test", "05-testing")
    resolver = _resolver(drive)
    await resolver.ensure_folder("05-testing/test-reports", root_id=ROOT)
    assert len(drive.created) == 1  # 05-testing existed; only test-reports was created
    url, body = drive.created[0]
    assert "supportsAllDrives=true" in url
    assert '"parents": ["f-test"]' in body.replace("'", '"') or '"f-test"' in body


async def test_resolver_never_leaves_the_root() -> None:
    """Every unsafe path is refused by normalize_path before a request is built."""
    drive = Drive()
    resolver = _resolver(drive)
    for bad in ("../escape.md", "/abs.md", "a/../../b", ".versions/x", "a\\b.md", ""):
        with pytest.raises(Exception):  # noqa: B017 - StoragePathError, asserted below
            await resolver.resolve(bad, root_id=ROOT)
    assert drive.queries == []


async def test_a_file_where_a_folder_is_expected_is_not_found() -> None:
    drive = Drive()
    drive.add(ROOT, "f-1", "02-requirements", "text/markdown")  # a file, not a folder
    resolver = _resolver(drive)
    with pytest.raises(StorageNotFound):
        await resolver.resolve("02-requirements/srs--demo.md", root_id=ROOT)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/storage/test_gdrive_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.storage.gdrive_paths'`.

- [ ] **Step 3: Write the resolver**

`backend/app/storage/gdrive_paths.py`:

```python
"""Path to file id for Google Drive (spec 8.3).

``StorageBackend`` is path-addressed and assumes one item per name. Drive addresses items by id
and allows two items with the same name in one folder. This module resolves each segment, caches
folder ids per connection, and raises ``StorageAmbiguousPath`` on a duplicate instead of picking
one, so a divergence is reported rather than silently written to the wrong item.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic

import httpx

from app.storage.base import StorageAmbiguousPath, StorageNotFound, normalize_path
from app.storage.http import TokenProvider
from app.storage.retry import DRIVE_POLICY, raise_for_storage, send_with_retry

FOLDER_MIME = "application/vnd.google-apps.folder"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
LIST_FIELDS = "files(id,name,mimeType),incompleteSearch"


def escape_query_value(value: str) -> str:
    """Escape a name for a Drive query literal: backslash first, then the quote."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


@dataclass(frozen=True)
class DriveEntry:
    id: str
    name: str
    mime_type: str

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME


class FolderCache:
    """Folder ids by scoped path key, with a TTL and a size cap.

    Keys are prefixed with the connection's scope, so one customer's Shared Drive can never
    answer a lookup for another's. Entries are hints: a miss costs one request, and a stale hit
    is detected by the caller and dropped with ``invalidate``.
    """

    def __init__(self, ttl: float = 600.0, max_entries: int = 2000) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._entries: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        found = self._entries.get(key)
        if found is None:
            return None
        file_id, expires = found
        if expires <= monotonic():
            del self._entries[key]
            return None
        return file_id

    def put(self, key: str, file_id: str) -> None:
        if len(self._entries) >= self._max:
            self._entries.clear()  # a cold cache costs one request per folder; keep it simple
        self._entries[key] = (file_id, monotonic() + self._ttl)

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def invalidate_scope(self, scope: str) -> None:
        for key in [k for k in self._entries if k.startswith(f"{scope}:")]:
            del self._entries[key]


class DriveResolver:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tokens: TokenProvider,
        drive_id: str,
        *,
        scope: str,
        cache: FolderCache,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._tokens = tokens
        self._drive_id = drive_id
        self._scope = scope
        self._cache = cache
        self._sleep = sleep

    def _key(self, relative: str) -> str:
        return f"{self._scope}:{relative}"

    def forget(self, relative: str) -> None:
        self._cache.invalidate(self._key(relative))

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._tokens.token()}"}

    async def find_child(self, parent_id: str, name: str) -> DriveEntry | None:
        """The single child of ``parent_id`` called ``name``; None when there is none."""
        params = {
            "q": f"name = '{escape_query_value(name)}' and '{parent_id}' in parents "
            "and trashed = false",
            "driveId": self._drive_id,
            "corpora": "drive",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
            "pageSize": "2",  # two is enough to prove a duplicate
            "fields": LIST_FIELDS,
        }
        headers = await self._headers()
        response = await send_with_retry(
            self._client,
            lambda: self._client.build_request("GET", FILES_URL, params=params, headers=headers),
            policy=DRIVE_POLICY,
            context=f"Looking up {name!r} in Google Drive",
            sleep=self._sleep,
        )
        raise_for_storage(response, context=f"Looking up {name!r} in Google Drive")
        files = response.json().get("files", [])
        if len(files) > 1:
            raise StorageAmbiguousPath(
                f"Google Drive holds more than one item named {name!r} in the same folder. "
                "Rename or remove the duplicate in Drive, then try again."
            )
        if not files:
            return None
        found = files[0]
        return DriveEntry(id=found["id"], name=found["name"], mime_type=found["mimeType"])

    async def _folder_id(self, relative: str, parent_id: str, name: str) -> str | None:
        cached = self._cache.get(self._key(relative))
        if cached is not None:
            return cached
        entry = await self.find_child(parent_id, name)
        if entry is None or not entry.is_folder:
            return None
        self._cache.put(self._key(relative), entry.id)
        return entry.id

    async def resolve_optional(self, relative: str, *, root_id: str) -> DriveEntry | None:
        parts = normalize_path(relative).split("/")
        parent_id = root_id
        walked: list[str] = []
        for name in parts[:-1]:
            walked.append(name)
            folder_id = await self._folder_id("/".join(walked), parent_id, name)
            if folder_id is None:
                return None
            parent_id = folder_id
        return await self.find_child(parent_id, parts[-1])

    async def resolve(self, relative: str, *, root_id: str) -> DriveEntry:
        entry = await self.resolve_optional(relative, root_id=root_id)
        if entry is None:
            raise StorageNotFound(f"File not found: {normalize_path(relative)}")
        return entry

    async def create_folder(self, parent_id: str, name: str) -> str:
        headers = await self._headers()
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        response = await send_with_retry(
            self._client,
            lambda: self._client.build_request(
                "POST",
                FILES_URL,
                params={"supportsAllDrives": "true", "fields": "id"},
                json=body,
                headers=headers,
            ),
            policy=DRIVE_POLICY,
            context=f"Creating folder {name!r} in Google Drive",
            sleep=self._sleep,
        )
        raise_for_storage(response, context=f"Creating folder {name!r} in Google Drive")
        created: str = response.json()["id"]
        return created

    async def ensure_folder(self, relative: str, *, root_id: str) -> str:
        """Resolve ``relative`` to a folder id, creating the segments that do not exist."""
        parent_id = root_id
        walked: list[str] = []
        for name in normalize_path(relative).split("/"):
            walked.append(name)
            key = "/".join(walked)
            folder_id = await self._folder_id(key, parent_id, name)
            if folder_id is None:
                folder_id = await self.create_folder(parent_id, name)
                self._cache.put(self._key(key), folder_id)
            parent_id = folder_id
        return parent_id
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/storage/test_gdrive_paths.py -v`
Expected: PASS, every test.

Run: `uv run ruff format . && uv run ruff check . && uv run mypy app`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add app/storage/gdrive_paths.py tests/storage/test_gdrive_paths.py
git commit -m "feat(storage): resolve Google Drive paths to ids with a per-connection cache

A duplicate name at any path segment is a storage error rather than a
guess, and cached folder ids are scoped per connection so one customer's
Shared Drive never answers another's lookup.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Google Drive adapter

**Needs live credentials:** no for the adapter logic (scripted with `httpx.MockTransport` and a fake token provider); the `ServiceAccountTokenProvider` is exercised offline with a monkeypatched `google.oauth2.service_account`, and its real round trip is proven in Task 9.

**Files:**
- Create: `backend/app/storage/gdrive.py`
- Modify: `backend/pyproject.toml` (add `google-auth`)
- Test: `backend/tests/storage/test_gdrive.py`

**Interfaces:**
- Consumes: Task 1 (`get_client`, `TokenProvider`, `send_with_retry`, `DRIVE_POLICY`, `raise_for_storage`), Task 2 (`DriveResolver`, `FolderCache`, `FOLDER_MIME`, `DriveEntry`), `app/storage/base.py` (`HealthStatus`, `StoredFile`, `StoredVersion`, `StorageNotFound`, `StorageAuthError`, `StorageError`, `normalize_path`).
- Produces:
  - `app.storage.gdrive.ServiceAccountTokenProvider(key_json: str)` implementing `TokenProvider`
  - `app.storage.gdrive.GoogleDriveBackend(drive_id: str, root_path: str, tokens: TokenProvider, *, scope: str, client: httpx.AsyncClient | None = None, cache: FolderCache | None = None, sleep=asyncio.sleep)` implementing `StorageBackend`
  - `app.storage.gdrive.SHARED_CACHE: FolderCache`
  - `app.storage.gdrive.KEEP_FOREVER_LIMIT: int = 200`, `KEEP_FOREVER_EXEMPT: tuple[str, ...] = ("project.yaml", "_reports/")`
  - `app.storage.gdrive.validate_service_account_key(key_json: str) -> str` (raises `StorageError`; returns the key unchanged)

- [ ] **Step 1: Add the dependency**

Run from `backend/`: `uv add google-auth`

Then add to `[[tool.mypy.overrides]]` in `backend/pyproject.toml`, extending the existing override list:

```toml
[[tool.mypy.overrides]]
module = ["pyotp", "langdetect", "langdetect.*", "google.auth.*", "google.oauth2.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: Write the failing test**

`backend/tests/storage/test_gdrive.py`:

```python
"""Google Drive adapter: uploads, revisions, keepForever policy and the staged health probe.
Every test runs against a scripted transport; nothing here reaches the network."""

import json

import httpx
import pytest

from app.storage.base import (
    HealthStatus,
    StorageAuthError,
    StorageError,
    StorageNotFound,
    StoragePathError,
)
from app.storage.gdrive import (
    KEEP_FOREVER_LIMIT,
    GoogleDriveBackend,
    validate_service_account_key,
)
from app.storage.gdrive_paths import FOLDER_MIME, FolderCache

DRIVE_ID = "shared-drive-test"
ROOT_ID = "drive-root-id"
PATH = "02-requirements/srs--customer-portal.docx"

# A synthetic key body, assembled at runtime so the repository's gitleaks hook does not
# flag a fixture. It is not a key and cannot sign anything.
FAKE_PEM = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END " + "PRIVATE KEY-----\n"


class FakeTokens:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def token(self) -> str:
        if self.fail:
            raise StorageAuthError(
                "The Google service-account key was rejected. Paste the key file again."
            )
        return "test-token"


class Script:
    """Records every request and replies from a list of (predicate, response) rules."""

    def __init__(self) -> None:
        self.rules: list[tuple[object, httpx.Response]] = []
        self.requests: list[httpx.Request] = []

    def on(self, match: str, response: httpx.Response) -> "Script":
        self.rules.append((match, response))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        target = f"{request.method} {request.url}"
        for match, response in self.rules:
            if isinstance(match, str) and match in target:
                return response
        return httpx.Response(404, json={"error": {"code": 404, "message": "not found"}})


async def _no_sleep(_seconds: float) -> None:
    return None


def _backend(script: Script, tokens: FakeTokens | None = None, root: str = "") -> GoogleDriveBackend:
    return GoogleDriveBackend(
        DRIVE_ID,
        root,
        tokens or FakeTokens(),
        scope="conn-test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(script.handler)),
        cache=FolderCache(),
        sleep=_no_sleep,
    )


def _list(files: list[dict[str, str]]) -> httpx.Response:
    return httpx.Response(200, json={"files": files, "incompleteSearch": False})


def _folder(file_id: str, name: str) -> dict[str, str]:
    return {"id": file_id, "name": name, "mimeType": FOLDER_MIME}


# -- configuration and keys ----------------------------------------------------------------


def test_validate_service_account_key_accepts_a_well_formed_key() -> None:
    key = json.dumps(
        {
            "type": "service_account",
            "project_id": "qc-agent-test",
            "private_key_id": "0" * 40,
            "private_key": FAKE_PEM,
            "client_email": "qc-agent@qc-agent-test.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    assert validate_service_account_key(key) == key


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("not json at all", "valid JSON"),
        (json.dumps({"type": "authorized_user"}), "service account"),
        (json.dumps({"type": "service_account"}), "client_email"),
    ],
)
def test_validate_service_account_key_rejects_bad_keys(key: str, expected: str) -> None:
    with pytest.raises(StorageError, match=expected):
        validate_service_account_key(key)


def test_validate_service_account_key_error_never_echoes_the_key() -> None:
    key = json.dumps({"type": "service_account", "private_key": "SENSITIVE-MATERIAL"})
    with pytest.raises(StorageError) as caught:
        validate_service_account_key(key)
    assert "SENSITIVE-MATERIAL" not in str(caught.value)


# -- reads and writes ----------------------------------------------------------------------


async def test_put_file_creates_folders_and_uploads_multipart() -> None:
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on("POST https://www.googleapis.com/drive/v3/files?", httpx.Response(200, json={"id": "f-1"}))
    )
    backend = _backend(script)
    stored = await backend.put_file(PATH, b"v1", "application/octet-stream")
    assert stored.item_id and stored.version_id
    uploads = [r for r in script.requests if "/upload/drive/v3/files" in str(r.url)]
    assert len(uploads) == 1
    assert "uploadType=multipart" in str(uploads[0].url)
    assert all("supportsAllDrives=true" in str(r.url) for r in script.requests if r.method != "PATCH")


async def test_every_request_stays_inside_the_configured_drive() -> None:
    """One connection is one customer's Shared Drive; nothing may address another."""
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on("POST https://www.googleapis.com/drive/v3/files?", httpx.Response(200, json={"id": "f-1"}))
    )
    backend = _backend(script)
    await backend.put_file(PATH, b"v1", "text/plain")
    for request in script.requests:
        drive_param = request.url.params.get("driveId")
        assert drive_param in (None, DRIVE_ID)
        assert "drives/" not in str(request.url) or f"drives/{DRIVE_ID}" in str(request.url)


async def test_large_files_use_a_resumable_upload() -> None:
    session_url = "https://www.googleapis.com/upload/drive/v3/files?upload_id=abc"
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on("POST https://www.googleapis.com/drive/v3/files?", httpx.Response(200, json={"id": "f-1"}))
        .on("uploadType=resumable", httpx.Response(200, headers={"Location": session_url}))
        .on(session_url, httpx.Response(200, json={"id": "f-1", "headRevisionId": "r2"}))
    )
    backend = _backend(script)
    await backend.put_file(PATH, b"x" * (6 * 1024 * 1024), "application/octet-stream")
    assert any("uploadType=resumable" in str(r.url) for r in script.requests)


async def test_a_new_version_updates_the_existing_file_id() -> None:
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([_folder("f-req", "02-requirements")]))
    )
    script.rules.insert(
        0,
        (
            "name%20%3D%20%27srs--customer-portal.docx%27",
            _list([{"id": "file-1", "name": "srs--customer-portal.docx", "mimeType": "application/octet-stream"}]),
        ),
    )
    script.on("PATCH", httpx.Response(200, json={"id": "file-1", "headRevisionId": "r2"}))
    script.on("revisions/r2", httpx.Response(200, json={"id": "r2", "keepForever": True}))
    backend = _backend(script)
    stored = await backend.put_file(PATH, b"v2", "application/octet-stream")
    assert stored.item_id == "file-1"
    patches = [r for r in script.requests if r.method == "PATCH" and "/upload/" in str(r.url)]
    assert len(patches) == 1 and "file-1" in str(patches[0].url)


async def test_keep_forever_is_not_set_on_reports_or_project_yaml() -> None:
    """These files are rewritten on every publish; the keepForever cap belongs to documents."""
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on("POST https://www.googleapis.com/drive/v3/files?", httpx.Response(200, json={"id": "f-1"}))
    )
    backend = _backend(script)
    await backend.put_file("_reports/gap-report.md", b"# gaps", "text/markdown")
    await backend.put_file("project.yaml", b"name: demo", "text/yaml")
    assert not [r for r in script.requests if "/revisions/" in str(r.url)]


async def test_versions_are_listed_oldest_first() -> None:
    revisions = {
        "revisions": [
            {"id": "r1", "size": "2", "modifiedTime": "2026-10-01T10:00:00.000Z"},
            {"id": "r2", "size": "2", "modifiedTime": "2026-10-02T10:00:00.000Z"},
        ]
    }
    script = (
        Script()
        .on("name%20%3D%20%2702-requirements%27", _list([_folder("f-req", "02-requirements")]))
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([{"id": "file-1", "name": "srs--customer-portal.docx", "mimeType": "application/octet-stream"}]))
        .on("/revisions?", httpx.Response(200, json=revisions))
    )
    backend = _backend(script)
    versions = await backend.list_versions(PATH)
    assert [v.version_id for v in versions] == ["r1", "r2"]
    assert versions[0].modified_at < versions[1].modified_at
    assert all(v.size == 2 for v in versions)


async def test_missing_file_raises_not_found() -> None:
    script = Script().on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
    backend = _backend(script)
    with pytest.raises(StorageNotFound):
        await backend.get_file(PATH)
    assert await backend.exists(PATH) is False


async def test_unsafe_paths_make_no_request() -> None:
    script = Script()
    backend = _backend(script)
    for bad in ("../escape.md", "/abs.md", ".versions/x", "a\\b.md", ""):
        with pytest.raises(StoragePathError):
            await backend.put_file(bad, b"x", "text/plain")
    assert script.requests == []


async def test_move_to_trash_sets_trashed() -> None:
    script = (
        Script()
        .on("name%20%3D%20%2702-requirements%27", _list([_folder("f-req", "02-requirements")]))
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([{"id": "file-1", "name": "srs--customer-portal.docx", "mimeType": "application/octet-stream"}]))
        .on("PATCH", httpx.Response(200, json={"id": "file-1"}))
    )
    backend = _backend(script)
    await backend.move_to_trash(PATH)
    patch = [r for r in script.requests if r.method == "PATCH"][-1]
    assert b'"trashed": true' in patch.read().replace(b"'", b'"')


# -- health -------------------------------------------------------------------------------


async def test_health_diagnoses_each_failure_stage() -> None:
    """Test connection names the field at fault, so a wrong id is caught here, not at upload."""
    rejected = _backend(Script(), FakeTokens(fail=True))
    status = await rejected.health()
    assert status.ok is False and status.field == "secret"
    assert "service-account key" in status.detail

    missing = _backend(Script().on(f"drives/{DRIVE_ID}", httpx.Response(404, json={})))
    status = await missing.health()
    assert status.ok is False and status.field == "drive_id"
    assert "Shared Drive" in status.detail and "not found" in status.detail

    forbidden = _backend(Script().on(f"drives/{DRIVE_ID}", httpx.Response(403, json={})))
    status = await forbidden.health()
    assert status.ok is False and status.field == "drive_id"
    assert "Content manager" in status.detail  # the membership grant IT must make

    read_only = _backend(
        Script().on(
            f"drives/{DRIVE_ID}",
            httpx.Response(
                200,
                json={"id": DRIVE_ID, "name": "Customer", "capabilities": {"canAddChildren": False}},
            ),
        )
    )
    status = await read_only.health()
    assert status.ok is False and status.field == "drive_id"
    assert "Content manager" in status.detail


async def test_health_is_ok_when_the_drive_is_writable() -> None:
    script = Script().on(
        f"drives/{DRIVE_ID}",
        httpx.Response(
            200, json={"id": DRIVE_ID, "name": "Customer", "capabilities": {"canAddChildren": True}}
        ),
    )
    status = await _backend(script).health()
    assert status == HealthStatus(ok=True, detail="ok")


async def test_health_reports_a_file_at_the_keep_forever_limit() -> None:
    script = Script().on(
        f"drives/{DRIVE_ID}",
        httpx.Response(
            200, json={"id": DRIVE_ID, "name": "Customer", "capabilities": {"canAddChildren": True}}
        ),
    )
    backend = _backend(script)
    backend.note_keep_forever_limit(PATH, KEEP_FOREVER_LIMIT)
    status = await backend.health()
    assert status.ok is False
    assert "keepForever" in status.detail and PATH in status.detail


async def test_health_message_never_contains_a_token_or_a_provider_body() -> None:
    script = Script().on(
        f"drives/{DRIVE_ID}", httpx.Response(500, text="Bearer test-token leaked by the provider")
    )
    status = await _backend(script).health()
    assert status.ok is False
    assert "test-token" not in status.detail and "Bearer" not in status.detail
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/storage/test_gdrive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.storage.gdrive'`.

- [ ] **Step 4: Write the adapter**

`backend/app/storage/gdrive.py`:

```python
"""Google Drive adapter (spec 8.3).

Drive API v3 over the shared httpx client. A service account authenticates; it must have been
added to the Shared Drive as Content manager by a Google Workspace administrator — no field in
the application can grant that. ``supportsAllDrives=true`` goes on every call, a new version is
``files.update`` on the existing file id, and published versions get ``keepForever`` because
Drive prunes revisions otherwise.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.storage.base import (
    HealthStatus,
    StorageAuthError,
    StorageError,
    StorageNotFound,
    StoredFile,
    StoredVersion,
    normalize_path,
)
from app.storage.gdrive_paths import DriveResolver, FolderCache, TokenProvider
from app.storage.http import get_client
from app.storage.retry import DRIVE_POLICY, raise_for_storage, send_with_retry

logger = logging.getLogger(__name__)

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SCOPES = ["https://www.googleapis.com/auth/drive"]
MULTIPART_LIMIT = 5 * 1024 * 1024
KEEP_FOREVER_LIMIT = 200
KEEP_FOREVER_EXEMPT = ("project.yaml", "_reports/")
SHARED_CACHE = FolderCache()

NOT_A_MEMBER = (
    "The service account is not a member of this Shared Drive, or has no permission to add "
    "files. A Google Workspace administrator must add it as Content manager."
)
DRIVE_NOT_FOUND = (
    "Shared Drive not found. Check the Shared Drive id, and that the service account has been "
    "added to that drive."
)
KEY_REJECTED = (
    "The Google service-account key was rejected or has been revoked. Paste a current key file."
)


def validate_service_account_key(key_json: str) -> str:
    """Check the shape of a service-account key without ever echoing any of it."""
    try:
        parsed = json.loads(key_json)
    except ValueError as exc:
        raise StorageError("The service-account key must be valid JSON.") from exc
    if not isinstance(parsed, dict) or parsed.get("type") != "service_account":
        raise StorageError("This is not a service account key (its \"type\" must be \"service_account\").")
    missing = [f for f in ("client_email", "private_key", "token_uri") if not parsed.get(f)]
    if missing:
        raise StorageError(f"The service-account key is missing: {', '.join(missing)}.")
    return key_json


class ServiceAccountTokenProvider:
    """Mints and caches an access token from a service-account key.

    ``google-auth`` is synchronous, so refreshes run in a worker thread. The key and the token
    exist only inside this object; neither is logged or put in an exception message.
    """

    def __init__(self, key_json: str) -> None:
        self._key_json = validate_service_account_key(key_json)
        self._credentials: Any | None = None
        self._lock = asyncio.Lock()

    def _refresh(self) -> str:
        from google.auth.transport.requests import Request  # imported late: optional at import
        from google.oauth2 import service_account

        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_info(
                json.loads(self._key_json), scopes=SCOPES
            )
        self._credentials.refresh(Request())
        token: str = self._credentials.token
        return token

    async def token(self) -> str:
        async with self._lock:
            credentials = self._credentials
            if credentials is not None and credentials.valid:
                current: str = credentials.token
                return current
            try:
                return await asyncio.to_thread(self._refresh)
            except StorageError:
                raise
            except Exception as exc:  # noqa: BLE001 - google-auth raises many types
                logger.warning("Google service-account token refresh failed: %s", type(exc).__name__)
                raise StorageAuthError(KEY_REJECTED) from None


class GoogleDriveBackend:
    def __init__(
        self,
        drive_id: str,
        root_path: str,
        tokens: TokenProvider,
        *,
        scope: str,
        client: httpx.AsyncClient | None = None,
        cache: FolderCache | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._drive_id = drive_id
        self._root_path = root_path.strip("/")
        self._tokens = tokens
        self._client = client or get_client()
        self._sleep = sleep
        self._scope = f"{scope}:{self._root_path}"
        self._resolver = DriveResolver(
            self._client,
            tokens,
            drive_id,
            scope=self._scope,
            cache=cache or SHARED_CACHE,
            sleep=sleep,
        )
        self._root_id: str | None = None
        self._at_limit: dict[str, int] = {}

    # -- plumbing --------------------------------------------------------------------------

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._tokens.token()}"}

    async def _send(
        self, method: str, url: str, *, context: str, **kwargs: Any
    ) -> httpx.Response:
        headers = {**(await self._headers()), **kwargs.pop("headers", {})}
        response = await send_with_retry(
            self._client,
            lambda: self._client.build_request(method, url, headers=headers, **kwargs),
            policy=DRIVE_POLICY,
            context=context,
            sleep=self._sleep,
        )
        return response

    async def _root(self, *, create: bool) -> str:
        if self._root_id is not None:
            return self._root_id
        if not self._root_path:
            self._root_id = self._drive_id  # a Shared Drive's root folder id is the drive id
            return self._root_id
        if create:
            self._root_id = await self._resolver.ensure_folder(
                self._root_path, root_id=self._drive_id
            )
        else:
            entry = await self._resolver.resolve_optional(
                self._root_path, root_id=self._drive_id
            )
            if entry is None or not entry.is_folder:
                raise StorageNotFound(f"Project folder not found: {self._root_path}")
            self._root_id = entry.id
        return self._root_id

    @staticmethod
    def _keep_forever(path: str) -> bool:
        return not any(path == e or path.startswith(e) for e in KEEP_FOREVER_EXEMPT)

    def note_keep_forever_limit(self, path: str, count: int) -> None:
        """Remember that ``path`` has reached Drive's keepForever cap, for ``health()``.

        Best effort and in-process only: it is a warning for an administrator, not a record.
        """
        self._at_limit[path] = count

    # -- StorageBackend --------------------------------------------------------------------

    async def ensure_folder(self, path: str) -> None:
        relative = normalize_path(path)
        await self._resolver.ensure_folder(relative, root_id=await self._root(create=True))

    async def put_file(self, path: str, data: bytes, content_type: str) -> StoredFile:
        relative = normalize_path(path)
        root_id = await self._root(create=True)
        folder, _, name = relative.rpartition("/")
        parent_id = (
            await self._resolver.ensure_folder(folder, root_id=root_id) if folder else root_id
        )
        existing = await self._resolver.find_child(parent_id, name)
        context = f"Uploading {relative}"
        if len(data) <= MULTIPART_LIMIT:
            file = await self._upload_multipart(existing, parent_id, name, data, content_type, context)
        else:
            file = await self._upload_resumable(existing, parent_id, name, data, content_type, context)
        version_id = str(file.get("headRevisionId") or "")
        if self._keep_forever(relative) and version_id:
            await self._mark_keep_forever(file["id"], version_id, relative, context)
        return StoredFile(
            item_id=str(file["id"]), version_id=version_id, web_url=file.get("webViewLink")
        )

    async def _upload_multipart(
        self,
        existing: Any,
        parent_id: str,
        name: str,
        data: bytes,
        content_type: str,
        context: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"name": name}
        if existing is None:
            metadata["parents"] = [parent_id]
        boundary = "qc-agent-boundary"
        body = b"".join(
            [
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
                json.dumps(metadata).encode(),
                f"\r\n--{boundary}\r\nContent-Type: {content_type}\r\n\r\n".encode(),
                data,
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        url = UPLOAD if existing is None else f"{UPLOAD}/{existing.id}"
        response = await self._send(
            "POST" if existing is None else "PATCH",
            url,
            context=context,
            params={
                "uploadType": "multipart",
                "supportsAllDrives": "true",
                "fields": "id,headRevisionId,webViewLink",
            },
            content=body,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        )
        raise_for_storage(response, context=context)
        result: dict[str, Any] = response.json()
        return result

    async def _upload_resumable(
        self,
        existing: Any,
        parent_id: str,
        name: str,
        data: bytes,
        content_type: str,
        context: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"name": name}
        if existing is None:
            metadata["parents"] = [parent_id]
        start = await self._send(
            "POST" if existing is None else "PATCH",
            UPLOAD if existing is None else f"{UPLOAD}/{existing.id}",
            context=context,
            params={
                "uploadType": "resumable",
                "supportsAllDrives": "true",
                "fields": "id,headRevisionId,webViewLink",
            },
            json=metadata,
            headers={"X-Upload-Content-Type": content_type},
        )
        raise_for_storage(start, context=context)
        session_url = start.headers.get("Location")
        if not session_url:
            raise StorageError(f"{context} failed: Google Drive did not start an upload session.")
        upload = await send_with_retry(
            self._client,
            lambda: self._client.build_request(
                "PUT",
                session_url,
                content=data,
                headers={
                    "Content-Type": content_type,
                    "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}",
                },
            ),
            policy=DRIVE_POLICY,
            context=context,
            sleep=self._sleep,
        )
        raise_for_storage(upload, context=context)
        result: dict[str, Any] = upload.json()
        return result

    async def _mark_keep_forever(
        self, file_id: str, revision_id: str, relative: str, context: str
    ) -> None:
        response = await self._send(
            "PATCH",
            f"{API}/files/{file_id}/revisions/{revision_id}",
            context=context,
            params={"fields": "id,keepForever"},
            json={"keepForever": True},
        )
        if response.status_code == 403:
            # Drive caps keepForever revisions per file. The upload itself succeeded; only the
            # retention of this revision is lost, so the publish is not failed for it.
            self.note_keep_forever_limit(relative, KEEP_FOREVER_LIMIT)
            logger.warning("keepForever refused for a file at Drive's limit: %s", relative)
            return
        raise_for_storage(response, context=context)

    async def get_file(self, path: str) -> bytes:
        relative = normalize_path(path)
        entry = await self._resolver.resolve(relative, root_id=await self._root(create=False))
        context = f"Downloading {relative}"
        response = await self._send(
            "GET",
            f"{API}/files/{entry.id}",
            context=context,
            params={"alt": "media", "supportsAllDrives": "true"},
        )
        raise_for_storage(response, context=context)
        return response.content

    async def exists(self, path: str) -> bool:
        relative = normalize_path(path)
        try:
            root_id = await self._root(create=False)
        except StorageNotFound:
            return False
        entry = await self._resolver.resolve_optional(relative, root_id=root_id)
        return entry is not None and not entry.is_folder

    async def list_versions(self, path: str) -> list[StoredVersion]:
        relative = normalize_path(path)
        entry = await self._resolver.resolve(relative, root_id=await self._root(create=False))
        context = f"Listing versions of {relative}"
        response = await self._send(
            "GET",
            f"{API}/files/{entry.id}/revisions",
            context=context,
            params={
                "fields": "revisions(id,size,modifiedTime,keepForever)",
                "pageSize": "1000",
            },
        )
        raise_for_storage(response, context=context)
        revisions = response.json().get("revisions", [])
        kept = sum(1 for r in revisions if r.get("keepForever"))
        if kept >= KEEP_FOREVER_LIMIT:
            self.note_keep_forever_limit(relative, kept)
        return [
            StoredVersion(
                version_id=str(r["id"]),
                size=int(r.get("size", 0)),
                modified_at=datetime.fromisoformat(r["modifiedTime"].replace("Z", "+00:00")),
            )
            for r in revisions
        ]

    async def get_version(self, path: str, version_id: str) -> bytes:
        relative = normalize_path(path)
        entry = await self._resolver.resolve(relative, root_id=await self._root(create=False))
        context = f"Downloading a version of {relative}"
        response = await self._send(
            "GET",
            f"{API}/files/{entry.id}/revisions/{version_id}",
            context=context,
            params={"alt": "media"},
        )
        if response.status_code == 404:
            raise StorageNotFound(f"Version not found: {version_id}")
        raise_for_storage(response, context=context)
        return response.content

    async def move_to_trash(self, path: str) -> None:
        relative = normalize_path(path)
        entry = await self._resolver.resolve(relative, root_id=await self._root(create=False))
        context = f"Removing {relative}"
        response = await self._send(
            "PATCH",
            f"{API}/files/{entry.id}",
            context=context,
            params={"supportsAllDrives": "true", "fields": "id"},
            json={"trashed": True},
        )
        raise_for_storage(response, context=context)
        self._resolver.forget(relative)

    async def health(self) -> HealthStatus:
        """Staged probe: credentials, then the Shared Drive, then write permission (spec 8.5).

        Each stage names the field or the grant at fault, so a wrong value is caught on Test
        connection rather than at the first upload.
        """
        try:
            await self._tokens.token()
        except StorageAuthError as exc:
            return HealthStatus(ok=False, detail=str(exc), field="secret")
        except StorageError as exc:
            return HealthStatus(ok=False, detail=str(exc), field="secret")
        try:
            response = await self._send(
                "GET",
                f"{API}/drives/{self._drive_id}",
                context="Checking the Shared Drive",
                params={"supportsAllDrives": "true", "fields": "id,name,capabilities"},
            )
        except StorageAuthError:
            return HealthStatus(ok=False, detail=NOT_A_MEMBER, field="drive_id")
        except StorageError as exc:
            return HealthStatus(ok=False, detail=str(exc), field="drive_id")
        if response.status_code == 404:
            return HealthStatus(ok=False, detail=DRIVE_NOT_FOUND, field="drive_id")
        if response.status_code == 403:
            return HealthStatus(ok=False, detail=NOT_A_MEMBER, field="drive_id")
        if response.status_code >= 400:
            return HealthStatus(
                ok=False,
                detail=f"Checking the Shared Drive failed ({response.status_code}).",
                field="drive_id",
            )
        capabilities = response.json().get("capabilities", {})
        if not capabilities.get("canAddChildren"):
            return HealthStatus(ok=False, detail=NOT_A_MEMBER, field="drive_id")
        if self._at_limit:
            paths = ", ".join(sorted(self._at_limit))
            return HealthStatus(
                ok=False,
                detail=(
                    "Google Drive's keepForever limit has been reached for: "
                    f"{paths}. Older versions of these files may be pruned by Drive."
                ),
            )
        return HealthStatus(ok=True, detail="ok")
```

Add the re-export the adapter imports from `gdrive_paths` by appending to `backend/app/storage/gdrive_paths.py`:

```python
__all__ = [
    "FOLDER_MIME",
    "DriveEntry",
    "DriveResolver",
    "FolderCache",
    "TokenProvider",
    "escape_query_value",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/storage/test_gdrive.py tests/storage/test_gdrive_paths.py -v`
Expected: PASS, every test.

Run: `uv run ruff format . && uv run ruff check . && uv run mypy app && uv run pytest`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add app/storage/gdrive.py app/storage/gdrive_paths.py pyproject.toml uv.lock tests/storage/test_gdrive.py
git commit -m "feat(storage): Google Drive adapter on Drive API v3

Service-account credentials, supportsAllDrives everywhere, multipart and
resumable uploads, new versions through files.update, keepForever on
document versions but not on project.yaml or _reports, and a staged
health probe that names the field or the grant at fault.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: SharePoint adapter

**Needs live credentials:** no for the adapter logic (scripted transport, fake token provider); `GraphTokenProvider` is exercised with a fake `msal` application object, and its real round trip is proven in Task 9.

**Files:**
- Create: `backend/app/storage/sharepoint.py`
- Modify: `backend/pyproject.toml` (add `msal`)
- Test: `backend/tests/storage/test_sharepoint.py`

**Interfaces:**
- Consumes: Task 1 (`get_client`, `TokenProvider`, `send_with_retry`, `GRAPH_POLICY`, `raise_for_storage`), `app/storage/base.py`.
- Produces:
  - `app.storage.sharepoint.GraphTokenProvider(tenant_id: str, client_id: str, client_secret: str)` implementing `TokenProvider`
  - `app.storage.sharepoint.SharePointBackend(site_id: str, drive_id: str, root_path: str, tokens: TokenProvider, *, client: httpx.AsyncClient | None = None, sleep=asyncio.sleep)` implementing `StorageBackend`
  - `app.storage.sharepoint.CHUNK_BYTES: int`, `SIMPLE_UPLOAD_LIMIT: int`, `HEALTH_PROBE_NAME: str`

- [ ] **Step 1: Add the dependency**

Run from `backend/`: `uv add msal`

`msal` ships type hints that mypy strict accepts for the two calls used here; if `uv run mypy app` reports missing stubs, add `"msal"` to the existing `ignore_missing_imports` override list rather than loosening anything else.

- [ ] **Step 2: Write the failing test**

`backend/tests/storage/test_sharepoint.py`:

```python
"""SharePoint adapter over Microsoft Graph. Scripted transport only; no network, no tenant."""

import httpx
import pytest

from app.storage.base import (
    HealthStatus,
    StorageAuthError,
    StorageNotFound,
    StoragePathError,
)
from app.storage.sharepoint import CHUNK_BYTES, SharePointBackend

SITE_ID = "contoso.sharepoint.com,00000000-0000-0000-0000-000000000000,1111"
DRIVE_ID = "test-library-drive-id"
OTHER_DRIVE = "another-customers-library"
PATH = "02-requirements/srs--customer-portal.docx"
DRIVE_PREFIX = f"https://graph.microsoft.com/v1.0/drives/{DRIVE_ID}"


class FakeTokens:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def token(self) -> str:
        if self.fail:
            raise StorageAuthError(
                "The Microsoft 365 credentials were rejected. Check the tenant id, client id "
                "and client secret."
            )
        return "test-token"


class Script:
    def __init__(self) -> None:
        self.rules: list[tuple[str, httpx.Response]] = []
        self.requests: list[httpx.Request] = []

    def on(self, match: str, response: httpx.Response) -> "Script":
        self.rules.append((match, response))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        target = f"{request.method} {request.url}"
        for match, response in self.rules:
            if match in target:
                return response
        return httpx.Response(404, json={"error": {"code": "itemNotFound"}})


async def _no_sleep(_seconds: float) -> None:
    return None


def _backend(script: Script, tokens: FakeTokens | None = None, root: str = "") -> SharePointBackend:
    return SharePointBackend(
        SITE_ID,
        DRIVE_ID,
        root,
        tokens or FakeTokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(script.handler)),
        sleep=_no_sleep,
    )


def _item(item_id: str = "item-1") -> dict[str, object]:
    return {"id": item_id, "name": "srs--customer-portal.docx", "webUrl": "https://example.invalid/x"}


# -- addressing ----------------------------------------------------------------------------


async def test_every_request_stays_inside_the_configured_library() -> None:
    """All customers share one site, so a request must never address another library."""
    script = (
        Script()
        .on("PUT", httpx.Response(201, json=_item()))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
    )
    backend = _backend(script)
    await backend.put_file(PATH, b"v1", "application/octet-stream")
    assert script.requests
    for request in script.requests:
        assert str(request.url).startswith(DRIVE_PREFIX)
        assert OTHER_DRIVE not in str(request.url)
        assert "/sites/" not in str(request.url)  # no library enumeration on a data path


async def test_paths_are_url_encoded_and_rooted_at_the_project_folder() -> None:
    script = (
        Script()
        .on("PUT", httpx.Response(201, json=_item()))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
    )
    backend = _backend(script, root="acme")
    await backend.put_file("01-overview/other--tài liệu (bản cuối).md", b"x", "text/markdown")
    url = str(script.requests[0].url)
    assert "root:/acme/01-overview/" in url
    assert " " not in url and "%20" in url


async def test_unsafe_paths_make_no_request() -> None:
    script = Script()
    backend = _backend(script)
    for bad in ("../escape.md", "/abs.md", "C:/x.md", ".versions/x", "a\\b.md", ""):
        with pytest.raises(StoragePathError):
            await backend.put_file(bad, b"x", "text/plain")
        with pytest.raises(StoragePathError):
            await backend.get_file(bad)
    assert script.requests == []


# -- uploads and versions ------------------------------------------------------------------


async def test_small_files_use_a_single_put() -> None:
    script = (
        Script()
        .on("PUT", httpx.Response(201, json=_item()))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "2.0"}, {"id": "1.0"}]}))
    )
    backend = _backend(script)
    stored = await backend.put_file(PATH, b"v1", "text/plain")
    assert stored.item_id == "item-1"
    assert stored.version_id == "2.0"  # Graph lists newest first; the newest is what we wrote
    assert stored.web_url == "https://example.invalid/x"
    assert not [r for r in script.requests if "createUploadSession" in str(r.url)]


async def test_large_files_use_an_upload_session_in_320_kib_chunks() -> None:
    session_url = "https://upload.invalid/session"
    script = (
        Script()
        .on("createUploadSession", httpx.Response(200, json={"uploadUrl": session_url}))
        .on(session_url, httpx.Response(201, json=_item()))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
    )
    backend = _backend(script)
    size = CHUNK_BYTES * 2 + 100
    await backend.put_file(PATH, b"x" * size, "application/octet-stream")
    chunks = [r for r in script.requests if str(r.url) == session_url]
    assert len(chunks) == 3
    assert chunks[0].headers["Content-Range"] == f"bytes 0-{CHUNK_BYTES - 1}/{size}"
    assert chunks[-1].headers["Content-Range"] == f"bytes {CHUNK_BYTES * 2}-{size - 1}/{size}"
    assert "Authorization" not in chunks[0].headers  # the upload URL is already pre-authorised


async def test_versions_are_returned_oldest_first() -> None:
    versions = {
        "value": [
            {"id": "2.0", "size": 4, "lastModifiedDateTime": "2026-10-02T10:00:00Z"},
            {"id": "1.0", "size": 2, "lastModifiedDateTime": "2026-10-01T10:00:00Z"},
        ]
    }
    script = Script().on("/versions", httpx.Response(200, json=versions))
    backend = _backend(script)
    listed = await backend.list_versions(PATH)
    assert [v.version_id for v in listed] == ["1.0", "2.0"]
    assert listed[0].modified_at < listed[1].modified_at


async def test_missing_file_and_version_raise_not_found() -> None:
    script = Script()
    backend = _backend(script)
    with pytest.raises(StorageNotFound):
        await backend.get_file(PATH)
    with pytest.raises(StorageNotFound):
        await backend.move_to_trash(PATH)
    assert await backend.exists(PATH) is False


async def test_version_content_follows_the_redirect_to_storage() -> None:
    script = (
        Script()
        .on("/versions/1.0/content", httpx.Response(302, headers={"Location": "https://cdn.invalid/blob"}))
        .on("https://cdn.invalid/blob", httpx.Response(200, content=b"v1"))
    )
    backend = _backend(script)
    assert await backend.get_version(PATH, "1.0") == b"v1"


# -- health --------------------------------------------------------------------------------


async def test_health_diagnoses_each_failure_stage() -> None:
    rejected = _backend(Script(), FakeTokens(fail=True))
    status = await rejected.health()
    assert status.ok is False and status.field == "secret"
    assert "client secret" in status.detail

    no_site = _backend(Script().on(f"/sites/{SITE_ID}", httpx.Response(404, json={})))
    status = await no_site.health()
    assert status.ok is False and status.field == "site_id"
    assert "site" in status.detail.lower() and "not found" in status.detail

    no_grant = _backend(Script().on(f"/sites/{SITE_ID}", httpx.Response(403, json={})))
    status = await no_grant.health()
    assert status.ok is False and status.field == "site_id"
    assert "Sites.Selected" in status.detail  # the grant IT must make, named in the message

    no_library = _backend(
        Script()
        .on(f"/sites/{SITE_ID}", httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}))
        .on(DRIVE_PREFIX, httpx.Response(404, json={}))
    )
    status = await no_library.health()
    assert status.ok is False and status.field == "drive_id"
    assert "document library" in status.detail


async def test_health_rejects_a_library_from_another_site() -> None:
    """A drive id pasted from a different site must be caught here, not at the first upload."""
    script = (
        Script()
        .on(f"/sites/{SITE_ID}", httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}))
        .on(DRIVE_PREFIX, httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/other/Docs"}))
    )
    status = await _backend(script).health()
    assert status.ok is False and status.field == "drive_id"
    assert "does not belong" in status.detail


async def test_health_reports_no_write_permission() -> None:
    script = (
        Script()
        .on(f"/sites/{SITE_ID}", httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}))
        .on(DRIVE_PREFIX + "?", httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}))
        .on("PUT", httpx.Response(403, json={}))
    )
    status = await _backend(script).health()
    assert status.ok is False and status.field == "site_id"
    assert "write" in status.detail and "Sites.Selected" in status.detail


async def test_health_reports_versioning_disabled() -> None:
    """A library with version history off would silently lose the history we record (spec 8.2)."""
    script = (
        Script()
        .on(f"/sites/{SITE_ID}", httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}))
        .on(DRIVE_PREFIX + "?", httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}))
        .on("PUT", httpx.Response(201, json=_item("probe-1")))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
        .on("DELETE", httpx.Response(204))
    )
    status = await _backend(script).health()
    assert status.ok is False and status.field == "drive_id"
    assert "Version history" in status.detail


async def test_health_is_ok_and_cleans_up_its_probe() -> None:
    script = (
        Script()
        .on(f"/sites/{SITE_ID}", httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}))
        .on(DRIVE_PREFIX + "?", httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}))
        .on("PUT", httpx.Response(201, json=_item("probe-1")))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "2.0"}, {"id": "1.0"}]}))
        .on("DELETE", httpx.Response(204))
    )
    backend = _backend(script)
    assert await backend.health() == HealthStatus(ok=True, detail="ok")
    assert [r for r in script.requests if r.method == "DELETE"]


async def test_health_probe_result_is_cached() -> None:
    script = (
        Script()
        .on(f"/sites/{SITE_ID}", httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}))
        .on(DRIVE_PREFIX + "?", httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}))
        .on("PUT", httpx.Response(201, json=_item("probe-1")))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "2.0"}, {"id": "1.0"}]}))
        .on("DELETE", httpx.Response(204))
    )
    backend = _backend(script)
    await backend.health()
    writes = len([r for r in script.requests if r.method == "PUT"])
    await backend.health()
    assert len([r for r in script.requests if r.method == "PUT"]) == writes  # no second probe


async def test_health_message_never_contains_a_token_or_a_provider_body() -> None:
    script = Script().on(f"/sites/{SITE_ID}", httpx.Response(500, text="Bearer test-token echoed"))
    status = await _backend(script).health()
    assert status.ok is False
    assert "test-token" not in status.detail and "Bearer" not in status.detail
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/storage/test_sharepoint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.storage.sharepoint'`.

- [ ] **Step 4: Write the adapter**

`backend/app/storage/sharepoint.py`:

```python
"""SharePoint / OneDrive adapter on Microsoft Graph (spec 8.2).

App-only client credentials through ``msal``, permission ``Sites.Selected``. All projects share
one site and each customer has its own document library, so a connection carries one site id and
one drive id and every data-path request addresses ``/drives/{drive_id}/`` and nothing else.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from time import monotonic
from typing import Any
from urllib.parse import quote

import httpx

from app.storage.base import (
    HealthStatus,
    StorageAuthError,
    StorageError,
    StorageNotFound,
    StoredFile,
    StoredVersion,
    normalize_path,
)
from app.storage.http import TokenProvider, get_client
from app.storage.retry import GRAPH_POLICY, raise_for_storage, send_with_retry

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024
CHUNK_BYTES = 5 * 320 * 1024  # Graph requires a multiple of 320 KiB
HEALTH_PROBE_NAME = ".qc-agent-health.txt"
PROBE_CACHE_SECONDS = 600.0

CREDENTIALS_REJECTED = (
    "The Microsoft 365 credentials were rejected or have expired. Check the tenant id, client "
    "id and client secret, and whether the secret has expired in Entra ID."
)
SITE_NOT_FOUND = "SharePoint site not found. Check the site id."
NO_GRANT = (
    "No access to this site. A Microsoft 365 administrator must grant this application write "
    "access to the site (Sites.Selected)."
)
NO_WRITE = (
    "This application can read the site but cannot write to it. The Sites.Selected grant must "
    "be write, not read."
)
LIBRARY_NOT_FOUND = "Document library not found. Check the document library (drive) id."
WRONG_SITE = (
    "This document library does not belong to the site above. Check the document library "
    "(drive) id."
)
VERSIONING_OFF = (
    "Version history appears to be disabled on this document library. Turn versioning on in "
    "the library settings, otherwise document history cannot be kept."
)


class GraphTokenProvider:
    """App-only Graph token through msal, cached by msal itself.

    ``msal`` is synchronous, so acquisition runs in a worker thread. The client secret and the
    token never leave this object.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._app: Any | None = None
        self._lock = asyncio.Lock()

    def _acquire(self) -> str:
        import msal  # imported late so the dependency is optional at import time

        if self._app is None:
            self._app = msal.ConfidentialClientApplication(
                self._client_id,
                authority=f"https://login.microsoftonline.com/{self._tenant_id}",
                client_credential=self._client_secret,
            )
        result = self._app.acquire_token_for_client(scopes=SCOPES)
        token = result.get("access_token") if isinstance(result, dict) else None
        if not token:
            # result["error_description"] can contain request identifiers; log the code only.
            code = result.get("error") if isinstance(result, dict) else "unknown"
            logger.warning("Graph token request failed: %s", code)
            raise StorageAuthError(CREDENTIALS_REJECTED)
        return str(token)

    async def token(self) -> str:
        async with self._lock:
            try:
                return await asyncio.to_thread(self._acquire)
            except StorageError:
                raise
            except Exception as exc:  # noqa: BLE001 - msal raises several transport types
                logger.warning("Graph token request failed: %s", type(exc).__name__)
                raise StorageAuthError(CREDENTIALS_REJECTED) from None


class SharePointBackend:
    def __init__(
        self,
        site_id: str,
        drive_id: str,
        root_path: str,
        tokens: TokenProvider,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._site_id = site_id
        self._drive_id = drive_id
        self._root_path = root_path.strip("/")
        self._tokens = tokens
        self._client = client or get_client()
        self._sleep = sleep
        self._probe: tuple[HealthStatus, float] | None = None

    # -- plumbing --------------------------------------------------------------------------

    @property
    def _drive(self) -> str:
        return f"{GRAPH}/drives/{self._drive_id}"

    def _address(self, path: str) -> str:
        """``/drives/{id}/root:/{project root}/{path}:`` with every segment URL-encoded."""
        relative = normalize_path(path)
        full = f"{self._root_path}/{relative}" if self._root_path else relative
        return f"{self._drive}/root:/{quote(full, safe='/')}:"

    async def _send(self, method: str, url: str, *, context: str, **kwargs: Any) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {await self._tokens.token()}",
            **kwargs.pop("headers", {}),
        }
        return await send_with_retry(
            self._client,
            lambda: self._client.build_request(method, url, headers=headers, **kwargs),
            policy=GRAPH_POLICY,
            context=context,
            sleep=self._sleep,
        )

    async def _item_id(self, path: str) -> str:
        relative = normalize_path(path)
        context = f"Looking up {relative}"
        response = await self._send(
            "GET", f"{self._address(path)}?$select=id", context=context
        )
        if response.status_code == 404:
            raise StorageNotFound(f"File not found: {relative}")
        raise_for_storage(response, context=context)
        return str(response.json()["id"])

    async def _newest_version_id(self, item_id: str, context: str) -> str:
        response = await self._send(
            "GET", f"{self._drive}/items/{item_id}/versions?$top=1", context=context
        )
        raise_for_storage(response, context=context)
        values = response.json().get("value", [])
        return str(values[0]["id"]) if values else ""

    # -- StorageBackend --------------------------------------------------------------------

    async def ensure_folder(self, path: str) -> None:
        relative = normalize_path(path)
        walked: list[str] = []
        for name in relative.split("/"):
            parent = "/".join(walked)
            walked.append(name)
            prefix = f"{self._root_path}/{parent}" if self._root_path else parent
            target = (
                f"{self._drive}/root:/{quote(prefix, safe='/')}:/children"
                if prefix
                else f"{self._drive}/root/children"
            )
            context = f"Creating folder {'/'.join(walked)}"
            response = await self._send(
                "POST",
                target,
                context=context,
                json={
                    "name": name,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "fail",
                },
            )
            if response.status_code == 409:
                continue  # already there, which is what ensure_folder promises
            raise_for_storage(response, context=context)

    async def put_file(self, path: str, data: bytes, content_type: str) -> StoredFile:
        relative = normalize_path(path)
        context = f"Uploading {relative}"
        if len(data) <= SIMPLE_UPLOAD_LIMIT:
            response = await self._send(
                "PUT",
                f"{self._address(path)}/content",
                context=context,
                content=data,
                headers={"Content-Type": content_type},
            )
            raise_for_storage(response, context=context)
            item = response.json()
        else:
            item = await self._upload_session(path, data, context)
        version_id = await self._newest_version_id(str(item["id"]), context)
        return StoredFile(
            item_id=str(item["id"]), version_id=version_id, web_url=item.get("webUrl")
        )

    async def _upload_session(self, path: str, data: bytes, context: str) -> dict[str, Any]:
        start = await self._send(
            "POST",
            f"{self._address(path)}/createUploadSession",
            context=context,
            json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
        )
        raise_for_storage(start, context=context)
        upload_url = str(start.json()["uploadUrl"])
        total = len(data)
        last: httpx.Response | None = None
        for offset in range(0, total, CHUNK_BYTES):
            chunk = data[offset : offset + CHUNK_BYTES]
            end = offset + len(chunk) - 1
            # The upload URL carries its own authorisation; sending the bearer token here is
            # both unnecessary and a way to leak it to a storage host.
            last = await send_with_retry(
                self._client,
                lambda chunk=chunk, offset=offset, end=end: self._client.build_request(  # type: ignore[misc]
                    "PUT",
                    upload_url,
                    content=chunk,
                    headers={"Content-Range": f"bytes {offset}-{end}/{total}"},
                ),
                policy=GRAPH_POLICY,
                context=context,
                sleep=self._sleep,
            )
            raise_for_storage(last, context=context)
        if last is None:
            raise StorageError(f"{context} failed: nothing to upload.")
        item: dict[str, Any] = last.json()
        return item

    async def get_file(self, path: str) -> bytes:
        relative = normalize_path(path)
        context = f"Downloading {relative}"
        response = await self._send(
            "GET", f"{self._address(path)}/content", context=context
        )
        if response.status_code in (301, 302, 303, 307):
            response = await self._client.get(response.headers["Location"])
        if response.status_code == 404:
            raise StorageNotFound(f"File not found: {relative}")
        raise_for_storage(response, context=context)
        return response.content

    async def exists(self, path: str) -> bool:
        context = f"Checking {normalize_path(path)}"
        response = await self._send(
            "GET", f"{self._address(path)}?$select=id,folder", context=context
        )
        if response.status_code == 404:
            return False
        raise_for_storage(response, context=context)
        return "folder" not in response.json()

    async def list_versions(self, path: str) -> list[StoredVersion]:
        relative = normalize_path(path)
        context = f"Listing versions of {relative}"
        item_id = await self._item_id(path)
        response = await self._send(
            "GET", f"{self._drive}/items/{item_id}/versions", context=context
        )
        raise_for_storage(response, context=context)
        values = response.json().get("value", [])
        versions = [
            StoredVersion(
                version_id=str(v["id"]),
                size=int(v.get("size", 0)),
                modified_at=datetime.fromisoformat(
                    str(v["lastModifiedDateTime"]).replace("Z", "+00:00")
                ),
            )
            for v in values
        ]
        versions.sort(key=lambda v: v.modified_at)  # Graph lists newest first
        return versions

    async def get_version(self, path: str, version_id: str) -> bytes:
        relative = normalize_path(path)
        context = f"Downloading a version of {relative}"
        item_id = await self._item_id(path)
        response = await self._send(
            "GET",
            f"{self._drive}/items/{item_id}/versions/{quote(version_id, safe='')}/content",
            context=context,
        )
        if response.status_code in (301, 302, 303, 307):
            response = await self._client.get(response.headers["Location"])
        if response.status_code == 404:
            raise StorageNotFound(f"Version not found: {version_id}")
        raise_for_storage(response, context=context)
        return response.content

    async def move_to_trash(self, path: str) -> None:
        relative = normalize_path(path)
        context = f"Removing {relative}"
        item_id = await self._item_id(path)  # raises StorageNotFound when it is not there
        response = await self._send("DELETE", f"{self._drive}/items/{item_id}", context=context)
        if response.status_code == 404:
            raise StorageNotFound(f"File not found: {relative}")
        raise_for_storage(response, context=context)

    # -- health ----------------------------------------------------------------------------

    async def health(self) -> HealthStatus:
        """Staged probe, each stage naming the field or the grant at fault (spec 8.5, 8.6).

        The last stage writes a small probe file twice and counts its versions, because Graph
        v1.0 does not expose a library's versioning setting. The result is cached for ten
        minutes so repeated checks do not churn the library.
        """
        if self._probe is not None and self._probe[1] > monotonic():
            return self._probe[0]
        status = await self._probe_once()
        self._probe = (status, monotonic() + PROBE_CACHE_SECONDS)
        return status

    async def _probe_once(self) -> HealthStatus:
        try:
            await self._tokens.token()
        except StorageError as exc:
            return HealthStatus(ok=False, detail=str(exc), field="secret")

        site = await self._quiet("GET", f"{GRAPH}/sites/{self._site_id}?$select=id,webUrl")
        if isinstance(site, HealthStatus):
            return HealthStatus(ok=False, detail=site.detail, field="site_id")
        if site.status_code == 404:
            return HealthStatus(ok=False, detail=SITE_NOT_FOUND, field="site_id")
        if site.status_code in (401, 403):
            return HealthStatus(ok=False, detail=NO_GRANT, field="site_id")
        if site.status_code >= 400:
            return HealthStatus(
                ok=False, detail=f"Checking the site failed ({site.status_code}).", field="site_id"
            )
        site_url = str(site.json().get("webUrl", "")).rstrip("/")

        drive = await self._quiet("GET", f"{self._drive}?$select=id,name,webUrl")
        if isinstance(drive, HealthStatus):
            return HealthStatus(ok=False, detail=drive.detail, field="drive_id")
        if drive.status_code in (403, 404):
            return HealthStatus(ok=False, detail=LIBRARY_NOT_FOUND, field="drive_id")
        if drive.status_code >= 400:
            return HealthStatus(
                ok=False,
                detail=f"Checking the document library failed ({drive.status_code}).",
                field="drive_id",
            )
        library_url = str(drive.json().get("webUrl", ""))
        if site_url and not library_url.startswith(site_url):
            return HealthStatus(ok=False, detail=WRONG_SITE, field="drive_id")

        return await self._probe_write_and_versioning()

    async def _probe_write_and_versioning(self) -> HealthStatus:
        probe_path = (
            f"{self._root_path}/{HEALTH_PROBE_NAME}" if self._root_path else HEALTH_PROBE_NAME
        )
        address = f"{self._drive}/root:/{quote(probe_path, safe='/')}:"
        item_id = ""
        for body in (b"qc-agent health probe 1\n", b"qc-agent health probe 2\n"):
            written = await self._quiet(
                "PUT", f"{address}/content", content=body, headers={"Content-Type": "text/plain"}
            )
            if isinstance(written, HealthStatus):
                return HealthStatus(ok=False, detail=written.detail, field="site_id")
            if written.status_code in (401, 403):
                return HealthStatus(ok=False, detail=NO_WRITE, field="site_id")
            if written.status_code >= 400:
                return HealthStatus(
                    ok=False,
                    detail=f"Writing a test file failed ({written.status_code}).",
                    field="drive_id",
                )
            item_id = str(written.json()["id"])

        versions = await self._quiet("GET", f"{self._drive}/items/{item_id}/versions")
        count = (
            0 if isinstance(versions, HealthStatus) else len(versions.json().get("value", []))
        )
        await self._quiet("DELETE", f"{self._drive}/items/{item_id}")  # best effort cleanup
        if count < 2:
            return HealthStatus(ok=False, detail=VERSIONING_OFF, field="drive_id")
        return HealthStatus(ok=True, detail="ok")

    async def _quiet(self, method: str, url: str, **kwargs: Any) -> httpx.Response | HealthStatus:
        """Send a probe request, turning a storage error into a status instead of raising."""
        try:
            return await self._send(method, url, context="Checking the connection", **kwargs)
        except StorageAuthError:
            return HealthStatus(ok=False, detail=NO_GRANT)
        except StorageError as exc:
            return HealthStatus(ok=False, detail=str(exc))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/storage/test_sharepoint.py -v`
Expected: PASS, every test.

Run: `uv run ruff format . && uv run ruff check . && uv run mypy app && uv run pytest`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add app/storage/sharepoint.py pyproject.toml uv.lock tests/storage/test_sharepoint.py
git commit -m "feat(storage): SharePoint adapter on Microsoft Graph

App-only Sites.Selected credentials through msal, upload sessions above
4 MiB, versions through driveItem/versions, and a staged health probe
that separates a rejected secret, a wrong site id, a library from another
site, a missing write grant and a library with versioning turned off.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Connection configuration, secrets and adapter selection

**Needs live credentials:** no. Everything is validation, decryption and wiring, tested against PostgreSQL with synthetic values.

After this task an administrator can create a working `sharepoint` or `gdrive` connection through the API with nothing but typed fields — no `.env` entry, no file on the server, no restart.

**Files:**
- Modify: `backend/app/schemas/storage.py` (`SharePointConfig`, `GDriveConfig`, `StorageTestResult.field`)
- Modify: `backend/app/services/storage_connections.py` (`ACCEPTED_TYPES`, config dispatch, secret rules, no-op audit)
- Modify: `backend/app/storage/select.py` (decrypt, cache token providers, build the adapters)
- Modify: `backend/app/api/routes/storage_connections.py` (return `field` from Test connection)
- Modify: `frontend/openapi.json` (regenerated)
- Test: `backend/tests/storage/test_select.py` (extend), `backend/tests/services/test_storage_connections.py` (extend), `backend/tests/api/test_storage_connections.py` (extend)

**Interfaces:**
- Consumes: `SharePointBackend`, `GraphTokenProvider` (Task 4); `GoogleDriveBackend`, `ServiceAccountTokenProvider`, `validate_service_account_key` (Task 3).
- Produces:
  - `app.schemas.storage.SharePointConfig(tenant_id: str, client_id: str, site_id: str, drive_id: str)`
  - `app.schemas.storage.GDriveConfig(drive_id: str)`
  - `app.schemas.storage.StorageTestResult(ok: bool, detail: str, field: str | None = None)`
  - `app.services.storage_connections.ACCEPTED_TYPES = ("localfs", "sharepoint", "gdrive")`
  - `app.services.storage_connections.SECRET_REQUIRED_TYPES = ("sharepoint", "gdrive")`
  - `app.storage.select.connection_secret(connection, settings) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/storage/test_select.py`:

```python
import json as _json

from app.core.crypto import SecretBox
from app.db.models import StorageConnection as _Connection
from app.storage.gdrive import GoogleDriveBackend
from app.storage.select import connection_secret
from app.storage.sharepoint import SharePointBackend

SP_CONFIG = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "client_id": "22222222-2222-2222-2222-222222222222",
    "site_id": "example.sharepoint.com,33333333-3333-3333-3333-333333333333,4444",
    "drive_id": "b!test-library-drive-id",
}
# A synthetic key body, assembled at runtime so the repository's gitleaks hook does not
# flag a fixture. It is not a key and cannot sign anything.
FAKE_PEM = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END " + "PRIVATE KEY-----\n"
GD_CONFIG = {"drive_id": "0ATestSharedDriveId"}
FAKE_SA_KEY = _json.dumps(
    {
        "type": "service_account",
        "project_id": "qc-agent-test",
        "private_key": FAKE_PEM,
        "client_email": "qc-agent@qc-agent-test.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


def _cloud(type_: str, config: dict[str, str], secret: str, settings: Settings) -> _Connection:
    return _Connection(
        id=uuid.uuid4(),
        type=type_,
        name="Customer library",
        config=config,
        secret_enc=SecretBox(settings.secret_encryption_key).encrypt(secret),
    )


def test_backend_for_sharepoint_is_rooted_at_the_project_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _cloud("sharepoint", SP_CONFIG, "client-secret-value", settings)
    backend = backend_for(connection, "acme", settings)
    assert isinstance(backend, SharePointBackend)
    own = connection_backend(connection, settings)
    assert isinstance(own, SharePointBackend)


def test_backend_for_gdrive_is_rooted_at_the_project_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _cloud("gdrive", GD_CONFIG, FAKE_SA_KEY, settings)
    assert isinstance(backend_for(connection, "acme", settings), GoogleDriveBackend)
    assert isinstance(connection_backend(connection, settings), GoogleDriveBackend)


def test_token_providers_are_reused_for_the_same_connection(tmp_path: Path) -> None:
    """A new provider per request would mean a token request per upload."""
    settings = _settings(tmp_path)
    connection = _cloud("sharepoint", SP_CONFIG, "client-secret-value", settings)
    first = backend_for(connection, "acme", settings)
    second = backend_for(connection, "acme", settings)
    assert first._tokens is second._tokens  # noqa: SLF001 - the point of the test


def test_rotating_the_secret_replaces_the_cached_provider(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _cloud("sharepoint", SP_CONFIG, "client-secret-value", settings)
    first = backend_for(connection, "acme", settings)
    connection.secret_enc = SecretBox(settings.secret_encryption_key).encrypt("rotated-secret")
    second = backend_for(connection, "acme", settings)
    assert first._tokens is not second._tokens  # noqa: SLF001


def test_a_cloud_connection_without_a_secret_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _Connection(id=uuid.uuid4(), type="gdrive", name="x", config=GD_CONFIG)
    with pytest.raises(StorageError, match="no stored secret"):
        connection_backend(connection, settings)


def test_a_secret_that_cannot_be_decrypted_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    connection = _Connection(
        id=uuid.uuid4(), type="gdrive", name="x", config=GD_CONFIG, secret_enc="not-a-fernet-token"
    )
    with pytest.raises(StorageError, match="could not be decrypted"):
        connection_secret(connection, settings)
```

Append to `backend/tests/services/test_storage_connections.py`:

```python
import json as _json

import pytest as _pytest

from app.services.storage_connections import StorageConnectionError, validate_config

# A synthetic key body, assembled at runtime so the repository's gitleaks hook does not
# flag a fixture. It is not a key and cannot sign anything.
FAKE_PEM = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END " + "PRIVATE KEY-----\n"

SP_CONFIG = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "client_id": "22222222-2222-2222-2222-222222222222",
    "site_id": "example.sharepoint.com,33333333-3333-3333-3333-333333333333,4444",
    "drive_id": "b!test-library-drive-id",
}


def test_sharepoint_config_is_validated_and_trimmed(settings: Settings) -> None:
    padded = {key: f"  {value}  " for key, value in SP_CONFIG.items()}
    assert validate_config("sharepoint", padded, settings) == SP_CONFIG


@_pytest.mark.parametrize("missing", sorted(SP_CONFIG))
def test_sharepoint_config_requires_every_field(settings: Settings, missing: str) -> None:
    config = {k: v for k, v in SP_CONFIG.items() if k != missing}
    with _pytest.raises(StorageConnectionError, match=missing.replace("_", " ")):
        validate_config("sharepoint", config, settings)


def test_sharepoint_config_rejects_unknown_fields(settings: Settings) -> None:
    with _pytest.raises(StorageConnectionError):
        validate_config("sharepoint", {**SP_CONFIG, "client_secret": "oops"}, settings)


def test_gdrive_config_requires_the_shared_drive_id(settings: Settings) -> None:
    assert validate_config("gdrive", {"drive_id": " 0ATest "}, settings) == {"drive_id": "0ATest"}
    with _pytest.raises(StorageConnectionError, match="Shared Drive id"):
        validate_config("gdrive", {}, settings)


def test_a_secret_is_required_for_cloud_types(
    db: AsyncSession, settings: Settings
) -> None:
    """A connection form that cannot store the secret is not a usable connection."""
    from app.services.storage_connections import require_secret

    with _pytest.raises(StorageConnectionError, match="client secret is required"):
        require_secret("sharepoint", None)
    with _pytest.raises(StorageConnectionError, match="service-account key is required"):
        require_secret("gdrive", None)
    require_secret("localfs", None)  # no secret, no complaint


def test_a_malformed_service_account_key_is_refused(settings: Settings) -> None:
    from app.services.storage_connections import require_secret

    with _pytest.raises(StorageConnectionError, match="valid JSON"):
        require_secret("gdrive", "not json")
    require_secret("gdrive", _json.dumps(
        {
            "type": "service_account",
            "private_key": FAKE_PEM,
            "client_email": "qc-agent@qc-agent-test.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    ))
```

Append to `backend/tests/api/test_storage_connections.py` (follow the file's existing client and admin-login fixtures):

```python
async def test_admin_creates_a_sharepoint_connection_without_touching_the_server(
    admin_client: AsyncClient,
) -> None:
    body = {
        "type": "sharepoint",
        "name": "Acme library",
        "config": {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "client_id": "22222222-2222-2222-2222-222222222222",
            "site_id": "example.sharepoint.com,33333333-3333-3333-3333-333333333333,4444",
            "drive_id": "b!test-library-drive-id",
        },
        "secret": "client-secret-value",
    }
    response = await admin_client.post("/api/v1/storage-connections", json=body, headers=CSRF)
    assert response.status_code == 201
    created = response.json()
    assert created["type"] == "sharepoint" and created["has_secret"] is True
    assert "secret" not in created and "client-secret-value" not in response.text
    assert created["config"]["site_id"] == body["config"]["site_id"]

    listed = await admin_client.get("/api/v1/storage-connections")
    assert "client-secret-value" not in listed.text


async def test_a_cloud_connection_without_a_secret_is_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/v1/storage-connections",
        json={"type": "gdrive", "name": "Acme drive", "config": {"drive_id": "0ATest"}},
        headers=CSRF,
    )
    assert response.status_code == 422
    assert "service-account key is required" in response.json()["detail"]


# A synthetic key body, assembled at runtime so the repository's gitleaks hook does not
# flag a fixture. It is not a key and cannot sign anything.
FAKE_PEM = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END " + "PRIVATE KEY-----\n"


async def test_test_connection_returns_the_field_at_fault(admin_client: AsyncClient) -> None:
    created = await admin_client.post(
        "/api/v1/storage-connections",
        json={
            "type": "gdrive",
            "name": "Unreachable drive",
            "config": {"drive_id": "0ADoesNotExist"},
            "secret": json.dumps(
                {
                    "type": "service_account",
                    "private_key": FAKE_PEM,
                    "client_email": "qc-agent@qc-agent-test.iam.gserviceaccount.com",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            ),
        },
        headers=CSRF,
    )
    connection_id = created.json()["id"]
    response = await admin_client.post(
        f"/api/v1/storage-connections/{connection_id}/test", headers=CSRF
    )
    assert response.status_code == 200
    result = response.json()
    # The key is syntactically valid but not a real credential, so Google rejects it: the
    # diagnosis must point at the secret field, and must not echo the key.
    assert result["ok"] is False and result["field"] == "secret"
    assert "PRIVATE KEY" not in response.text


async def test_patch_with_no_changes_writes_no_audit_row(
    admin_client: AsyncClient, db: AsyncSession
) -> None:
    connection = (await admin_client.get("/api/v1/storage-connections")).json()[0]
    before = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "storage_connection.updated")
    )
    response = await admin_client.patch(
        f"/api/v1/storage-connections/{connection['id']}",
        json={"name": connection["name"]},
        headers=CSRF,
    )
    assert response.status_code == 200
    after = await db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "storage_connection.updated")
    )
    assert after == before
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/storage/test_select.py tests/services/test_storage_connections.py tests/api/test_storage_connections.py -v`
Expected: FAIL — `ImportError: cannot import name 'connection_secret'`, and 422 "not available in this version" from the API tests.

- [ ] **Step 3: Add the configuration schemas**

In `backend/app/schemas/storage.py`, after `LocalFsConfig`:

```python
def _required(label: str) -> Callable[[str], str]:
    def check(value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{label} is required.")
        return cleaned

    return check


class SharePointConfig(BaseModel):
    """Non-secret configuration of a ``sharepoint`` connection: one customer's document library
    on the single shared site (spec 8.2). The client secret is stored separately, write-only."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=200)
    client_id: str = Field(min_length=1, max_length=200)
    site_id: str = Field(min_length=1, max_length=400)
    drive_id: str = Field(min_length=1, max_length=400)

    _strip_tenant = field_validator("tenant_id")(classmethod(lambda cls, v: _required("Tenant id")(v)))
    _strip_client = field_validator("client_id")(classmethod(lambda cls, v: _required("Client id")(v)))
    _strip_site = field_validator("site_id")(classmethod(lambda cls, v: _required("Site id")(v)))
    _strip_drive = field_validator("drive_id")(
        classmethod(lambda cls, v: _required("Document library (drive) id")(v))
    )


class GDriveConfig(BaseModel):
    """Non-secret configuration of a ``gdrive`` connection. The service-account JSON key is
    stored separately, write-only."""

    model_config = ConfigDict(extra="forbid")

    drive_id: str = Field(min_length=1, max_length=200)

    _strip_drive = field_validator("drive_id")(
        classmethod(lambda cls, v: _required("Shared Drive id")(v))
    )
```

Add `from collections.abc import Callable` to the imports, and give `StorageTestResult` the field:

```python
class StorageTestResult(BaseModel):
    ok: bool
    detail: str
    field: str | None = None  # the connection field at fault, when the adapter identified one
```

- [ ] **Step 4: Dispatch validation and require the secret**

In `backend/app/services/storage_connections.py`, replace `ACCEPTED_TYPES` and `validate_config`, and add `require_secret`:

```python
ACCEPTED_TYPES = ("localfs", "sharepoint", "gdrive")
SECRET_REQUIRED_TYPES = ("sharepoint", "gdrive")
SECRET_LABELS = {
    "sharepoint": "A client secret is required for a SharePoint connection.",
    "gdrive": "A service-account key is required for a Google Drive connection.",
}
CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "localfs": LocalFsConfig,
    "sharepoint": SharePointConfig,
    "gdrive": GDriveConfig,
}


def validate_config(type_: str, config: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Validate and normalise the non-secret configuration for a connection type."""
    if type_ not in ACCEPTED_TYPES:
        raise StorageConnectionError(f"Storage type {type_!r} is not available in this version.")
    try:
        parsed = CONFIG_MODELS[type_].model_validate(config)
    except ValidationError as exc:
        raise StorageConnectionError("; ".join(str(e["msg"]) for e in exc.errors())) from exc
    if isinstance(parsed, LocalFsConfig):
        try:
            localfs_root(parsed.root_path, settings)
        except StorageError as exc:
            raise StorageConnectionError(str(exc)) from exc
    return parsed.model_dump()


def require_secret(type_: str, secret: str | None) -> None:
    """A cloud connection without a usable secret cannot work; refuse it at the form."""
    if type_ not in SECRET_REQUIRED_TYPES:
        return
    if not secret:
        raise StorageConnectionError(SECRET_LABELS[type_])
    if type_ == "gdrive":
        try:
            validate_service_account_key(secret)
        except StorageError as exc:
            raise StorageConnectionError(str(exc)) from exc
```

Import `BaseModel` from `pydantic`, `GDriveConfig` and `SharePointConfig` from `app.schemas.storage`, and `validate_service_account_key` from `app.storage.gdrive`.

In `create_connection`, call `require_secret(type_, secret)` immediately after `clean_config = validate_config(...)`. In `update_connection`, call `require_secret(connection.type, secret)` when `secret is not None` (a connection may be edited without re-entering its secret, but a replacement must be usable).

In `update_connection`, skip the bookkeeping when nothing changed — this clears the open item "PATCH ghi audit cả khi không có gì đổi" in `docs/PENDING.md`:

```python
    if not changes:
        if commit:
            await db.commit()
        return connection
```

placed immediately after the `try: await db.flush() / except IntegrityError` block and before the
existing `await audit.record(db, "storage_connection.updated", ...)` call, which stays as it is.

In `test_connection`, carry the field through:

```python
    await audit.record(
        db,
        "storage_connection.tested",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"ok": status.ok, "detail": status.detail, "field": status.field},
    )
```

- [ ] **Step 5: Build the adapters in `select.py`**

In `backend/app/storage/select.py`, add the constants, the secret helper, the provider cache and the two branches:

```python
SHAREPOINT = "sharepoint"
GDRIVE = "gdrive"
NO_SECRET = "This storage connection has no stored secret. Enter it on the Storage page."
BAD_SECRET = "The stored secret could not be decrypted. Enter it again on the Storage page."

# One token provider per (connection, secret), so a publish does not mint a token per file and
# rotating a secret transparently replaces the provider.
_providers: dict[str, Any] = {}


def connection_secret(connection: StorageConnection, settings: Settings) -> str:
    if not connection.secret_enc:
        raise StorageError(NO_SECRET)
    try:
        return SecretBox(settings.secret_encryption_key).decrypt(connection.secret_enc)
    except InvalidToken as exc:
        raise StorageError(BAD_SECRET) from exc


def _provider_key(connection: StorageConnection) -> str:
    digest = hashlib.sha256((connection.secret_enc or "").encode()).hexdigest()[:16]
    return f"{connection.type}:{connection.id}:{digest}"


def _cloud_backend(connection: StorageConnection, root: str, settings: Settings) -> StorageBackend:
    key = _provider_key(connection)
    config = connection.config
    if connection.type == SHAREPOINT:
        provider = _providers.get(key)
        if provider is None:
            secret = connection_secret(connection, settings)
            provider = GraphTokenProvider(
                str(config["tenant_id"]), str(config["client_id"]), secret
            )
            _providers[key] = provider
        return SharePointBackend(
            str(config["site_id"]), str(config["drive_id"]), root, provider
        )
    provider = _providers.get(key)
    if provider is None:
        provider = ServiceAccountTokenProvider(connection_secret(connection, settings))
        _providers[key] = provider
    return GoogleDriveBackend(
        str(config["drive_id"]), root, provider, scope=str(connection.id)
    )
```

`connection_backend` gains, before its final `raise`:

```python
    if connection.type in (SHAREPOINT, GDRIVE):
        return _cloud_backend(connection, "", settings)
```

and `backend_for`:

```python
    if connection.type in (SHAREPOINT, GDRIVE):
        return _cloud_backend(connection, validate_root_segment(root), settings)
```

A connection row whose `config` was tampered with would raise `KeyError` from the `config[...]`
reads, which is not a message anyone can act on. Read the values through one helper placed above
`_cloud_backend` and use it for every `config[...]` above:

```python
def _config_value(connection: StorageConnection, key: str) -> str:
    value = connection.config.get(key)
    if not isinstance(value, str) or not value:
        raise StorageError("Storage connection configuration is incomplete.")
    return value
```

so `str(config["site_id"])` becomes `_config_value(connection, "site_id")`, and likewise for
`tenant_id`, `client_id` and both `drive_id` reads.

Add the imports: `hashlib`, `typing.Any`, `cryptography.fernet.InvalidToken`, `app.core.crypto.SecretBox`, `app.storage.gdrive.GoogleDriveBackend`, `app.storage.gdrive.ServiceAccountTokenProvider`, `app.storage.sharepoint.GraphTokenProvider`, `app.storage.sharepoint.SharePointBackend`.

- [ ] **Step 6: Return the field from the route**

In `backend/app/api/routes/storage_connections.py`, the last line of `test_connection` becomes:

```python
    return StorageTestResult(ok=status.ok, detail=status.detail, field=status.field)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/storage tests/services/test_storage_connections.py tests/api/test_storage_connections.py -v`
Expected: PASS.

- [ ] **Step 8: Regenerate the OpenAPI document**

Run from `backend/`: `uv run python -m app.openapi_export ../frontend/openapi.json`
Run: `uv run pytest tests/api/test_openapi_export.py -v`
Expected: PASS (the committed document matches the app).

Run: `uv run ruff format . && uv run ruff check . && uv run mypy app && uv run pytest`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add app/schemas/storage.py app/services/storage_connections.py app/storage/select.py app/api/routes/storage_connections.py ../frontend/openapi.json tests/storage/test_select.py tests/services/test_storage_connections.py tests/api/test_storage_connections.py
git commit -m "feat(storage): configure SharePoint and Google Drive connections from the API

Typed fields only: tenant/client/site/library for SharePoint, Shared Drive
id for Drive, with the client secret and the service-account key stored
write-only and encrypted. Test connection now returns the field at fault,
and a PATCH that changes nothing no longer writes an audit row.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Storage connections in `/health`

**Needs live credentials:** no. The summary is tested with stub backends.

`/health` is unauthenticated (`app/api/routes/health.py` has no auth dependency), so it reports one `ok`/`error` value and nothing else: no connection name, tenant id, site id, drive id or provider message. Details stay in `POST /storage-connections/{id}/test`, which is admin-only. The result is cached briefly so an anonymous caller cannot turn the endpoint into one Graph or Drive request per hit.

**Files:**
- Create: `backend/app/services/storage_health.py`
- Modify: `backend/app/api/routes/health.py`
- Modify: `frontend/openapi.json` (regenerated)
- Test: `backend/tests/services/test_storage_health.py`, `backend/tests/api/test_health.py` (extend)

**Interfaces:**
- Consumes: `connection_backend` (Task 5), `list_connections` (`app/services/storage_connections.py`), `HealthStatus`.
- Produces: `async app.services.storage_health.storage_check(db: AsyncSession, settings: Settings, *, now: Callable[[], float] = monotonic) -> str` returning `"ok"`, `"error"` or `"skipped"`, and `app.services.storage_health.reset_cache() -> None` for tests. Cache TTL `app.services.storage_health.CACHE_SECONDS = 60.0`.

- [ ] **Step 1: Write the failing test**

`backend/tests/services/test_storage_health.py`:

```python
"""The public /health storage check: one word, no details, and cached."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import StorageConnection
from app.services import storage_health
from app.storage.base import HealthStatus, StorageError
from tests.factories import make_connection


class Stub:
    calls = 0

    def __init__(self, status: HealthStatus | Exception) -> None:
        self._status = status

    async def health(self) -> HealthStatus:
        Stub.calls += 1
        if isinstance(self._status, Exception):
            raise self._status
        return self._status


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    storage_health.reset_cache()
    Stub.calls = 0


async def test_all_connections_healthy_is_ok(
    db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    assert await storage_health.storage_check(db, settings) == "ok"


async def test_one_failing_connection_makes_the_check_error(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_connection(db, name="Broken", root_path="broken")

    def fake(connection: StorageConnection, _settings: Settings) -> Stub:
        return Stub(HealthStatus(ok=connection.name != "Broken", detail="x", field="drive_id"))

    monkeypatch.setattr(storage_health, "connection_backend", fake)
    assert await storage_health.storage_check(db, settings) == "error"


async def test_an_adapter_that_raises_counts_as_an_error(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        storage_health, "connection_backend", lambda *_: Stub(StorageError("no secret"))
    )
    assert await storage_health.storage_check(db, settings) == "error"


async def test_inactive_connections_are_not_checked(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_connection(db, name="Retired", root_path="retired", is_active=False)
    monkeypatch.setattr(
        storage_health, "connection_backend", lambda *_: Stub(HealthStatus(ok=True, detail="ok"))
    )
    await storage_health.storage_check(db, settings)
    assert Stub.calls == 1  # only the active default


async def test_the_result_is_cached(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unauthenticated endpoint must not become one API call per request."""
    clock = [1000.0]
    monkeypatch.setattr(
        storage_health, "connection_backend", lambda *_: Stub(HealthStatus(ok=True, detail="ok"))
    )
    await storage_health.storage_check(db, settings, now=lambda: clock[0])
    await storage_health.storage_check(db, settings, now=lambda: clock[0])
    assert Stub.calls == 1
    clock[0] += storage_health.CACHE_SECONDS + 1
    await storage_health.storage_check(db, settings, now=lambda: clock[0])
    assert Stub.calls == 2
```

Append to `backend/tests/api/test_health.py`:

```python
async def test_health_reports_storage_without_any_detail(monkeypatch: Any) -> None:
    """Anonymous callers learn that storage is unhealthy, never which one or why."""
    from app.api.routes import health as health_route

    async def failing(*_args: Any, **_kwargs: Any) -> str:
        return "error"

    monkeypatch.setattr(health_route, "storage_check", failing)
    async with _client_with(_OkSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": "ok", "storage": "error"}}
    body = response.text
    for leak in ("sharepoint", "gdrive", "drive_id", "tenant", "site", "secret", "Bearer"):
        assert leak not in body


async def test_health_is_ok_when_storage_is_ok(monkeypatch: Any) -> None:
    from app.api.routes import health as health_route

    async def healthy(*_args: Any, **_kwargs: Any) -> str:
        return "ok"

    monkeypatch.setattr(health_route, "storage_check", healthy)
    async with _client_with(_OkSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["checks"]["storage"] == "ok"


async def test_health_skips_storage_when_the_database_is_down(monkeypatch: Any) -> None:
    """Without a database there are no connection rows to check; say so, do not guess."""
    async with _client_with(_BrokenSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "error", "storage": "skipped"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/services/test_storage_health.py tests/api/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.storage_health'`.

- [ ] **Step 3: Write the summary service**

`backend/app/services/storage_health.py`:

```python
"""Storage part of the public ``/health`` endpoint (spec 16).

``/health`` has no authentication, so this returns one word. Which connection failed and why is
admin-only and lives in ``POST /storage-connections/{id}/test``. The result is cached for a
minute so an anonymous caller cannot turn one request into one Graph or Drive call per
connection.
"""

import asyncio
import logging
from collections.abc import Callable
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import StorageConnection
from app.services.storage_connections import list_connections
from app.storage.base import StorageError
from app.storage.select import connection_backend

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0
PER_CONNECTION_TIMEOUT = 15.0

_cache: tuple[str, float] | None = None


def reset_cache() -> None:
    global _cache
    _cache = None


async def _one(connection: StorageConnection, settings: Settings) -> bool:
    try:
        async with asyncio.timeout(PER_CONNECTION_TIMEOUT):
            status = await connection_backend(connection, settings).health()
    except (StorageError, TimeoutError, OSError):
        logger.warning("Storage connection %s failed its health check", connection.id)
        return False
    if not status.ok:
        logger.warning("Storage connection %s is unhealthy", connection.id)
    return status.ok


async def storage_check(
    db: AsyncSession, settings: Settings, *, now: Callable[[], float] = monotonic
) -> str:
    global _cache
    if _cache is not None and _cache[1] > now():
        return _cache[0]
    connections = [c for c in await list_connections(db) if c.is_active]
    results = await asyncio.gather(*(_one(c, settings) for c in connections))
    verdict = "ok" if all(results) else "error"
    _cache = (verdict, now() + CACHE_SECONDS)
    return verdict
```

- [ ] **Step 4: Add the check to the route**

Replace the body of `health` in `backend/app/api/routes/health.py`:

```python
from app.api.deps import AppSettings, DbSession
from app.services.storage_health import storage_check


@router.get("/health")
async def health(db: DbSession, settings: AppSettings) -> JSONResponse:
    database = await _check_database(db)
    # No database means no connection rows to read, so the storage check has nothing to say.
    storage = await storage_check(db, settings) if database == "ok" else "skipped"
    checks = {"database": database, "storage": storage}
    ok = database == "ok" and storage in ("ok", "skipped")
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks},
        status_code=200 if ok else 503,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/services/test_storage_health.py tests/api/test_health.py -v`
Expected: PASS.

Run from `backend/`: `uv run python -m app.openapi_export ../frontend/openapi.json`
Run: `uv run ruff format . && uv run ruff check . && uv run mypy app && uv run pytest`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add app/services/storage_health.py app/api/routes/health.py ../frontend/openapi.json tests/services/test_storage_health.py tests/api/test_health.py
git commit -m "feat(health): report storage connections without leaking any detail

/health is unauthenticated, so it answers ok, error or skipped, and the
result is cached for a minute so it cannot be used to drive one Graph or
Drive request per hit. Names and reasons stay in the admin-only test.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Admin UI — SharePoint and Google Drive connection forms

**Needs live credentials:** no. Vitest with a mocked fetch, as the existing admin tests do.

The stakeholder's requirement is that an administrator configures a connection entirely by typing into the existing dialog. So the type dropdown's `sharepoint` and `gdrive` options stop being disabled, and the fields below the dropdown switch with the selected type **inside the same dialog** — not three dialogs. One descriptor module holds the per-type field list, so the form, the list column and the tests agree.

**Files:**
- Create: `frontend/src/features/admin/connectionTypes.ts`
- Create: `frontend/src/features/admin/ConnectionDialog.test.tsx`
- Modify: `frontend/src/features/admin/types.ts` (`AVAILABLE_TYPES`)
- Modify: `frontend/src/features/admin/ConnectionDialog.tsx`
- Modify: `frontend/src/features/admin/StorageAdmin.tsx` (location column)
- Modify: `frontend/src/messages.ts`
- Modify: `frontend/src/lib/api/schema.d.ts` (regenerated)
- Test: `frontend/src/features/admin/StorageAdmin.test.tsx` (extend)

**Interfaces:**
- Consumes: `StorageConnectionCreate` / `StorageConnectionOut` / `StorageTestResult` from `@/lib/api/schema` (Task 5 regenerated them; `StorageTestResult` now carries `field`).
- Produces:
  - `type ConnectionField = { name: string; label: string; hint?: string; secret?: boolean; multiline?: boolean; maxLength: number }`
  - `type ConnectionTypeSpec = { fields: ConnectionField[]; secretField: ConnectionField | null; defaults: Record<string, string>; summary: (config: Record<string, unknown>) => string }`
  - `CONNECTION_SPECS: Record<ConnectionType, ConnectionTypeSpec>`
  - `connectionSummary(connection: Connection): string`

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/admin/ConnectionDialog.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { ConnectionDialog } from "./ConnectionDialog";

const created = {
  id: "c-new",
  type: "sharepoint",
  name: "Acme library",
  config: {},
  is_default: false,
  is_active: true,
  has_secret: true,
  created_at: "2026-10-02T10:00:00+00:00",
  updated_at: "2026-10-02T10:00:00+00:00",
};

function open() {
  const onSaved = vi.fn();
  render(<ConnectionDialog onClose={() => {}} onSaved={onSaved} />);
  return onSaved;
}

it("switches the fields when the type changes, inside the same dialog", async () => {
  open();
  expect(screen.getByLabelText("Root path")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Type"), "sharepoint");
  expect(screen.queryByLabelText("Root path")).toBeNull();
  for (const label of [
    "Tenant ID",
    "Client ID",
    "Client secret",
    "Site ID",
    "Document library (drive) ID",
  ]) {
    expect(screen.getByLabelText(label)).toBeInTheDocument();
  }
  await userEvent.selectOptions(screen.getByLabelText("Type"), "gdrive");
  expect(screen.queryByLabelText("Tenant ID")).toBeNull();
  expect(screen.getByLabelText("Shared Drive ID")).toBeInTheDocument();
  expect(screen.getByLabelText("Service account JSON key")).toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
});

it("creates a SharePoint connection from typed fields only", async () => {
  const f = mockFetch([
    { method: "POST", path: "/api/v1/storage-connections", status: 201, body: created },
  ]);
  open();
  await userEvent.type(screen.getByLabelText("Name"), "Acme library");
  await userEvent.selectOptions(screen.getByLabelText("Type"), "sharepoint");
  await userEvent.type(screen.getByLabelText("Tenant ID"), "tenant-value");
  await userEvent.type(screen.getByLabelText("Client ID"), "client-value");
  await userEvent.type(screen.getByLabelText("Client secret"), "secret-value");
  await userEvent.type(screen.getByLabelText("Site ID"), "site-value");
  await userEvent.type(screen.getByLabelText("Document library (drive) ID"), "drive-value");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await f.body(0)).toEqual({
    type: "sharepoint",
    name: "Acme library",
    config: {
      tenant_id: "tenant-value",
      client_id: "client-value",
      site_id: "site-value",
      drive_id: "drive-value",
    },
    secret: "secret-value",
  });
});

it("keeps the secret out of the DOM after typing and never prefills it", async () => {
  open();
  await userEvent.selectOptions(screen.getByLabelText("Type"), "sharepoint");
  const secret = screen.getByLabelText("Client secret");
  await userEvent.type(secret, "secret-value");
  expect(secret).toHaveAttribute("type", "password");
  expect(secret).toHaveAttribute("autocomplete", "off");
  expect(document.body.innerHTML).not.toContain("secret-value");
});

it("requires the secret when creating a cloud connection", async () => {
  const f = mockFetch([]);
  open();
  await userEvent.type(screen.getByLabelText("Name"), "Acme drive");
  await userEvent.selectOptions(screen.getByLabelText("Type"), "gdrive");
  await userEvent.type(screen.getByLabelText("Shared Drive ID"), "0ATest");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Service account JSON key is required.",
  );
  expect(f.calls()).toHaveLength(0);
});

it("lets an existing cloud connection be edited without re-entering the secret", async () => {
  const f = mockFetch([
    {
      method: "PATCH",
      path: "/api/v1/storage-connections/c-1",
      body: { ...created, id: "c-1" },
    },
  ]);
  render(
    <ConnectionDialog
      connection={{
        ...created,
        id: "c-1",
        config: {
          tenant_id: "t",
          client_id: "c",
          site_id: "s",
          drive_id: "d",
        },
      }}
      onClose={() => {}}
      onSaved={() => {}}
    />,
  );
  expect(screen.getByLabelText("Type")).toBeDisabled();
  expect(screen.getByLabelText("Client secret")).toHaveValue("");
  await userEvent.clear(screen.getByLabelText("Site ID"));
  await userEvent.type(screen.getByLabelText("Site ID"), "s2");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const body = (await f.body(0)) as { secret?: string };
  expect(body.secret).toBeUndefined();
});
```

Append to `frontend/src/features/admin/StorageAdmin.test.tsx`:

```tsx
it("shows a location summary per type and the field a failed test blames", async () => {
  const sharepoint = {
    id: "c-sp",
    type: "sharepoint",
    name: "Acme library",
    config: { tenant_id: "t", client_id: "c", site_id: "site-value", drive_id: "drive-value" },
    is_default: false,
    is_active: true,
    has_secret: true,
    created_at: "2026-10-02T10:00:00+00:00",
    updated_at: "2026-10-02T10:00:00+00:00",
  };
  mockFetch([
    { path: "/api/v1/storage-connections", body: [sharepoint] },
    {
      method: "POST",
      path: "/api/v1/storage-connections/c-sp/test",
      body: {
        ok: false,
        detail:
          "No access to this site. A Microsoft 365 administrator must grant this application write access to the site (Sites.Selected).",
        field: "site_id",
      },
    },
  ]);
  render(<StorageAdmin />);
  const row = (await screen.findByRole("cell", { name: "Acme library" })).closest("tr")!;
  expect(within(row).getByText(/drive-value/)).toBeInTheDocument();
  expect(within(row).queryByText(/^t$/)).toBeNull(); // no tenant or client id in the list
  await userEvent.click(within(row).getByRole("button", { name: "Test connection" }));
  const status = await within(row).findByRole("status");
  expect(status).toHaveTextContent("Sites.Selected");
  expect(status).toHaveTextContent("Site ID"); // the field at fault, named for the admin
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `frontend/`: `pnpm test`
Expected: FAIL — `Cannot find module './connectionTypes'`, and the type dropdown's `sharepoint` option is still disabled.

- [ ] **Step 3: Write the type descriptors**

`frontend/src/features/admin/connectionTypes.ts`:

```ts
import { m } from "@/messages";
import type { Connection, ConnectionType } from "./types";

export type ConnectionField = {
  name: string;
  label: string;
  hint?: string;
  secret?: boolean;
  multiline?: boolean;
  maxLength: number;
};

export type ConnectionTypeSpec = {
  /** Non-secret fields, in the order they appear in the dialog. */
  fields: ConnectionField[];
  /** The write-only secret, or null for a type that has none. */
  secretField: ConnectionField | null;
  defaults: Record<string, string>;
  summary: (config: Record<string, unknown>) => string;
};

export const CONNECTION_SPECS: Record<ConnectionType, ConnectionTypeSpec> = {
  localfs: {
    fields: [
      {
        name: "root_path",
        label: m.storage.rootPath,
        hint: m.storage.rootPathHint,
        maxLength: 500,
      },
    ],
    secretField: null,
    defaults: { root_path: "." },
    summary: (config) => String(config.root_path ?? ""),
  },
  sharepoint: {
    fields: [
      { name: "tenant_id", label: m.storage.tenantId, hint: m.storage.tenantIdHint, maxLength: 200 },
      { name: "client_id", label: m.storage.clientId, hint: m.storage.clientIdHint, maxLength: 200 },
      { name: "site_id", label: m.storage.siteId, hint: m.storage.siteIdHint, maxLength: 400 },
      { name: "drive_id", label: m.storage.libraryId, hint: m.storage.libraryIdHint, maxLength: 400 },
    ],
    secretField: {
      name: "secret",
      label: m.storage.clientSecret,
      hint: m.storage.clientSecretHint,
      secret: true,
      maxLength: 20000,
    },
    defaults: {},
    // The list shows the library, which is the customer-visible part; tenant and client ids
    // identify the application and are not useful in a table.
    summary: (config) => String(config.drive_id ?? ""),
  },
  gdrive: {
    fields: [
      { name: "drive_id", label: m.storage.sharedDriveId, hint: m.storage.sharedDriveIdHint, maxLength: 200 },
    ],
    secretField: {
      name: "secret",
      label: m.storage.serviceAccountKey,
      hint: m.storage.serviceAccountKeyHint,
      secret: true,
      multiline: true,
      maxLength: 20000,
    },
    defaults: {},
    summary: (config) => String(config.drive_id ?? ""),
  },
};

export function connectionSummary(connection: Connection): string {
  const spec = CONNECTION_SPECS[connection.type as ConnectionType];
  return spec ? spec.summary(connection.config) : "";
}

/** The dialog label of a field a failed Test connection blamed, for the result message. */
export function fieldLabel(type: string, field: string | null | undefined): string | null {
  if (!field) return null;
  const spec = CONNECTION_SPECS[type as ConnectionType];
  if (!spec) return null;
  if (spec.secretField && spec.secretField.name === field) return spec.secretField.label;
  return spec.fields.find((f) => f.name === field)?.label ?? null;
}
```

- [ ] **Step 4: Enable the types and rewrite the dialog**

In `frontend/src/features/admin/types.ts`:

```ts
export const CONNECTION_TYPES: ConnectionType[] = ["localfs", "sharepoint", "gdrive"];
export const AVAILABLE_TYPES: ConnectionType[] = ["localfs", "sharepoint", "gdrive"];
```

In `frontend/src/features/admin/ConnectionDialog.tsx`, add
`import { CONNECTION_SPECS, type ConnectionTypeSpec } from "./connectionTypes";` next to the
existing `./types` import, then replace the `rootPath`/`hasSecret` state and the two hard-coded fields with state driven by `CONNECTION_SPECS`:

```tsx
  const [type, setType] = useState<ConnectionType>(
    (connection?.type as ConnectionType) ?? "localfs",
  );
  const spec = CONNECTION_SPECS[type];
  const [values, setValues] = useState<Record<string, string>>(() =>
    initialValues(CONNECTION_SPECS[(connection?.type as ConnectionType) ?? "localfs"], connection),
  );
  const [secret, setSecret] = useState("");

  function changeType(next: ConnectionType) {
    setType(next);
    setValues(initialValues(CONNECTION_SPECS[next], undefined));
    setSecret("");
  }
```

with this helper above the component:

```tsx
function initialValues(spec: ConnectionTypeSpec, connection: Connection | undefined) {
  const start: Record<string, string> = {};
  for (const field of spec.fields) {
    const current = connection?.config[field.name];
    start[field.name] = current === undefined ? (spec.defaults[field.name] ?? "") : String(current);
  }
  return start;
}
```

In `submit`, build the config from the spec and refuse a missing secret on create before any request:

```tsx
    const config = Object.fromEntries(
      spec.fields.map((field) => [field.name, values[field.name]?.trim() ?? ""]),
    );
    if (spec.secretField && !connection && !secret.trim()) {
      setError(m.storage.secretRequired(spec.secretField.label));
      setBusy(false);
      return;
    }
```

and send `...(secret.trim() ? { secret } : {})` on both create and update, so editing an existing connection never clears or re-sends the stored secret.

Render the fields from the spec, in place of the old `rootPath` field:

```tsx
        {spec.fields.map((field) => (
          <Field
            key={field.name}
            label={field.label}
            hint={field.hint}
            required
            maxLength={field.maxLength}
            value={values[field.name] ?? ""}
            onChange={(event) =>
              setValues((current) => ({ ...current, [field.name]: event.target.value }))
            }
          />
        ))}
        {spec.secretField ? (
          <Field
            label={spec.secretField.label}
            hint={
              connection ? m.storage.secretHint : (spec.secretField.hint ?? m.storage.secretHint)
            }
            type={spec.secretField.multiline ? undefined : "password"}
            multiline={spec.secretField.multiline}
            autoComplete="off"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
          />
        ) : null}
```

The multiline variant is needed for the service-account key, which is a JSON document. If `Field` does not support `multiline`, add it to `frontend/src/components/ui/Field.tsx` as a `<textarea>` branch that keeps the same label, hint and `aria-describedby` wiring, with `rows={6}` and `spellCheck={false}`, and nothing else changed.

The type `<Select>` keeps `disabled={connection !== undefined}` and `onChange={(event) => changeType(event.target.value as ConnectionType)}`; with `AVAILABLE_TYPES` now holding all three, no option renders disabled.

- [ ] **Step 5: Show the location per type and the blamed field**

In `frontend/src/features/admin/StorageAdmin.tsx`, add
`import { connectionSummary, fieldLabel } from "./connectionTypes";` next to the existing
`./ConnectionDialog` import, then replace the header `{m.storage.rootPath}` with `{m.storage.location}` and the cell:

```tsx
                  <Td className="font-mono">{connectionSummary(connection)}</Td>
```

and the test result line:

```tsx
                      {result && result !== "running" ? (
                        <span role="status" className={result.ok ? "text-success" : "text-danger"}>
                          {result.ok
                            ? m.storage.testOk
                            : m.storage.testFailedWith(
                                fieldLabel(connection.type, result.field),
                                result.detail,
                              )}
                        </span>
                      ) : null}
```

Widen `TestState` to `{ ok: boolean; detail: string; field?: string | null } | "running"`.

- [ ] **Step 6: Add the copy**

In the `storage` block of `frontend/src/messages.ts`, replace `typeLabels` and add the new strings:

```ts
    location: "Location",
    tenantId: "Tenant ID",
    tenantIdHint: "The Microsoft Entra ID directory (tenant) ID of the application.",
    clientId: "Client ID",
    clientIdHint: "The application (client) ID of the registered Entra ID application.",
    clientSecret: "Client secret",
    clientSecretHint:
      "The Entra ID client secret. Stored encrypted and never shown again. Client secrets expire; Test connection reports an expired one.",
    siteId: "Site ID",
    siteIdHint: "The shared SharePoint site all projects live on.",
    libraryId: "Document library (drive) ID",
    libraryIdHint:
      "The document library for this customer, inside the shared site. One connection per customer library.",
    sharedDriveId: "Shared Drive ID",
    sharedDriveIdHint: "The Google Shared Drive for this customer.",
    serviceAccountKey: "Service account JSON key",
    serviceAccountKeyHint:
      "Paste the whole JSON key file. Stored encrypted and never shown again. The service account must already be a Content manager on the Shared Drive.",
    secretRequired: (label: string) => `${label} is required.`,
    testFailedWith: (field: string | null, detail: string) =>
      field ? `Connection failed — check ${field}: ${detail}` : `Connection failed: ${detail}`,
    typeLabels: {
      localfs: "Local filesystem",
      sharepoint: "SharePoint / OneDrive",
      gdrive: "Google Drive",
    } as Record<string, string>,
```

- [ ] **Step 7: Run the tests to verify they pass**

Run from `frontend/`: `pnpm api:generate && pnpm test`
Expected: PASS, every test including the existing `StorageAdmin` and `UsersAdmin` suites.

Run: `pnpm lint && pnpm format:write && pnpm format && pnpm typecheck && pnpm build`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/features/admin src/messages.ts src/components/ui/Field.tsx src/lib/api/schema.d.ts
git commit -m "feat(admin): SharePoint and Google Drive connection forms

The type dropdown's cloud options are enabled and the fields switch with
the selected type inside the same dialog. Secrets are write-only: never
prefilled, never re-sent on an edit, never in the DOM. A failed Test
connection names the field to fix.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Opt-in live contract suite (wiring)

**Needs live credentials: partly.** The fixture, the skip logic and the documentation are written and committed without any credential, and the default test run is proven unchanged. What cannot be proven offline is the live branch itself: that the two adapters pass the shared contract suite against the real services. Running it is Task 9.

`backend/tests/storage/conftest.py` already says "Plan 3 adds SharePoint and Google Drive params as opt-in live tests". This task does exactly that.

**Files:**
- Modify: `backend/tests/storage/conftest.py`
- Create: `backend/tests/storage/live.py`
- Modify: `backend/.env.example`, `backend/README.md`
- Test: `backend/tests/storage/test_live_wiring.py`

**Interfaces:**
- Consumes: `SharePointBackend`, `GraphTokenProvider` (Task 4); `GoogleDriveBackend`, `ServiceAccountTokenProvider` (Task 3).
- Produces: `app`-free test helpers `tests.storage.live.LIVE_FLAG`, `live_enabled() -> bool`, `live_params() -> list[str]`, `require(name: str) -> str`, `sharepoint_backend(root: str)`, `gdrive_backend(root: str)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/storage/test_live_wiring.py`:

```python
"""The live suite must stay opt-in: an ordinary run is offline, free and parameterised on
localfs alone. These tests check the switch, not the live services."""

import pytest

from tests.storage import live


def test_live_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(live.LIVE_FLAG, raising=False)
    assert live.live_enabled() is False
    assert live.live_params() == []


@pytest.mark.parametrize("value", ["0", "", "true", "yes"])
def test_only_the_exact_flag_enables_live_tests(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """A half-set variable must not start charging money against a customer tenant."""
    monkeypatch.setenv(live.LIVE_FLAG, value)
    assert live.live_enabled() is False


def test_the_flag_adds_both_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(live.LIVE_FLAG, "1")
    assert live.live_params() == ["sharepoint", "gdrive"]


def test_a_missing_credential_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silently skipping would make a green run look like proof the adapters work."""
    monkeypatch.delenv("QC_LIVE_SP_TENANT_ID", raising=False)
    with pytest.raises(RuntimeError, match="QC_LIVE_SP_TENANT_ID"):
        live.require("QC_LIVE_SP_TENANT_ID")


def test_no_credential_value_is_committed() -> None:
    """The repository must never contain a tenant, site, drive id or key."""
    source = (live.__file__,)
    for path in source:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        assert "BEGIN PRIVATE KEY" not in text
        assert ".sharepoint.com," not in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/storage/test_live_wiring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.storage.live'`.

- [ ] **Step 3: Write the live helpers**

`backend/tests/storage/live.py`:

```python
"""Credentials and throwaway roots for the opt-in live storage contract suite (spec 15).

Nothing here holds a credential: every value comes from the environment of the person running
the suite, and a missing one fails loudly rather than skipping, so a green run never looks like
proof the adapters work. The suite writes under one throwaway folder per run and deletes it.
"""

import os
import uuid

from app.storage.gdrive import GoogleDriveBackend, ServiceAccountTokenProvider
from app.storage.sharepoint import GraphTokenProvider, SharePointBackend

LIVE_FLAG = "QC_AGENT_LIVE_STORAGE"
TEST_ROOT = "qc-agent-tests"


def live_enabled() -> bool:
    return os.environ.get(LIVE_FLAG) == "1"


def live_params() -> list[str]:
    return ["sharepoint", "gdrive"] if live_enabled() else []


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} must be set when {LIVE_FLAG}=1. See backend/README.md, 'Live storage tests'."
        )
    return value


def run_root() -> str:
    """One folder per run, so two people can run the suite against one site at once."""
    return f"{TEST_ROOT}-{uuid.uuid4().hex[:8]}"


def sharepoint_backend(root: str) -> SharePointBackend:
    tokens = GraphTokenProvider(
        require("QC_LIVE_SP_TENANT_ID"),
        require("QC_LIVE_SP_CLIENT_ID"),
        require("QC_LIVE_SP_CLIENT_SECRET"),
    )
    return SharePointBackend(
        require("QC_LIVE_SP_SITE_ID"), require("QC_LIVE_SP_DRIVE_ID"), root, tokens
    )


def gdrive_backend(root: str) -> GoogleDriveBackend:
    key_path = require("QC_LIVE_GDRIVE_SA_JSON_FILE")
    with open(key_path, encoding="utf-8") as handle:
        key_json = handle.read()
    return GoogleDriveBackend(
        require("QC_LIVE_GDRIVE_DRIVE_ID"),
        root,
        ServiceAccountTokenProvider(key_json),
        scope=f"live-{root}",
    )
```

The Google key is read from a **file path**, never from an environment variable holding the key itself, so the key does not end up in a shell history, a process listing or a CI log.

- [ ] **Step 4: Parameterise the contract suite**

Replace `backend/tests/storage/conftest.py`:

```python
"""Storage contract fixtures.

The suite runs on the local adapter in every test run. Setting ``QC_AGENT_LIVE_STORAGE=1`` adds
SharePoint and Google Drive, which need a real tenant and Shared Drive and the credentials
listed in backend/README.md. CI never sets it, so the default run is offline and free.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.storage.base import StorageBackend, StorageError
from app.storage.localfs import LocalFsBackend
from tests.storage import live


@pytest.fixture(params=["localfs", *live.live_params()])
async def backend(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[StorageBackend]:
    if request.param == "localfs":
        yield LocalFsBackend(tmp_path / "project-root")
        return
    root = live.run_root()
    adapter: StorageBackend = (
        live.sharepoint_backend(root)
        if request.param == "sharepoint"
        else live.gdrive_backend(root)
    )
    status = await adapter.health()
    if not status.ok:
        pytest.fail(f"Live {request.param} connection is not healthy: {status.detail}")
    try:
        yield adapter
    finally:
        # Each test gets its own run root; remove everything it wrote.
        for path in _written(adapter):
            try:
                await adapter.move_to_trash(path)
            except StorageError:
                pass


def _written(_adapter: StorageBackend) -> list[str]:
    """Paths the contract suite creates, so the live run leaves nothing behind."""
    return [
        "02-requirements/srs--customer-portal.docx",
        "05-testing/test-reports/test-report--sprint-1.md",
        "01-overview/other--tài liệu (bản cuối).md",
    ]
```

- [ ] **Step 5: Document the variables**

Append to `backend/.env.example` (names only, no values — these are not read by the application, only by the live test suite):

```bash
# Live storage tests (opt-in; see backend/README.md). Never commit values for these.
# QC_AGENT_LIVE_STORAGE=1
# QC_LIVE_SP_TENANT_ID=
# QC_LIVE_SP_CLIENT_ID=
# QC_LIVE_SP_CLIENT_SECRET=
# QC_LIVE_SP_SITE_ID=
# QC_LIVE_SP_DRIVE_ID=
# QC_LIVE_GDRIVE_DRIVE_ID=
# QC_LIVE_GDRIVE_SA_JSON_FILE=/absolute/path/to/service-account.json
```

Add a section to `backend/README.md` after "Tests":

```markdown
### Live storage tests (opt-in)

The storage contract suite runs on the local adapter in every test run. To run the same suite
against real SharePoint and Google Drive:

```bash
QC_AGENT_LIVE_STORAGE=1 uv run pytest tests/storage/test_contract.py -v
```

It needs a test document library on the shared SharePoint site and a test Shared Drive, and the
variables listed in `.env.example` under "Live storage tests". Two grants cannot be made from
the application and must be done by an administrator first: `Sites.Selected` **write** on the
SharePoint site for the registered Entra ID application, and the service account added to the
Shared Drive as **Content manager**. The suite writes under a throwaway folder per run and
removes what it wrote. CI never sets the flag, so pull requests stay offline and free.

Never put a credential in `.env`, in a shell history or in a commit: export the SharePoint
values in your shell for the run, and point `QC_LIVE_GDRIVE_SA_JSON_FILE` at a key file kept
outside the repository.
```
```

(The fenced block above is nested inside the README section; keep the README's own fences intact when pasting.)

- [ ] **Step 6: Prove the default run is unchanged**

Run: `uv run pytest tests/storage -v`
Expected: PASS; every `test_contract.py` test shows the `[localfs]` parameter only, and no other.

Run: `uv run pytest tests/storage/test_live_wiring.py -v`
Expected: PASS.

Run: `uv run ruff format . && uv run ruff check . && uv run mypy app && uv run pytest`
Expected: clean.

Run: `git grep -nE "BEGIN PRIVATE KEY|\.sharepoint\.com," -- backend frontend deploy templates`
Expected: only `tests/storage/test_live_wiring.py`'s own assertion and the synthetic
`example.sharepoint.com,33333333-…` site id in the test fixtures. Any other hit is a real value
that must be removed from the history before the commit.

- [ ] **Step 7: Commit**

```bash
git add tests/storage/conftest.py tests/storage/live.py tests/storage/test_live_wiring.py .env.example README.md
git commit -m "test(storage): run the contract suite on live storage behind an opt-in flag

QC_AGENT_LIVE_STORAGE=1 adds the sharepoint and gdrive params; without it
the suite is localfs only, so the default run and CI stay offline and
free. Credentials come from the environment, the Google key from a file
path, and a missing one fails loudly instead of skipping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Live verification on the real tenant and Shared Drive

**Needs live credentials: yes, entirely.** This task cannot start until IT has provisioned the test document library on the shared SharePoint site, the test Shared Drive, the Entra ID application with the `Sites.Selected` **write** grant on that site, and the service account added to the Shared Drive as Content manager (`docs/PENDING.md` section 3). Everything in Tasks 1–8 is already committed, reviewable and green without any of it.

**What the earlier tasks could not prove, and this task proves:**

| Assumption | Where it is assumed | Why offline tests cannot settle it |
|---|---|---|
| `msal.ConfidentialClientApplication.acquire_token_for_client` returns an app-only token that Graph accepts with a `Sites.Selected` grant | Task 4, `GraphTokenProvider` | The token comes from Entra ID; a fake msal object only proves our handling of the result. |
| Graph returns versions newest-first, and the id of a version stays the same after the next upload | Task 4, `list_versions`, `put_file` | Ordering and id stability are Graph behaviour, not ours. The contract suite asserts them. |
| A SharePoint library with versioning turned off really makes the probe see fewer than two versions | Task 4, `_probe_write_and_versioning` | Needs a library with the setting changed. |
| An upload session accepts 1,638,400-byte chunks and returns the finished item on the last chunk | Task 4, `_upload_session` | Graph's chunk rules and final response are server behaviour. |
| A service-account key mints a token that Drive accepts for a Shared Drive it is a Content manager on | Task 3, `ServiceAccountTokenProvider` | Needs Google's token endpoint and a real membership. |
| `files.update` creates a revision, `keepForever` is accepted, and an old revision is still downloadable | Task 3, `put_file`, `get_version` | Revision behaviour is Drive's. |
| Drive returns 403 with a quota reason under throttling rather than another shape | Task 1, `DRIVE_POLICY` | Only observable under real load; record what is seen. |
| `size` is present on Drive revisions and on Graph versions for the files we write | Tasks 3 and 4, `list_versions` | The contract suite asserts `size > 0`. |

**Files:**
- Create: `docs/superpowers/spikes/2026-10-plan-3b-live-results.md`
- Modify: whichever adapter file a live failure proves wrong, with the offline test that reproduces it added first.

- [ ] **Step 1: Confirm the prerequisites are in place**

Ask IT to confirm, and record the answers in the results file (names of the grants, not their values):

1. An Entra ID application exists with application permission `Sites.Selected`, admin-consented.
2. That application has a **write** grant on the shared SharePoint site.
3. A document library exists on that site for testing, with version history **enabled**.
4. A Google Cloud service account exists, the Drive API is enabled, and the account is a **Content manager** on a test Shared Drive.

Export the variables from `backend/.env.example` in your shell for this session only, and point `QC_LIVE_GDRIVE_SA_JSON_FILE` at a key file outside the repository.

- [ ] **Step 2: Run the contract suite against SharePoint**

Run from `backend/`:

```bash
QC_AGENT_LIVE_STORAGE=1 uv run pytest tests/storage/test_contract.py -v -k sharepoint
```

Expected: every test passes with the `[sharepoint]` parameter.

If `test_overwrite_keeps_versions` fails on ordering or on version ids, that is the Graph assumption in the table above. Write the offline test that reproduces the real shape with `httpx.MockTransport` **first**, watch it fail, then fix `SharePointBackend.list_versions` / `put_file`, then re-run both.

- [ ] **Step 3: Run the contract suite against Google Drive**

Run:

```bash
QC_AGENT_LIVE_STORAGE=1 uv run pytest tests/storage/test_contract.py -v -k gdrive
```

Expected: every test passes with the `[gdrive]` parameter.

- [ ] **Step 4: Verify the health diagnoses against reality**

With the same shell, run a one-off check per diagnosis and record what came back. Each is a deliberate single wrong value; none of them is committed:

```bash
QC_AGENT_LIVE_STORAGE=1 uv run python - <<'PY'
import asyncio, os
from tests.storage import live

async def main() -> None:
    sp = live.sharepoint_backend("qc-agent-tests-health")
    print("sharepoint ok:", await sp.health())
    gd = live.gdrive_backend("qc-agent-tests-health")
    print("gdrive ok:", await gd.health())
    os.environ["QC_LIVE_SP_SITE_ID"] = "contoso.sharepoint.com,00000000-0000-0000-0000-000000000000,0000"
    print("wrong site id:", await live.sharepoint_backend("x").health())
    os.environ["QC_LIVE_GDRIVE_DRIVE_ID"] = "0ADoesNotExist"
    print("wrong Shared Drive id:", await live.gdrive_backend("x").health())

asyncio.run(main())
PY
```

Expected: the healthy cases print `ok=True`; the wrong-id cases print `ok=False` with `field='site_id'` and `field='drive_id'` and the messages from Tasks 3 and 4. Then ask IT to turn version history **off** on the test library, re-run the first line, confirm `field='drive_id'` with the versioning message, and ask IT to turn it back on.

- [ ] **Step 5: Observe throttling at least once**

Run the suite twice in parallel against the same library and Shared Drive and check the application log for `transport error` or the retry warnings from `app.storage.retry`. Record whether Graph sent `Retry-After` and in what unit, and what shape Drive's quota error had. If Drive's quota reason is not one of the three in `DRIVE_QUOTA_REASONS`, add the observed reason — with an offline test for it first.

- [ ] **Step 6: Record the results**

`docs/superpowers/spikes/2026-10-plan-3b-live-results.md`: one section per service, listing for each row of the table above what was observed, and a final section "Deviations fixed" naming each adapter change the live run forced, with the offline test that now covers it. **No tenant id, site id, drive id, client id, secret, key or URL containing any of them.** Refer to them as "the test library" and "the test Shared Drive".

- [ ] **Step 7: Confirm the offline suite is still green and clean up**

Run: `uv run pytest` (without the flag)
Expected: PASS, unchanged, no network.

Run: `git grep -nE "BEGIN PRIVATE KEY|\.sharepoint\.com," -- backend frontend deploy templates`
Expected: the same two hits as in Task 8 and nothing else. In particular the results file
written in Step 6 must produce no hit.

Delete any folder the runs left in the test library and the test Shared Drive.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/spikes/2026-10-plan-3b-live-results.md backend/app/storage backend/tests/storage
git commit -m "test(storage): verify both cloud adapters against live SharePoint and Drive

The shared contract suite passes with QC_AGENT_LIVE_STORAGE=1 on a test
document library and a test Shared Drive. Results recorded with no tenant,
site, drive or key values; each deviation the live run exposed is covered
by an offline test first.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Deferred, with where it goes

- An index on `(storage->>'connection_id', lower(storage->>'root'))` for project lookups — Plan 3c, where storage migration makes the lookup hot (`docs/PENDING.md`).
- `PATCH /storage-connections/{id}` cannot both reactivate and set default in one call (`set_default` runs first and refuses an inactive connection) — Plan 3c, with the migration UI that needs it.
- Showing the last health result on the Admin → Storage page without pressing Test connection (spec 8.6) needs a stored result per connection — Plan 6, with the operations work; today the page shows the result of the test the admin ran.
- Changing a project's storage from one connection to another, including SharePoint → Drive — Plan 3c.
