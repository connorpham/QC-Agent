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
