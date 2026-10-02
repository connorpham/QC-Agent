"""SharePoint adapter over Microsoft Graph. Scripted transport only; no network, no tenant."""

import httpx
import pytest

from app.storage.base import (
    HealthStatus,
    StorageAuthError,
    StorageNotFound,
    StoragePathError,
)
from app.storage.sharepoint import (
    CHUNK_BYTES,
    FIELD_DRIVE_GRANT,
    FIELD_DRIVE_ID,
    FIELD_VERSIONING,
    LIBRARY_NO_GRANT,
    LIBRARY_NOT_FOUND,
    SIMPLE_UPLOAD_LIMIT,
    VERSIONING_OFF,
    SharePointBackend,
)

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
    return {
        "id": item_id,
        "name": "srs--customer-portal.docx",
        "webUrl": "https://example.invalid/x",
    }


# -- addressing ----------------------------------------------------------------------------


async def test_a_drive_id_containing_a_slash_cannot_retarget_the_request() -> None:
    """The configuration schema already refuses a drive id with a slash in it (finding 7), but
    the adapter must not rely on that alone: a hostile drive id reaching this layer by any other
    path must still be quoted, not interpreted as a path separator that lets it address something
    other than the configured library."""
    script = Script().on("PUT", httpx.Response(201, json=_item()))
    hostile_drive_id = "../another-customers-library"
    backend = SharePointBackend(
        SITE_ID,
        hostile_drive_id,
        "",
        FakeTokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(script.handler)),
        sleep=_no_sleep,
    )
    await backend.exists(PATH)  # the script's unmatched-request default (404) is enough here
    assert script.requests
    sent = str(script.requests[0].url)
    # The hostile id must not be able to consume the structural "/drives/" segment of the path
    # (httpx itself resolves a literal ".." against the URL, so this is a real path-traversal
    # risk, not just a cosmetic one): the segment right after "/drives/" must be exactly the
    # quoted id, with no unescaped "/" inside it.
    assert "/drives/" in sent
    drive_segment = sent.split("/drives/", 1)[1].split("/root:", 1)[0]
    assert "/" not in drive_segment


async def test_a_site_id_containing_a_slash_cannot_retarget_the_request() -> None:
    script = (
        Script()
        .on("PUT", httpx.Response(201, json=_item()))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
    )
    hostile_site_id = "../another-customers-site"
    backend = SharePointBackend(
        hostile_site_id,
        DRIVE_ID,
        "",
        FakeTokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(script.handler)),
        sleep=_no_sleep,
    )
    await backend.health()
    sent = str(script.requests[0].url)
    assert "/sites/" in sent
    site_segment = sent.split("/sites/", 1)[1].split("?", 1)[0]
    assert "/" not in site_segment


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


async def test_special_characters_are_percent_encoded() -> None:
    """A literal '#', '%' or ':' in a file name must be percent-encoded - a colon especially,
    since it is Graph's own addressing delimiter and a literal one would corrupt the path."""
    script = (
        Script()
        .on("PUT", httpx.Response(201, json=_item()))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
    )
    backend = _backend(script)
    await backend.put_file("01-overview/100% done #2: final.md", b"x", "text/markdown")
    url = str(script.requests[0].url)
    assert "%23" in url  # '#'
    assert "%25" in url  # '%'
    assert "%3A" in url  # ':'
    assert "root:/" in url  # the structural delimiters are untouched


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


async def test_file_exactly_at_the_upload_limit_uses_a_single_put() -> None:
    """The boundary belongs to the simple path: only a file strictly larger than
    SIMPLE_UPLOAD_LIMIT should go through an upload session."""
    script = (
        Script()
        .on("PUT", httpx.Response(201, json=_item()))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
    )
    backend = _backend(script)
    await backend.put_file(PATH, b"x" * SIMPLE_UPLOAD_LIMIT, "application/octet-stream")
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
    # A file goes through an upload session when it exceeds SIMPLE_UPLOAD_LIMIT, regardless of
    # how that relates to CHUNK_BYTES; this file is sized off the upload threshold, not the
    # chunk size, so it genuinely exercises the session path with a non-trivial last chunk.
    size = SIMPLE_UPLOAD_LIMIT + CHUNK_BYTES + 100
    await backend.put_file(PATH, b"x" * size, "application/octet-stream")
    chunks = [r for r in script.requests if str(r.url) == session_url]
    expected_chunks = -(-size // CHUNK_BYTES)  # ceiling division
    assert len(chunks) == expected_chunks
    offset = 0
    for index, chunk in enumerate(chunks):
        is_last = index == len(chunks) - 1
        chunk_len = (size - offset) if is_last else CHUNK_BYTES
        assert chunk.headers["Content-Range"] == f"bytes {offset}-{offset + chunk_len - 1}/{size}"
        if not is_last:
            assert chunk_len == CHUNK_BYTES  # every chunk but the last is exactly CHUNK_BYTES
        offset += chunk_len
    assert offset == size  # every byte covered exactly once: no gap, no overlap
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
        .on(
            "/versions/1.0/content",
            httpx.Response(302, headers={"Location": "https://cdn.invalid/blob"}),
        )
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
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(DRIVE_PREFIX, httpx.Response(404, json={}))
    )
    status = await no_library.health()
    assert status.ok is False and status.field == "drive_id"
    assert "document library" in status.detail


