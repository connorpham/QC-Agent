"""The OpenAPI export the frontend generates its client from, and the drift check that keeps
``frontend/openapi.json`` current."""

import json
from pathlib import Path

import pytest

from app.openapi_export import build_document, main, render

REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / "frontend" / "openapi.json"
HINT = "run `uv run python -m app.openapi_export ../frontend/openapi.json` from backend/ and commit"


def test_export_writes_the_document(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "openapi.json"
    assert main([str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "QC-Agent"
    for path in ("/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/projects", "/api/v1/users"):
        assert path in document["paths"], path
    assert "LoginRequest" in document["components"]["schemas"]
    assert out.read_text(encoding="utf-8").endswith("}\n")


def test_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_render_is_deterministic() -> None:
    assert render(build_document()) == render(build_document())


def test_committed_frontend_document_is_current() -> None:
    assert COMMITTED.exists(), f"frontend/openapi.json is missing: {HINT}"
    assert COMMITTED.read_text(encoding="utf-8") == render(build_document()), (
        f"frontend/openapi.json is stale: {HINT}"
    )
