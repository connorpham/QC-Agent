# QC-Agent backend

FastAPI + PostgreSQL. Phase 1 so far: accounts, mandatory TOTP MFA, sessions, projects and roles (Plan 1); guided document upload, deterministic conversion, publishing into the standard folder structure on local storage, versions, stubs and gap report, document browsing with visibility rules (Plan 2).

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

API docs: http://localhost:8000/docs (requires `EXPOSE_DOCS=true`, which `.env.example` sets for local development; docs are off by default).

Documents are written under `LOCAL_STORAGE_ROOT` (default `./workspace`, one folder per project slug) and uploads are staged under `STAGING_ROOT` (default `./staging`). Both are git-ignored. The taxonomy and document templates live in `../templates/` and are validated when the app starts.

## Behind a reverse proxy

Run uvicorn with `--proxy-headers` and set `FORWARDED_ALLOW_IPS` to the proxy's address, otherwise
rate limiting and session IPs see only the proxy's address:

```bash
FORWARDED_ALLOW_IPS=10.0.0.5 uv run uvicorn --factory app.main:create_app --proxy-headers
```

## Tests

CI (GitHub Actions, `.github/workflows/ci.yml`) runs the same gates on every pull request and on pushes to `main`: ruff, mypy strict, `alembic upgrade head` + `alembic check`, pytest against PostgreSQL 16, and a gitleaks scan of the full history.

Activate the pre-commit hooks once (from the repository root) so the gitleaks secret scan,
ruff and mypy run on every commit:

```bash
uv tool install pre-commit && pre-commit install
```

```bash
uv run pytest
uv run ruff check . && uv run mypy app
```

Tests use the `qc_agent_test` database created by `deploy/dev/init-test-db.sql`. Override with `TEST_DATABASE_URL`. Storage and staging roots are temporary directories created per test session; fixture documents are generated at test time (no binary fixtures, no customer content).

## Sign-in flow

1. `POST /api/v1/auth/login` → session cookie, MFA pending.
2. First time: `POST /auth/mfa/enroll` → scan the `otpauth_uri`; `POST /auth/mfa/confirm` → recovery codes (shown once).
   Later: `POST /auth/mfa/verify` with a 6-digit code or a recovery code.
3. If `must_change_password`: `POST /auth/change-password`.

Every state-changing request needs the header `X-QC-Agent: 1`.

## Ingestion flow

1. An owner confirms that converted document text may be sent to the Claude API:
   `POST /api/v1/projects/{id}/llm-consent {"confirmed_by_name": "..."}`. Uploads return 409 until then.
2. `GET /api/v1/taxonomy` lists the six folders and their document types; every folder also accepts `<folder-id>/other`.
3. Upload (multipart; one `items` entry per file, in order):

   ```bash
   curl -b cookies.txt -H "X-QC-Agent: 1" \
     -F "files=@srs.docx" -F "files=@export.zip" \
     -F 'items=[{"doc_type":"srs","title":"Customer Portal SRS"},{"doc_type":"glossary"}]' \
     http://localhost:8000/api/v1/projects/<project-id>/uploads
   ```

   Zip entries become items of the archive's type; unsafe or unsupported entries are listed under `rejected`.
4. Poll `GET /api/v1/uploads/{id}`. Item states: `uploaded → converting → checking → publishing → published`, `needs_confirmation` when the type check disagrees (the check is skipped until the agent plan), `failed` with a reason and `POST /upload-items/{id}/retry`.
5. Items waiting for the uploader appear in `GET /api/v1/me/tasks`; `POST /upload-items/{id}/confirm-type {"doc_type": "..."}` keeps or changes the type and publishes.
6. Browse: `GET /projects/{id}/documents` (filters `folder`, `doc_type`, `visibility`, `q`), `GET /documents/{id}`, `/versions`, `/versions/{v}/original` (download), `/versions/{v}/markdown`, `PATCH /documents/{id}` (title, visibility), `GET /projects/{id}/gap-report` (internal roles), `GET /projects/{id}/version-suggestions?doc_type=&title=`.

Clients (customer accounts) upload as `shared`, see only shared documents and never the gap report.

## Storage layout (local backend)

```
workspace/<project-slug>/
├── project.yaml
├── 01-overview/ … 06-deployment/      # <doc-type>--<title-slug>.<ext> + .md with frontmatter; <doc-type>.md stubs
├── 04-source/adr/, 05-testing/test-reports/
├── _reports/gap-report.md, gap-report.json
├── .versions/<path>/<n>                # previous content of overwritten files
└── .trash/<path>                       # removed stubs
```

## Data notice

Converted document text is stored in PostgreSQL (`document_versions.markdown_text`) and in the project's storage folder. No document content is sent to any external service in this version: the type check is a placeholder (`SkipAnalyzer`) until the agent plan, and that plan sends text to the Claude API only for projects with a recorded confirmation.
