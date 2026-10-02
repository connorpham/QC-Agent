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
    MULTIPART_LIMIT,
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


def _is_drive_chunk_upload(request: httpx.Request) -> bool:
    """The one request any test in this file is allowed to send without
    ``supportsAllDrives=true``: the PUT of file bytes to the resumable session URL Drive hands
    back from the request that started the session. That URL already carries the Shared Drive
    context (and Drive's resumable protocol takes no query parameters on the chunk PUT itself),
    so this is a real exemption, not a gap.

    Identified by the ``upload_id`` query parameter Drive puts on every session URL it issues —
    deliberately not by HTTP method, since excluding a method is exactly what let the original
    bug (a PATCH missing the flag) hide inside a per-test assertion.
    """
    return "upload_id=" in str(request.url)


class Script:
    """Records every request and replies from a list of (predicate, response) rules.

    Also enforces, for every request any test in this file sends, that it stays scoped to the
    configured Shared Drive via ``supportsAllDrives=true`` (the one exemption is
    ``_is_drive_chunk_upload``). The check lives here — where every Drive request passes through
    in tests — rather than as an assertion inside one test, so a new adapter method cannot
    quietly escape it just because the test that exercises it doesn't happen to check.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[object, httpx.Response]] = []
        self.requests: list[httpx.Request] = []

    def on(self, match: str, response: httpx.Response) -> "Script":
        self.rules.append((match, response))
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not _is_drive_chunk_upload(request):
            assert "supportsAllDrives=true" in str(request.url), (
                f"missing supportsAllDrives=true on {request.method} {request.url}"
            )
        target = f"{request.method} {request.url}"
        for match, response in self.rules:
            if isinstance(match, str) and match in target:
                return response
        return httpx.Response(404, json={"error": {"code": 404, "message": "not found"}})


async def _no_sleep(_seconds: float) -> None:
    return None


def _backend(
    script: Script, tokens: FakeTokens | None = None, root: str = ""
) -> GoogleDriveBackend:
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
        .on(
            "POST https://www.googleapis.com/drive/v3/files?",
            httpx.Response(200, json={"id": "f-1"}),
        )
        .on(
            "uploadType=multipart",
            httpx.Response(200, json={"id": "f-1", "headRevisionId": "r1"}),
        )
        .on("/revisions/", httpx.Response(200, json={"id": "r1", "keepForever": True}))
    )
    backend = _backend(script)
    stored = await backend.put_file(PATH, b"v1", "application/octet-stream")
    assert stored.item_id and stored.version_id
    uploads = [r for r in script.requests if "/upload/drive/v3/files" in str(r.url)]
    assert len(uploads) == 1
    assert "uploadType=multipart" in str(uploads[0].url)
    # supportsAllDrives=true on every request (except the resumable chunk PUT) is enforced
    # globally by Script.handler, not by an assertion local to this test.


async def test_every_request_stays_inside_the_configured_drive() -> None:
    """One connection is one customer's Shared Drive; nothing may address another."""
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on(
            "POST https://www.googleapis.com/drive/v3/files?",
            httpx.Response(200, json={"id": "f-1"}),
        )
        .on(
            "uploadType=multipart",
            httpx.Response(200, json={"id": "f-1", "headRevisionId": "r1"}),
        )
        .on("/revisions/", httpx.Response(200, json={"id": "r1", "keepForever": True}))
    )
    backend = _backend(script)
    await backend.put_file(PATH, b"v1", "text/plain")
    for request in script.requests:
        drive_param = request.url.params.get("driveId")
        assert drive_param in (None, DRIVE_ID)
        assert "drives/" not in str(request.url) or f"drives/{DRIVE_ID}" in str(request.url)


async def test_a_file_of_exactly_the_multipart_limit_still_uses_multipart() -> None:
    """The boundary is inclusive: MULTIPART_LIMIT bytes is still small enough for multipart."""
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on(
            "POST https://www.googleapis.com/drive/v3/files?",
            httpx.Response(200, json={"id": "f-1"}),
        )
        .on(
            "uploadType=multipart",
            httpx.Response(200, json={"id": "f-1", "headRevisionId": "r1"}),
        )
        .on("/revisions/", httpx.Response(200, json={"id": "r1", "keepForever": True}))
    )
    backend = _backend(script)
    stored = await backend.put_file(PATH, b"x" * MULTIPART_LIMIT, "application/octet-stream")
    assert stored.item_id and stored.version_id
    uploads = [r for r in script.requests if "/upload/drive/v3/files" in str(r.url)]
    assert len(uploads) == 1
    assert "uploadType=multipart" in str(uploads[0].url)
    assert not any("uploadType=resumable" in str(r.url) for r in script.requests)


