# QC-Agent

Web application where TECHVIFY team members and customer users upload project documents into one standard SDLC structure (Phase 1 design: `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md`).

- `backend/` — FastAPI + PostgreSQL API (`backend/README.md`)
- `frontend/` — Next.js web application (`frontend/README.md`)
- `templates/` — document taxonomy and templates (data, not code)
- `deploy/dev/` — PostgreSQL for development and tests

## Run everything locally

Prerequisites: Docker Desktop or OrbStack, uv, Node 24 with pnpm 11 (`corepack enable` installs the pinned pnpm).

```bash
docker compose -f deploy/dev/docker-compose.yml up -d db

# backend — http://localhost:8000
cd backend
cp .env.example .env                      # fill SESSION_SECRET and SECRET_ENCRYPTION_KEY
uv sync && uv run alembic upgrade head
uv run qc-agent create-admin --email you@techvify.com.vn --name "Your Name"
uv run uvicorn --factory app.main:create_app --reload

# frontend — http://localhost:3000 (proxies /api to BACKEND_URL, default http://localhost:8000)
cd ../frontend
pnpm install
pnpm dev
```

Sign in at http://localhost:3000 with the administrator e-mail and the temporary password: enrol MFA (scan the QR code or type the setup key into an authenticator app, store the recovery codes), change the password, then configure storage under Admin → Storage and create the first project.

## Checks

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd frontend && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build
cd frontend && pnpm e2e        # Playwright against a disposable database (needs the dev PostgreSQL)
```

After changing any API model or route: `cd backend && uv run python -m app.openapi_export ../frontend/openapi.json && cd ../frontend && pnpm api:generate`, and commit both generated files.

## What the UI offers

- Admin users and storage settings
- Upload wizard with live progress (Server-Sent Events), My tasks and type confirmation, document browser with in-browser Markdown, versions and downloads, gap report (Plan 5)

CI (`.github/workflows/ci.yml`) runs the backend gates, the frontend gates, the end-to-end suite and a gitleaks scan on every pull request.
