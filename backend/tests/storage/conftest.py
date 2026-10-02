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