async def test_large_files_use_a_resumable_upload() -> None:
    session_url = "https://www.googleapis.com/upload/drive/v3/files?upload_id=abc"
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on(
            "POST https://www.googleapis.com/drive/v3/files?",
            httpx.Response(200, json={"id": "f-1"}),
        )
        .on("uploadType=resumable", httpx.Response(200, headers={"Location": session_url}))
        .on(session_url, httpx.Response(200, json={"id": "f-1", "headRevisionId": "r2"}))
        .on("/revisions/", httpx.Response(200, json={"id": "r2", "keepForever": True}))
    )
    backend = _backend(script)
    size = 6 * 1024 * 1024  # larger than MULTIPART_LIMIT outright, not a multiple of any chunk
    await backend.put_file(PATH, b"x" * size, "application/octet-stream")
    assert any("uploadType=resumable" in str(r.url) for r in script.requests)
    # The adapter sends the whole file as one PUT (no chunking constant to respect), so the
    # single Content-Range must cover bytes 0..size-1 of size with no gap and no overlap.
    puts = [r for r in script.requests if r.method == "PUT"]
    assert len(puts) == 1
    assert puts[0].headers["Content-Range"] == f"bytes 0-{size - 1}/{size}"


async def test_a_new_version_updates_the_existing_file_id() -> None:
    script = Script().on(
        "GET https://www.googleapis.com/drive/v3/files?",
        _list([_folder("f-req", "02-requirements")]),
    )
    script.rules.insert(
        0,
        (
            # httpx form-encodes a space in a query value as "+", not "%20"; match the quoted
            # literal only so this does not depend on that encoding detail.
            "%27srs--customer-portal.docx%27",
            _list(
                [
                    {
                        "id": "file-1",
                        "name": "srs--customer-portal.docx",
                        "mimeType": "application/octet-stream",
                    }
                ]
            ),
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
        .on(
            "POST https://www.googleapis.com/drive/v3/files?",
            httpx.Response(200, json={"id": "f-1"}),
        )
        .on(
            "uploadType=multipart",
            httpx.Response(200, json={"id": "f-1", "headRevisionId": "r1"}),
        )
    )
    backend = _backend(script)
    await backend.put_file("_reports/gap-report.md", b"# gaps", "text/markdown")
    await backend.put_file("project.yaml", b"name: demo", "text/yaml")
    assert not [r for r in script.requests if "/revisions/" in str(r.url)]


async def test_keep_forever_exemption_matches_project_yaml_exactly() -> None:
    """A path that merely starts with "project.yaml" is a different file and is not exempt."""
    script = (
        Script()
        .on("GET https://www.googleapis.com/drive/v3/files?", _list([]))
        .on(
            "POST https://www.googleapis.com/drive/v3/files?",
            httpx.Response(200, json={"id": "f-1"}),
        )
        .on(
            "uploadType=multipart",
            httpx.Response(200, json={"id": "f-1", "headRevisionId": "r1"}),
        )
        .on("/revisions/", httpx.Response(200, json={"id": "r1", "keepForever": True}))
    )
    backend = _backend(script)
    await backend.put_file("project.yamlx", b"not actually the project file", "text/yaml")
    assert [r for r in script.requests if "/revisions/" in str(r.url)]


async def test_versions_are_listed_oldest_first() -> None:
    revisions = {
        "revisions": [
            {"id": "r1", "size": "2", "modifiedTime": "2026-10-01T10:00:00.000Z"},
            {"id": "r2", "size": "2", "modifiedTime": "2026-10-02T10:00:00.000Z"},
        ]
    }
    script = (
        Script()
        # httpx form-encodes a space in a query value as "+", not "%20"; match the quoted
        # literal only so this does not depend on that encoding detail.
        .on("%2702-requirements%27", _list([_folder("f-req", "02-requirements")]))
        .on(
            "GET https://www.googleapis.com/drive/v3/files?",
            _list(
                [
                    {
                        "id": "file-1",
                        "name": "srs--customer-portal.docx",
                        "mimeType": "application/octet-stream",
                    }
                ]
            ),
        )
        .on("/revisions?", httpx.Response(200, json=revisions))
    )
    backend = _backend(script)
    versions = await backend.list_versions(PATH)
    assert [v.version_id for v in versions] == ["r1", "r2"]
    assert versions[0].modified_at < versions[1].modified_at
    assert all(v.size == 2 for v in versions)


async def test_get_version_downloads_a_specific_revision() -> None:
    script = (
        Script()
        .on("%2702-requirements%27", _list([_folder("f-req", "02-requirements")]))
        .on(
            "GET https://www.googleapis.com/drive/v3/files?",
            _list(
                [
                    {
                        "id": "file-1",
                        "name": "srs--customer-portal.docx",
                        "mimeType": "application/octet-stream",
                    }
                ]
            ),
        )
        .on("/revisions/r1?", httpx.Response(200, content=b"old content"))
    )
    backend = _backend(script)
    assert await backend.get_version(PATH, "r1") == b"old content"


async def test_get_version_missing_revision_raises_not_found() -> None:
    script = (
        Script()
        .on("%2702-requirements%27", _list([_folder("f-req", "02-requirements")]))
        .on(
            "GET https://www.googleapis.com/drive/v3/files?",
            _list(
                [
                    {
                        "id": "file-1",
                        "name": "srs--customer-portal.docx",
                        "mimeType": "application/octet-stream",
                    }
                ]
            ),
        )
        .on("/revisions/does-not-exist?", httpx.Response(404, json={"error": {"code": 404}}))
    )
    backend = _backend(script)
    with pytest.raises(StorageNotFound):
        await backend.get_version(PATH, "does-not-exist")


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
        # httpx form-encodes a space in a query value as "+", not "%20"; match the quoted
        # literal only so this does not depend on that encoding detail.
        .on("%2702-requirements%27", _list([_folder("f-req", "02-requirements")]))
        .on(
            "GET https://www.googleapis.com/drive/v3/files?",
            _list(
                [
                    {
                        "id": "file-1",
                        "name": "srs--customer-portal.docx",
                        "mimeType": "application/octet-stream",
                    }
                ]
            ),
        )
        .on("PATCH", httpx.Response(200, json={"id": "file-1"}))
    )
    backend = _backend(script)
    await backend.move_to_trash(PATH)
    patch = [r for r in script.requests if r.method == "PATCH"][-1]
    # json.dumps has no space after the colon by default; check the parsed body rather than
    # a literal byte string so this does not depend on that formatting detail.
    assert json.loads(patch.read()) == {"trashed": True}


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
    assert status.ok is False and status.field == "not_member"
    assert "Content manager" in status.detail  # the membership grant IT must make

    read_only = _backend(
        Script().on(
            f"drives/{DRIVE_ID}",
            httpx.Response(
                200,
                json={
                    "id": DRIVE_ID,
                    "name": "Customer",
                    "capabilities": {"canAddChildren": False},
                },
            ),
        )
    )
    status = await read_only.health()
    assert status.ok is False and status.field == "write_grant"
    assert "Content manager" in status.detail


