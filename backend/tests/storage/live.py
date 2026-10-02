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
