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
from app.storage.gdrive_paths import DriveResolver, FolderCache, TokenProvider
from app.storage.http import get_client
from app.storage.responses import parsed_json, parsed_timestamp, required_str
from app.storage.retry import DRIVE_POLICY, raise_for_storage, send_with_retry

logger = logging.getLogger(__name__)

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SCOPES = ["https://www.googleapis.com/auth/drive"]
MULTIPART_LIMIT = 5 * 1024 * 1024
KEEP_FOREVER_LIMIT = 200
KEEP_FOREVER_EXEMPT = ("project.yaml", "_reports/")
# The configuration schema already restricts a Shared Drive id to this character set
# (app.schemas.storage._SAFE_ID_RE), but it is interpolated straight into a URL path here, so it
# is quoted again at the point of use rather than trusting that validation was the only way it
# could ever arrive (finding 7). Characters in this set pass through unescaped; anything else -
# most importantly "/" - is percent-encoded so it can never be read as a path separator.
ID_SAFE_CHARS = ",.:!_-"
SHARED_CACHE = FolderCache()

NOT_A_MEMBER = (
    "The service account has not been added to this Shared Drive, or cannot see it at all. A "
    "Google Workspace administrator must add it as Content manager."
)
DRIVE_NOT_FOUND = (
    "Shared Drive not found. Check the Shared Drive id, and that the service account has been "
    "added to that drive."
)
NOT_CONTENT_MANAGER = (
    "The service account can see this Shared Drive but does not have permission to add or "
    "replace files. A Google Workspace administrator must raise its role to Content manager."
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
        raise StorageError(
            'This is not a service account key (its "type" must be "service_account").'
        )
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
            # google-auth ships without inline type annotations for this constructor.
            self._credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
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
                logger.warning(
                    "Google service-account token refresh failed: %s", type(exc).__name__
                )
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
        # The Shared Drive id is part of the scope, not just the connection id and root path: an
        # administrator can correct a connection's drive id after a publish has already cached
        # folder ids resolved against the old drive. Without the drive id in the key, a lookup
        # made right after that correction could return a folder id that belongs to the old
        # (wrong) Shared Drive, and Drive honours a parent id regardless of which drive a request
        # is scoped to - silently writing into the previous customer's drive (finding 1).
        self._scope = f"{scope}:{self._drive_id}:{self._root_path}"
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
        self,
        method: str,
        url: str,
        *,
        context: str,
        raise_on_auth_error: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = {**(await self._headers()), **kwargs.pop("headers", {})}
        response = await send_with_retry(
            self._client,
            lambda: self._client.build_request(method, url, headers=headers, **kwargs),
            policy=DRIVE_POLICY,
            context=context,
            sleep=self._sleep,
            raise_on_auth_error=raise_on_auth_error,
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
            entry = await self._resolver.resolve_optional(self._root_path, root_id=self._drive_id)
            if entry is None or not entry.is_folder:
                raise StorageNotFound(f"Project folder not found: {self._root_path}")
            self._root_id = entry.id
        return self._root_id

    @staticmethod
    def _keep_forever(path: str) -> bool:
        # An entry with a trailing slash is a folder prefix (e.g. "_reports/"); anything else is
        # an exact relative path (e.g. "project.yaml"), matched whole so "project.yamlx" is not
        # caught by a bare prefix check.
        return not any(
            path.startswith(e) if e.endswith("/") else path == e for e in KEEP_FOREVER_EXEMPT
        )

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
            file = await self._upload_multipart(
                existing, parent_id, name, data, content_type, context
            )
        else:
            file = await self._upload_resumable(
                existing, parent_id, name, data, content_type, context
            )
        item_id = required_str(file, "id", context=context)
        version_id = str(file.get("headRevisionId") or "")
        if self._keep_forever(relative) and version_id:
            await self._mark_keep_forever(item_id, version_id, relative, context)
        return StoredFile(item_id=item_id, version_id=version_id, web_url=file.get("webViewLink"))

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
        return parsed_json(response, context=context)

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
        if upload.status_code not in (200, 201):
            # Google's resumable-upload protocol signals an incomplete transfer with a 308; this
            # adapter always sends the whole file in one PUT, so any non-2xx-complete response
            # here (308 most of all) is itself the unexpected case, not a status this adapter can
            # usefully continue from - and its body is not a completed item either (finding 8).
            raise StorageError(
                f"{context} failed: the storage service returned an unexpected response."
            )
        return parsed_json(upload, context=context)

    async def _mark_keep_forever(
        self, file_id: str, revision_id: str, relative: str, context: str
    ) -> None:
        response = await self._send(
            "PATCH",
            f"{API}/files/{file_id}/revisions/{revision_id}",
            context=context,
            params={"fields": "id,keepForever", "supportsAllDrives": "true"},
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
                "supportsAllDrives": "true",
            },
        )
        raise_for_storage(response, context=context)
        revisions = parsed_json(response, context=context).get("revisions", [])
        if not isinstance(revisions, list):
            raise StorageError(
                f"{context} failed: the storage service returned an unexpected response."
            )
        for r in revisions:
            if not isinstance(r, dict):
                raise StorageError(
                    f"{context} failed: the storage service returned an unexpected response."
                )
        kept = sum(1 for r in revisions if r.get("keepForever"))
        if kept >= KEEP_FOREVER_LIMIT:
            self.note_keep_forever_limit(relative, kept)
        return [
            StoredVersion(
                version_id=required_str(r, "id", context=context),
                size=int(r.get("size", 0)),
                modified_at=parsed_timestamp(r.get("modifiedTime"), context=context),
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
            params={"alt": "media", "supportsAllDrives": "true"},
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

    async def health(self, *, probe_write: bool = False) -> HealthStatus:
        """Staged probe: credentials, then the Shared Drive, then write permission (spec 8.5).

        Each stage has its own field token, so Test connection can point at the input or the
        grant at fault instead of a generic failure. The probe asks ``send_with_retry`` not to
        auto-raise on 401/403 (``raise_on_auth_error=False``): this stage must read the status
        code itself to tell "wrong credentials" apart from "forbidden for this Shared Drive",
        which an exception raised before the response reaches here could not distinguish.

        ``probe_write`` is accepted for symmetry with the SharePoint adapter's ``health``, whose
        public-vs-admin split it mirrors, but there is nothing to opt into here: every stage below
        is already a read (``canAddChildren`` is reported by the Shared Drive itself, and
        ``keep_forever`` reflects state this adapter already holds from earlier uploads), so this
        probe never writes, creates or deletes anything regardless of the flag.

        Field tokens: ``secret`` (credentials rejected), ``drive_id`` (Shared Drive not found),
        ``not_member`` (service account cannot see the Shared Drive at all), ``write_grant``
        (service account can see it but is not Content manager), ``keep_forever`` (a file has hit
        Drive's revision-retention cap). No two stages share a token.
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
                f"{API}/drives/{quote(self._drive_id, safe=ID_SAFE_CHARS)}",
                context="Checking the Shared Drive",
                params={"supportsAllDrives": "true", "fields": "id,name,capabilities"},
                raise_on_auth_error=False,
            )
        except StorageError as exc:
            return HealthStatus(ok=False, detail=str(exc), field="drive_id")
        if response.status_code == 404:
            return HealthStatus(ok=False, detail=DRIVE_NOT_FOUND, field="drive_id")
        if response.status_code in (401, 403):
            return HealthStatus(ok=False, detail=NOT_A_MEMBER, field="not_member")
        if response.status_code >= 400:
            return HealthStatus(
                ok=False,
                detail=f"Checking the Shared Drive failed ({response.status_code}).",
                field="drive_id",
            )
        capabilities = response.json().get("capabilities", {})
        if not capabilities.get("canAddChildren"):
            return HealthStatus(ok=False, detail=NOT_CONTENT_MANAGER, field="write_grant")
        if self._at_limit:
            paths = ", ".join(sorted(self._at_limit))
            return HealthStatus(
                ok=False,
                detail=(
                    "Google Drive's keepForever limit has been reached for: "
                    f"{paths}. Older versions of these files may be pruned by Drive."
                ),
                field="keep_forever",
            )
        return HealthStatus(ok=True, detail="ok")
