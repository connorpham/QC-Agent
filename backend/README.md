# QC-Agent backend

FastAPI + PostgreSQL. Phase 1 foundation: accounts, mandatory TOTP MFA, sessions, projects and roles.

## Prerequisites

- Docker Desktop or OrbStack
- uv (Python 3.12 is installed by uv)

## First run

```bash
docker compose -f ../deploy/dev/docker-compose.yml up -d db
cp .env.example .env        # fill SESSION_SECRET and SECRET_ENCRYPTION_KEY (commands inside)
uv sync
uv run alembic upgrade head
uv run qc-agent create-admin --email you@techvify.com.vn --name "Your Name"
uv run uvicorn --factory app.main:create_app --reload
```

API docs: http://localhost:8000/docs

## Tests

```bash
uv run pytest
uv run ruff check . && uv run mypy app
```

Tests use the `qc_agent_test` database created by `deploy/dev/init-test-db.sql`. Override with `TEST_DATABASE_URL`.

## Sign-in flow

1. `POST /api/v1/auth/login` → session cookie, MFA pending.
2. First time: `POST /auth/mfa/enroll` → scan the `otpauth_uri`; `POST /auth/mfa/confirm` → recovery codes (shown once).
   Later: `POST /auth/mfa/verify` with a 6-digit code or a recovery code.
3. If `must_change_password`: `POST /auth/change-password`.

Every state-changing request needs the header `X-QC-Agent: 1`.

## Data notice

No customer documents are handled by this foundation. Later phases send converted document text to the Claude API only after a per-project customer confirmation (see the spec).
