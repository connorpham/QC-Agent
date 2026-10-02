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

# Field tokens returned on ``HealthStatus.field``. These are diagnosis codes, not strictly the
# connection's own column names: "library not found" and "library belongs to another site" are
# both ultimately about the drive id, but they are different faults with different fixes, so
# they get different codes. Each stage below has exactly one of these, and no two stages share
# one (see test_health_every_stage_reports_a_distinct_field).
FIELD_SECRET = "secret"  # noqa: S105 - a diagnosis-code label, not a credential
FIELD_SITE_ID = "site_id"
FIELD_DRIVE_ID = "drive_id"
FIELD_DRIVE_WRONG_SITE = "drive_id_wrong_site"
FIELD_WRITE_GRANT = "write_grant"
FIELD_VERSIONING = "versioning"

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

    async def _send(
        self,
        method: str,
        url: str,
        *,
        context: str,
        auth_raises: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
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
            raise_on_auth_error=auth_raises,
        )

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
        response = await self._send("GET", f"{self._address(path)}/content", context=context)
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
        # Graph accepts path addressing on /versions directly, so there is no separate
        # "turn this path into an item id" lookup here (or in get_version, move_to_trash):
        # that would be an extra request per call for no benefit. Do not re-add one.
        relative = normalize_path(path)
        context = f"Listing versions of {relative}"
        response = await self._send("GET", f"{self._address(path)}/versions", context=context)
        if response.status_code == 404:
            raise StorageNotFound(f"File not found: {relative}")
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
        response = await self._send(
            "GET",
            f"{self._address(path)}/versions/{quote(version_id, safe='')}/content",
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
        response = await self._send("DELETE", self._address(path), context=context)
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
            return HealthStatus(ok=False, detail=str(exc), field=FIELD_SECRET)

        site = await self._quiet("GET", f"{GRAPH}/sites/{self._site_id}?$select=id,webUrl")
        if isinstance(site, HealthStatus):
            return HealthStatus(ok=False, detail=site.detail, field=None)
        if site.status_code == 404:
            return HealthStatus(ok=False, detail=SITE_NOT_FOUND, field=FIELD_SITE_ID)
        if site.status_code in (401, 403):
            return HealthStatus(ok=False, detail=NO_GRANT, field=FIELD_SITE_ID)
        if site.status_code >= 400:
            return HealthStatus(
                ok=False,
                detail=f"Checking the site failed ({site.status_code}).",
                field=FIELD_SITE_ID,
            )
        site_url = str(site.json().get("webUrl", "")).rstrip("/")

        drive = await self._quiet("GET", f"{self._drive}?$select=id,name,webUrl")
        if isinstance(drive, HealthStatus):
            return HealthStatus(ok=False, detail=drive.detail, field=None)
        if drive.status_code in (403, 404):
            return HealthStatus(ok=False, detail=LIBRARY_NOT_FOUND, field=FIELD_DRIVE_ID)
        if drive.status_code >= 400:
            return HealthStatus(
                ok=False,
                detail=f"Checking the document library failed ({drive.status_code}).",
                field=FIELD_DRIVE_ID,
            )
        library_url = str(drive.json().get("webUrl", ""))
        if site_url and not library_url.startswith(site_url):
            return HealthStatus(ok=False, detail=WRONG_SITE, field=FIELD_DRIVE_WRONG_SITE)

        return await self._probe_write_and_versioning()

    async def _probe_write_and_versioning(self) -> HealthStatus:
        """Write the probe file twice and count its versions.

        ``item_id`` is set the moment the first write succeeds, and the ``finally`` block
        deletes it on every exit path from here on - whether the second write fails, the
        version count comes back short, or the version lookup itself errors - so a failed
        health check never leaves the probe file behind in a customer's library.
        """
        probe_path = (
            f"{self._root_path}/{HEALTH_PROBE_NAME}" if self._root_path else HEALTH_PROBE_NAME
        )
        address = f"{self._drive}/root:/{quote(probe_path, safe='/')}:"
        item_id = ""
        try:
            for body in (b"qc-agent health probe 1\n", b"qc-agent health probe 2\n"):
                written = await self._quiet(
                    "PUT",
                    f"{address}/content",
                    content=body,
                    headers={"Content-Type": "text/plain"},
                )
                if isinstance(written, HealthStatus):
                    return HealthStatus(ok=False, detail=written.detail, field=None)
                if written.status_code in (401, 403):
                    return HealthStatus(ok=False, detail=NO_WRITE, field=FIELD_WRITE_GRANT)
                if written.status_code >= 400:
                    return HealthStatus(
                        ok=False,
                        detail=f"Writing a test file failed ({written.status_code}).",
                        field=FIELD_DRIVE_ID,
                    )
                item_id = str(written.json()["id"])

            versions = await self._quiet("GET", f"{self._drive}/items/{item_id}/versions")
            count = (
                0 if isinstance(versions, HealthStatus) else len(versions.json().get("value", []))
            )
            if count < 2:
                return HealthStatus(ok=False, detail=VERSIONING_OFF, field=FIELD_VERSIONING)
            return HealthStatus(ok=True, detail="ok")
        finally:
            if item_id:
                await self._quiet("DELETE", f"{self._drive}/items/{item_id}")  # best effort

    async def _quiet(self, method: str, url: str, **kwargs: Any) -> httpx.Response | HealthStatus:
        """Send a probe request with ``auth_raises=False``, so a 401/403 comes back as an
        ordinary response the caller's own stage can inspect and assign its own field to,
        instead of ``send_with_retry`` raising ``StorageAuthError`` and collapsing every stage
        into the same generic message. Any other failure (connectivity, retries exhausted)
        still comes back as a status with no specific field - the caller cannot say more."""
        try:
            return await self._send(
                method, url, context="Checking the connection", auth_raises=False, **kwargs
            )
        except StorageError as exc:
            return HealthStatus(ok=False, detail=str(exc))