async def test_health_stages_are_genuinely_distinguishable() -> None:
    """Guards against the shape of bug where a shared exception path collapses every stage
    into the same (field, detail), which a substring assertion alone would not catch: two
    stages could report identically and every ``in`` check above would still pass."""
    rejected = await _backend(Script(), FakeTokens(fail=True)).health()
    missing = await _backend(
        Script().on(f"drives/{DRIVE_ID}", httpx.Response(404, json={}))
    ).health()
    forbidden = await _backend(
        Script().on(f"drives/{DRIVE_ID}", httpx.Response(403, json={}))
    ).health()
    read_only = await _backend(
        Script().on(
            f"drives/{DRIVE_ID}",
            httpx.Response(
                200,
                json={
                    "id": DRIVE_ID,
                    "name": "Customer",
                    "capabilities": {"canAddChildren": False},
                },
            ),
        )
    ).health()
    keep_forever_script = Script().on(
        f"drives/{DRIVE_ID}",
        httpx.Response(
            200, json={"id": DRIVE_ID, "name": "Customer", "capabilities": {"canAddChildren": True}}
        ),
    )
    keep_forever_backend = _backend(keep_forever_script)
    keep_forever_backend.note_keep_forever_limit(PATH, KEEP_FOREVER_LIMIT)
    keep_forever = await keep_forever_backend.health()

    fields = [
        rejected.field,
        missing.field,
        forbidden.field,
        read_only.field,
        keep_forever.field,
    ]
    assert fields == ["secret", "drive_id", "not_member", "write_grant", "keep_forever"]
    assert len(set(fields)) == len(fields)  # no two stages share a token
    details = [
        rejected.detail,
        missing.detail,
        forbidden.detail,
        read_only.detail,
        keep_forever.detail,
    ]
    assert len(set(details)) == len(details)  # and no two stages share a message either


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
    assert status.ok is False and status.field == "keep_forever"
    assert "keepForever" in status.detail and PATH in status.detail


async def test_the_public_health_check_never_writes() -> None:
    """The unauthenticated ``/health`` endpoint uses ``health()``'s default, ``probe_write=False``
    - and here, ``probe_write=True`` makes no difference, since Drive's probe never writes to
    begin with. Pinned by asserting what requests were actually made, not by excluding one
    method name: every request this probe issues must be a plain ``GET``, in both modes."""
    script = Script().on(
        f"drives/{DRIVE_ID}",
        httpx.Response(
            200, json={"id": DRIVE_ID, "name": "Customer", "capabilities": {"canAddChildren": True}}
        ),
    )
    status = await _backend(script).health()
    assert status == HealthStatus(ok=True, detail="ok")
    assert script.requests  # the probe did run
    assert {request.method for request in script.requests} == {"GET"}

    script_write = Script().on(
        f"drives/{DRIVE_ID}",
        httpx.Response(
            200, json={"id": DRIVE_ID, "name": "Customer", "capabilities": {"canAddChildren": True}}
        ),
    )
    status = await _backend(script_write).health(probe_write=True)
    assert status == HealthStatus(ok=True, detail="ok")
    assert {request.method for request in script_write.requests} == {"GET"}


async def test_health_message_never_contains_a_token_or_a_provider_body() -> None:
    script = Script().on(
        f"drives/{DRIVE_ID}", httpx.Response(500, text="Bearer test-token leaked by the provider")
    )
    status = await _backend(script).health()
    assert status.ok is False
    assert "test-token" not in status.detail and "Bearer" not in status.detail
