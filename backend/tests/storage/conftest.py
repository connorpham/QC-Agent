"""Storage contract fixtures. Plan 3 adds SharePoint and Google Drive params (opt-in live)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.storage.base import StorageBackend
from app.storage.localfs import LocalFsBackend


@pytest.fixture(params=["localfs"])
async def backend(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[StorageBackend]:
    if request.param == "localfs":
        yield LocalFsBackend(tmp_path / "project-root")
        return
    raise RuntimeError(f"Unknown storage backend param {request.param!r}")