async def test_health_distinguishes_forbidden_from_not_found_on_the_drive_stage() -> None:
    """A 403 on the library itself must not be folded into "library not found": the natural next
    action on that message is to paste a different library id, and on a site shared by every
    customer, every other library belongs to another customer. A 403 means the application lacks
    a grant to this one; a 404 means the id does not resolve at all - different faults, different
    fields, different messages, never a substring in common to accidentally satisfy both checks
    at once (finding 6)."""
    site_ok = httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"})

    forbidden = await _backend(
        Script().on(f"/sites/{SITE_ID}", site_ok).on(DRIVE_PREFIX, httpx.Response(403, json={}))
    ).health()
    not_found = await _backend(
        Script().on(f"/sites/{SITE_ID}", site_ok).on(DRIVE_PREFIX, httpx.Response(404, json={}))
    ).health()

    assert forbidden.ok is False and not_found.ok is False
    assert forbidden.field == FIELD_DRIVE_GRANT
    assert not_found.field == FIELD_DRIVE_ID
    assert forbidden.field != not_found.field
    assert forbidden.detail == LIBRARY_NO_GRANT
    assert not_found.detail == LIBRARY_NOT_FOUND
    assert forbidden.detail != not_found.detail


async def test_health_rejects_a_library_from_another_site() -> None:
    """A drive id pasted from a different site must be caught here, not at the first upload."""
    script = (
        Script()
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(
            DRIVE_PREFIX,
            httpx.Response(
                200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/other/Docs"}
            ),
        )
    )
    status = await _backend(script).health()
    assert status.ok is False and status.field == "drive_id_wrong_site"
    assert "does not belong" in status.detail


async def test_health_reports_no_write_permission() -> None:
    """A 401/403 here must be diagnosed as a write-grant problem, not collapsed into the
    generic site-access message - a real defect where ``send_with_retry`` auto-raised on
    401/403 before the adapter ever saw the status, so every stage reported the same thing."""
    script = (
        Script()
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(
            DRIVE_PREFIX + "?",
            httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}),
        )
        .on("PUT", httpx.Response(403, json={}))
    )
    status = await _backend(script).health(probe_write=True)
    assert status.ok is False and status.field == "write_grant"
    assert "write" in status.detail and "Sites.Selected" in status.detail


async def test_health_reports_versioning_disabled() -> None:
    """A library with version history off would silently lose the history we record (spec 8.2)."""
    script = (
        Script()
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(
            DRIVE_PREFIX + "?",
            httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}),
        )
        .on("PUT", httpx.Response(201, json=_item("probe-1")))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
        .on("DELETE", httpx.Response(204))
    )
    status = await _backend(script).health(probe_write=True)
    assert status.ok is False and status.field == "versioning"
    assert "Version history" in status.detail
    assert [r for r in script.requests if r.method == "DELETE"]  # no litter even when it fails


async def test_health_versioning_lookup_transport_error_is_not_reported_as_disabled() -> None:
    """A failed version lookup must not be reported as the specific, confident "version history
    is disabled" message - that belongs only to a successful lookup that genuinely found fewer
    than two versions. A transport error during the lookup itself is the last stage's own
    failure, distinct from a genuinely disabled library (finding 5)."""
    site_response = httpx.Response(
        200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}
    )
    drive_response = httpx.Response(
        200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        target = f"{request.method} {request.url}"
        if f"/sites/{SITE_ID}" in target:
            return site_response
        if target.startswith(f"GET {DRIVE_PREFIX}?"):
            return drive_response
        if request.method == "PUT":
            return httpx.Response(201, json=_item("probe-1"))
        if "/versions" in target:
            raise httpx.ConnectError("boom")
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={})

    backend = SharePointBackend(
        SITE_ID,
        DRIVE_ID,
        "",
        FakeTokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
    )
    status = await backend.health(probe_write=True)
    assert status.ok is False
    assert status.field != FIELD_VERSIONING
    assert status.detail != VERSIONING_OFF


