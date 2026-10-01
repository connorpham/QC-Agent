"""Write the API's OpenAPI document as JSON for the frontend's generated client.

    uv run python -m app.openapi_export ../frontend/openapi.json

The app is built with placeholder settings: ``create_app`` connects to nothing until its
lifespan runs, and ``app.openapi()`` never runs it, so the export needs no database or ``.env``.
"""

import json
import sys
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from app.core.config import Settings
from app.main import create_app

USAGE = "usage: python -m app.openapi_export <output.json>"


def export_settings() -> Settings:
    """Placeholder values that satisfy validation; nothing here ever serves a request."""
    return Settings(
        database_url="postgresql+asyncpg://export:export@localhost/export",
        session_secret="openapi-export-placeholder-not-a-real-secret",  # noqa: S106
        secret_encryption_key=Fernet.generate_key().decode(),
        expose_docs=False,
    )


def build_document() -> dict[str, Any]:
    return create_app(export_settings()).openapi()


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    output = Path(args[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(build_document()), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
