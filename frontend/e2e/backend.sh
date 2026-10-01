#!/usr/bin/env bash
# Started by Playwright's webServer with the e2e environment (see env.ts): recreate the e2e
# database, apply the migrations, run the API. Playwright waits for /api/v1/health.
set -euo pipefail
cd "$(dirname "$0")/../../backend"
uv run python - <<'PY'
import asyncio
import os

import asyncpg

url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
server, name = url.rsplit("/", 1)
name = name.split("?", 1)[0]

# This script drops the database it is pointed at. Only a disposable e2e database may be named,
# so a stray DATABASE_URL (the dev or test database, or production) cannot be destroyed here.
if not name.endswith("e2e"):
    raise SystemExit(
        f"Refusing to drop database {name!r}: the end-to-end database name must end in 'e2e'. "
        "Set QC_E2E_DATABASE_URL to a disposable database, for example "
        "postgresql+asyncpg://qc:qc@localhost:5434/qc_agent_e2e."
    )


async def main() -> None:
    conn = await asyncpg.connect(f"{server}/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


asyncio.run(main())
PY
uv run alembic upgrade head
exec uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8001