async def test_health_versioning_lookup_exhausted_retries_is_not_reported_as_disabled() -> None:
    """Retries exhausted under sustained throttling during the version lookup is also the last
    stage's own failure, not evidence that versioning is off (finding 5)."""
    site_response = httpx.Response(
        200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}
    )
    drive_response = httpx.Response(
        200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        target = f"{request.method} {request.url}"
        if f"/sites/{SITE_ID}" in target:
            return site_response
        if target.startswith(f"GET {DRIVE_PREFIX}?"):
            return drive_response
        if request.method == "PUT":
            return httpx.Response(201, json=_item("probe-1"))
        if "/versions" in target:
            return httpx.Response(429, headers={"Retry-After": "0"})  # throttled, every attempt
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={})

    backend = SharePointBackend(
        SITE_ID,
        DRIVE_ID,
        "",
        FakeTokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
    )
    status = await backend.health(probe_write=True)
    assert status.ok is False
    assert status.field != FIELD_VERSIONING
    assert status.detail != VERSIONING_OFF


async def test_health_every_stage_reports_a_distinct_field() -> None:
    """Walk every diagnosable stage and check its field is unique.

    This is the test that should have caught fix round 1's defect: ``send_with_retry`` raised
    ``StorageAuthError`` on every 401/403 before the adapter's own stage code ever saw the
    response, so the drive-probe and write-probe branches below were unreachable and both fell
    through to the same generic message - while still reporting a field value that happened to
    be "correct" by coincidence, which is exactly why asserting on message substrings alone (the
    previous version of this test) could not catch it. Asserting that two stages never share a
    field would have failed immediately.
    """
    site_ok = httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"})
    drive_ok = httpx.Response(
        200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}
    )
    scenarios: list[tuple[str, SharePointBackend]] = [
        ("credentials rejected", _backend(Script(), FakeTokens(fail=True))),
        (
            "site not found",
            _backend(Script().on(f"/sites/{SITE_ID}", httpx.Response(404, json={}))),
        ),
        (
            "library not found",
            _backend(
                Script()
                .on(f"/sites/{SITE_ID}", site_ok)
                .on(DRIVE_PREFIX, httpx.Response(404, json={}))
            ),
        ),
        (
            "library access forbidden",
            _backend(
                Script()
                .on(f"/sites/{SITE_ID}", site_ok)
                .on(DRIVE_PREFIX, httpx.Response(403, json={}))
            ),
        ),
        (
            "library belongs to another site",
            _backend(
                Script()
                .on(f"/sites/{SITE_ID}", site_ok)
                .on(
                    DRIVE_PREFIX,
                    httpx.Response(
                        200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/other/Docs"}
                    ),
                )
            ),
        ),
        (
            "missing write grant",
            _backend(
                Script()
                .on(f"/sites/{SITE_ID}", site_ok)
                .on(DRIVE_PREFIX + "?", drive_ok)
                .on("PUT", httpx.Response(403, json={}))
            ),
        ),
        (
            "versioning disabled",
            _backend(
                Script()
                .on(f"/sites/{SITE_ID}", site_ok)
                .on(DRIVE_PREFIX + "?", drive_ok)
                .on("PUT", httpx.Response(201, json=_item("probe-1")))
                .on("/versions", httpx.Response(200, json={"value": [{"id": "1.0"}]}))
                .on("DELETE", httpx.Response(204))
            ),
        ),
    ]
    fields: list[str | None] = []
    for name, backend in scenarios:
        # probe_write=True: this walks the write-grant and versioning stages too, which only
        # run for the admin-only full probe.
        status = await backend.health(probe_write=True)
        assert status.ok is False, f"{name} unexpectedly reported healthy"
        assert status.field is not None, f"{name} reported no field at all"
        fields.append(status.field)
    assert len(set(fields)) == len(fields), f"two stages shared a field: {fields}"


async def test_health_cleans_up_its_probe_when_the_second_write_fails() -> None:
    """A failure partway through the probe (first write ok, second rejected) must not leave the
    first write behind in the customer's library. ``Script`` always returns the same response
    for a given match, so this test scripts the two PUTs by hand instead."""
    site_response = httpx.Response(
        200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}
    )
    drive_response = httpx.Response(
        200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}
    )
    write_responses = [httpx.Response(201, json=_item("probe-1")), httpx.Response(403, json={})]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        target = f"{request.method} {request.url}"
        if f"/sites/{SITE_ID}" in target:
            return site_response
        if target.startswith(f"GET {DRIVE_PREFIX}?"):
            return drive_response
        if request.method == "PUT":
            return write_responses.pop(0)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={})

    backend = SharePointBackend(
        SITE_ID,
        DRIVE_ID,
        "",
        FakeTokens(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=_no_sleep,
    )
    status = await backend.health(probe_write=True)
    assert status.ok is False and status.field == "write_grant"
    deletes = [r for r in requests if r.method == "DELETE"]
    assert deletes and "probe-1" in str(deletes[0].url)


async def test_health_is_ok_and_cleans_up_its_probe() -> None:
    script = (
        Script()
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(
            DRIVE_PREFIX + "?",
            httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}),
        )
        .on("PUT", httpx.Response(201, json=_item("probe-1")))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "2.0"}, {"id": "1.0"}]}))
        .on("DELETE", httpx.Response(204))
    )
    backend = _backend(script)
    assert await backend.health(probe_write=True) == HealthStatus(ok=True, detail="ok")
    assert [r for r in script.requests if r.method == "DELETE"]


async def test_health_probe_result_is_cached() -> None:
    script = (
        Script()
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(
            DRIVE_PREFIX + "?",
            httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}),
        )
        .on("PUT", httpx.Response(201, json=_item("probe-1")))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "2.0"}, {"id": "1.0"}]}))
        .on("DELETE", httpx.Response(204))
    )
    backend = _backend(script)
    await backend.health(probe_write=True)
    writes = len([r for r in script.requests if r.method == "PUT"])
    await backend.health(probe_write=True)
    assert len([r for r in script.requests if r.method == "PUT"]) == writes  # no second probe


async def test_the_public_health_check_never_writes() -> None:
    """The unauthenticated ``/health`` endpoint uses ``health()``'s default, ``probe_write=False``.
    It must never write, create or delete anything in the customer's library - checked here by
    asserting what requests were actually made, not by excluding one method name: every request
    the probe issues must be a plain ``GET``."""
    script = (
        Script()
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(
            DRIVE_PREFIX + "?",
            httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}),
        )
    )
    backend = _backend(script)
    status = await backend.health()
    assert status == HealthStatus(ok=True, detail="ok")
    assert script.requests  # the probe did run
    assert {request.method for request in script.requests} == {"GET"}


async def test_the_write_probe_requires_explicit_opt_in() -> None:
    """A read-only check and a full check of the same connection must not share a cache slot:
    an admin's write probe must still run in full even if the public check already ran and
    cached an ``ok``, and vice versa."""
    script = (
        Script()
        .on(
            f"/sites/{SITE_ID}",
            httpx.Response(200, json={"id": SITE_ID, "webUrl": "https://c.invalid/sites/qc"}),
        )
        .on(
            DRIVE_PREFIX + "?",
            httpx.Response(200, json={"id": DRIVE_ID, "webUrl": "https://c.invalid/sites/qc/Docs"}),
        )
        .on("PUT", httpx.Response(201, json=_item("probe-1")))
        .on("/versions", httpx.Response(200, json={"value": [{"id": "2.0"}, {"id": "1.0"}]}))
        .on("DELETE", httpx.Response(204))
    )
    backend = _backend(script)
    await backend.health()  # read-only; cached under its own key
    assert not [r for r in script.requests if r.method in ("PUT", "DELETE")]
    status = await backend.health(probe_write=True)
    assert status == HealthStatus(ok=True, detail="ok")
    assert [r for r in script.requests if r.method == "PUT"]
    assert [r for r in script.requests if r.method == "DELETE"]


async def test_health_message_never_contains_a_token_or_a_provider_body() -> None:
    script = Script().on(f"/sites/{SITE_ID}", httpx.Response(500, text="Bearer test-token echoed"))
    status = await _backend(script).health()
    assert status.ok is False
    assert "test-token" not in status.detail and "Bearer" not in status.detail
