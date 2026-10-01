# Plan 2 — Local Ingestion: Guided Upload End to End on Local Storage

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Project members upload documents with a selected type; the backend validates, stages, converts them to Markdown, runs a (currently skipped) type check, publishes original + converted file with frontmatter into the standard folder structure on a local filesystem storage backend, keeps versions, maintains stubs and the gap report, and serves documents with role and visibility rules.

**Architecture:** The ingestion pipeline is deterministic code in `app/ingestion/` (taxonomy, naming, converters, intake, stubs, gap report, version suggestion) and `app/services/` (uploads, publish, pipeline, documents, workspace, consent). Storage goes through a `StorageBackend` protocol with one adapter, `LocalFsBackend`, and a contract test suite that later adapters (Plan 3) re-run unchanged. The per-item state machine runs as FastAPI `BackgroundTasks` after the upload request (deterministic in tests: `httpx.ASGITransport` awaits background tasks before returning the response) and re-queues unfinished items at startup. The agent is behind an `Analyzer` protocol: `SkipAnalyzer` in production until Plan 4, `FakeAnalyzer` in tests, injected through `create_app(analyzer=...)`.

**Tech Stack:** Python 3.12 (uv), FastAPI 0.142, SQLAlchemy 2.1 (asyncio) + asyncpg, Alembic, PyYAML, markitdown 0.1.8 (`[docx,pptx,xlsx,pdf]`), PyMuPDF 1.28, langdetect, python-multipart, anyio; tests with pytest + httpx and runtime-generated fixtures (python-docx, python-pptx, openpyxl, PyMuPDF).

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` — sections 5 (knowledge-base standard), 6 (upload flow, states, steps 1–5, concurrency), 7.1 (analyzer interface, check only), 8.1 and 8.4 (storage interface, local adapter), 9 (roles and visibility), 10 (`uploads`, `upload_items`, `documents`, `document_versions`; `projects.storage`), 11 (taxonomy, uploads, items, documents, suggest endpoints), 13 (uploads, data processing), 14 (error handling), 15 (unit, storage contract, API matrix tests). Scope decided by the controller on 2026-10-01 (stakeholder choice: upload on local storage first, cloud storage later); this plan re-sequences the roadmap, the spec stays the authority.

**Re-sequenced roadmap (Task 14 writes it):** Plan 2 = local ingestion (this plan); Plan 3 = cloud storage adapters (SharePoint, Google Drive, storage connections, admin endpoints); Plan 4 = agent layer; Plan 5 = frontend; Plan 6 = deployment and operations.

**Deferred from this plan (where it goes):**

- Server-Sent Events `GET /uploads/{id}/events`, `events` table, `Last-Event-ID` replay → Plan 5 (frontend); the frontend polls `GET /uploads/{id}` until then.
- SharePoint / Google Drive adapters, `storage_connections`, admin connection endpoints, "Test connection" → Plan 3.
- Agent check and normalise sessions, `normalizing`/`draft_ready`/`normalized_published` states, `normalized_drafts`, `agent_runs`, draft endpoints, `*.normalized.md` → Plan 4 (`Analyzer.check` stays; `normalize` is added there).
- Repository-structure document from a git URL (spec 5.6; `uploads.repo_ref` column exists but is unused) → Plan 4 or a later small plan.
- OCR for scanned PDFs → out of Phase 1 (spec 2.2); low-text PDFs publish with a `low_text` warning.
- Staging cleanup job (`STAGING_RETENTION_DAYS`), `/health` extensions → Plan 6.

## Global Constraints

- Python `>=3.12,<3.13`, managed with uv; run every command from `backend/` unless stated. All Plan 1 Global Constraints still apply (API prefix `/api/v1`, English copy, CSRF header `X-QC-Agent: 1` on every state-changing request, Annotated dependencies, services never import `app.api`, `SessionContext` from `app.services.context`, audit rows via `app.services.audit.record` which never commits).
- PostgreSQL 16 on `localhost:5434` (`deploy/dev/docker-compose.yml`); tests run against `qc_agent_test`, never SQLite. Docker (or a local PostgreSQL 16) must be running before Task 1's tests.
- `ruff check`, `ruff format --check` and `mypy app` (strict) pass after every task. Blocking file I/O never runs directly inside `async def` (ruff `ASYNC230`/`ASYNC240`): use `asyncio.to_thread(...)` or `anyio.open_file`.
- Taxonomy and templates are data at the repository root: `templates/taxonomy.yaml` exactly as spec 5.2 and one Markdown template per document type in `templates/doc-templates/`. Every folder implicitly accepts `other` (API key `<folder-id>/other`). Validation at startup; an invalid taxonomy stops the app.
- File names: original `<doc-type>--<title-slug>.<ext>`, converted `<doc-type>--<title-slug>.md`, normalised `<doc-type>--<title-slug>.normalized.md` (reserved), stub `<doc-type>.md`; `multi` types live in their `subdir`. Slugs: lowercase ASCII, digits, hyphens, Vietnamese transliterated, ≤ 80 chars, collisions get `-2`, `-3`, … (reuse `app.core.slugs`).
- Frontmatter starts every converted and stub Markdown file: `qc_agent: 2`, `document_id`, `version`, `doc_type`, `folder`, `title`, `kind` (`converted` | `stub`; `normalized` later), `source_file`, `source_sha256`, `uploaded_by` (display name only, never an e-mail), `uploaded_at`, `type_selected_by_user`, `type_check` (`match` | `mismatch_kept` | `mismatch_changed` | `skipped`), `language`, `visibility`, `normalized_approved_by: null`.
- Storage paths are relative to the project root, `/`-separated, normalised; `..`, absolute paths, backslashes, control characters, symlinks and the reserved top-level folders `.versions`/`.trash` are rejected with `StoragePathError`. `LocalFsBackend` keeps versions as `.versions/<path>/<n>` and trashed files as `.trash/<path>`.
- Project storage binding `projects.storage = {"type": "localfs", "root": "<slug>", "provisioned_at": ...}` is set at creation; the workspace (six folders, `_reports/`, `project.yaml`, stubs for required types, gap report) is provisioned **eagerly at project creation** and `ensure_workspace` is idempotent, so a project that predates provisioning is repaired on its first publish.
- Upload limits: extensions `docx pdf xlsx pptx md txt html csv zip` (`htm` → `html`), `MAX_UPLOAD_FILE_MB` 50, `MAX_UPLOAD_BATCH_MB` 500, zip: ≤ 200 entries, no path traversal / absolute / symlink / encrypted / nested-zip entries, hidden entries (`__MACOSX`, dot files) skipped; file names sanitised; sizes counted while streaming (declared sizes are not trusted).
- Per-project LLM data-processing confirmation (`projects.llm_consent`) is required before the first upload: `POST /projects/{id}/uploads` returns 409 until an owner posts `/projects/{id}/llm-consent`.
- Publishing runs under `pg_advisory_xact_lock(<project key>)`; a new version overwrites the same paths (storage keeps history, `document_versions` records storage version ids); an identical SHA-256 to the current version is rejected as "no change" (early at intake, again under the lock); a stub is removed only if its content hash is unchanged; the gap report and `project.yaml` are regenerated on every publish; a retried item that already has a document version is not published twice.
- Roles and visibility (spec 9): `viewer` cannot upload; `client` uploads are forced `shared`, clients see only `shared` documents and get 404 for anything else, cannot change visibility, cannot read the gap report, and see only their own uploads; `editor` may share an internal document but not make a shared one internal; `owner` may do anything. Visibility and role checks live in one dependency (`document_context`) used by every document route.
- Audit rows for: `upload.created`, `upload_item.published`, `upload_item.failed`, `upload_item.type_confirmed`, `upload_item.retried`, `document.updated`, `document.visibility_changed`, `project.llm_consent`.
- Customer data never appears in fixtures or logs: tests generate synthetic files at runtime (no binary fixtures committed); logs carry ids and error classes, never document content.

## Verified third-party behaviour this plan depends on (checked on 2026-10-01 in a scratch environment)

- `markitdown` 0.1.8: `MarkItDown(enable_plugins=False).convert(path, stream_info=StreamInfo(extension=".docx"))` returns `DocumentConverterResult` with `.markdown` == `.text_content` and `.title`. It sniffs content: bytes that are not OOXML are converted as plain text without error, and a plain zip renamed `.docx` is *extracted* by its zip converter, so this plan validates containers (`[Content_Types].xml` in the zip, `%PDF-` header) before calling it. A password-protected PDF raises `FileConversionException`; a truncated docx raises `FileConversionException` (`BadZipFile`). Import costs ~0.6 s (magika/onnxruntime), construction 0.04 s, a small docx converts in ~70 ms.
- PyMuPDF 1.28.2 (`import pymupdf`): `pymupdf.open(path)` supports `with`; `doc.needs_pass`, `doc.page_count`, `doc.load_page(i).get_text("text")`; garbage raises `pymupdf.FileDataError`, empty input `pymupdf.EmptyFileError`; `doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=..., owner_pw=...)` writes an encrypted fixture; `doc.tobytes()` returns PDF bytes. It ships `py.typed` but leaves `Document` untyped: `untyped_calls_exclude = ["pymupdf"]` in mypy config.
- langdetect 1.0.9: `DetectorFactory.seed = 0` makes `detect()` deterministic (Vietnamese and English samples returned `vi`/`en` five times out of five); empty or numeric text raises `LangDetectException` ("No features in text."). No type stubs → `ignore_missing_imports`.
- FastAPI 0.142.2 / Starlette 1.7.0: `UploadFile(file, *, size, filename, headers)`; `files: Annotated[list[UploadFile], File()]` + `items: Annotated[str, Form()]` need `python-multipart` (0.0.32, not yet in the lock file); `BackgroundTasks` complete before `httpx.ASGITransport` returns the response, so API tests observe the finished pipeline deterministically; `app.routes` wraps included routers (`_IncludedRouter`), so route listings go through `app.openapi()["paths"]`.
- `zipfile`: `ZipInfo.external_attr >> 16` is the Unix mode (`stat.S_ISLNK` detects symlinks), `is_dir()`, `flag_bits & 0x1` is the encryption flag; traversal names (`../x`, `/abs`) are preserved verbatim for inspection; `ZipFile.writestr` resets `flag_bits`, so the encrypted-entry rule is unit-tested on a constructed `ZipInfo`.
- SQLAlchemy 2.1.1 compiles `update(users).values(failed_logins=users.c.failed_logins + 1).returning(users.c.failed_logins)` and `select(func.pg_advisory_xact_lock(literal(key, BigInteger)))` as expected for PostgreSQL.

## Review Focus

1. A password-protected PDF must fail its item with a clear reason ("PDF is password-protected…"), not crash the pipeline → test in Task 7 (`test_password_protected_pdf_is_rejected_with_a_clear_reason`).
2. A file whose bytes do not match its extension (plain text named `.docx`, a plain zip named `.docx`) must be rejected as mismatched content, never converted as text nor extracted → tests in Task 7 (`test_mismatched_content_is_rejected`, `test_zip_disguised_as_docx_is_rejected`).
3. A Confluence/Finder zip export containing `__MACOSX/`, `.DS_Store`, a `../` entry and a symlink must deliver the good entries, reject the dangerous ones individually and skip the junk silently → test in Task 8 (`test_zip_safety`).
4. A stub that a team member edited directly in storage must survive the publish of the real document (hash differs) → test in Task 11 (`test_edited_stub_is_kept`).
5. Two uploads with the same title published concurrently in one project must end as two documents with distinct slugs and paths, not a unique-constraint crash → test in Task 11 (`test_concurrent_publishes_in_one_project_get_distinct_slugs`).

---

## File Structure

```
QC-Agent/
├── templates/
│   ├── taxonomy.yaml                      # spec 5.2 verbatim
│   └── doc-templates/*.md                 # 20 templates: section headings + one-line guidance
├── docs/superpowers/plans/2026-10-01-phase1-roadmap.md   # re-sequenced (Task 14)
└── backend/
    ├── pyproject.toml                     # + pyyaml, markitdown, pymupdf, langdetect, anyio, python-multipart; dev: types-PyYAML, python-docx, python-pptx, openpyxl
    ├── .env.example                       # + LOCAL_STORAGE_ROOT, STAGING_ROOT, MAX_UPLOAD_*; TEMPLATES_DIR optional
    ├── migrations/versions/0002_ingestion.py
    ├── app/
    │   ├── main.py                        # taxonomy at startup, analyzer injection, pipeline context, re-queue, routers
    │   ├── core/config.py                 # + templates_dir, local_storage_root, staging_root, max_upload_file_mb, max_upload_batch_mb
    │   ├── db/models/
    │   │   ├── projects.py                # + storage, llm_consent
    │   │   └── ingestion.py               # Upload, UploadItem, Document, DocumentVersion
    │   ├── ingestion/
    │   │   ├── taxonomy.py                # load_taxonomy, Taxonomy, Folder, DocType, "other"
    │   │   ├── naming.py                  # paths + Frontmatter render/split
    │   │   ├── stubs.py                   # render_stub
    │   │   ├── gaps.py                    # build_gap_report, render_gap_report_markdown
    │   │   ├── versioning.py              # suggest_versions (difflib ≥ 0.8)
    │   │   ├── intake.py                  # extensions, sanitising, stage_stream, expand_zip
    │   │   └── converters/                # base (protocol, result), office (markitdown), pdf (pymupdf), text (md/txt/csv)
    │   ├── storage/
    │   │   ├── base.py                    # StorageBackend protocol, StoredFile, errors, normalize_path
    │   │   ├── localfs.py                 # LocalFsBackend
    │   │   └── select.py                  # backend_for(project.storage, settings), localfs_binding
    │   ├── agent/
    │   │   ├── analyzer.py                # Analyzer protocol, CheckBatch/CheckItem/ItemVerdict/CheckResult, SkipAnalyzer
    │   │   └── fake.py                    # FakeAnalyzer (scripted)
    │   ├── services/
    │   │   ├── auth.py                    # register_failure atomic (Task 1)
    │   │   ├── consent.py                 # record_consent, has_consent
    │   │   ├── workspace.py               # ensure_workspace, create_stub, refresh_reports, project.yaml
    │   │   ├── projects.py                # create_project binds storage + provisions
    │   │   ├── uploads.py                 # stage_files, create_upload, my_tasks, confirm_type, retry_item
    │   │   ├── publish.py                 # publish_item under advisory lock
    │   │   ├── pipeline.py                # PipelineContext, run_upload, check_items, publish_item_by_id, requeue_stale_items
    │   │   └── documents.py               # list/versions/update/version_suggestions with visibility rules
    │   ├── schemas/                       # taxonomy.py, uploads.py, documents.py; projects.py + consent/storage
    │   └── api/
    │       ├── deps.py                    # taxonomy_dep, pipeline_dep, resolve_role, Uploader, document_context
    │       └── routes/                    # taxonomy.py, uploads.py, documents.py; projects.py + llm-consent
    └── tests/
        ├── conftest.py                    # EXPOSE_DOCS=false, temp storage/staging roots, make_app(analyzer=...)
        ├── factories.py                   # + make_project, add_member
        ├── helpers/files.py, helpers/ingest.py
        ├── ingestion/, storage/, agent/   # unit + service tests
        ├── api/test_lockout_atomic.py, test_taxonomy_api.py, test_consent.py, test_uploads.py, test_documents.py
        └── db/test_models.py              # + ingestion model tests
```

---

### Task 1: Plan 1 carry-overs — hermetic docs test and atomic failed-login counter

**Files:**
- Modify: `backend/tests/conftest.py` (one line after `COOKIE_SECURE`), `backend/app/services/auth.py:29-36` (`register_failure`) and `:66` (call site), `backend/app/services/mfa.py:121` (call site)
- Test: `backend/tests/api/test_lockout_atomic.py`

**Interfaces:**
- Consumes: `User`, `Settings`, `audit.record`, test fixtures `db_sessionmaker`, `settings`, factories `make_user`, `reload` (Plan 1).
- Produces: `app.services.auth.register_failure(db: AsyncSession, user: User, settings: Settings, now: datetime) -> bool` (async; increments `failed_logins` in the database with `UPDATE … RETURNING`, locks atomically when the limit is reached, refreshes `user`, returns True when this call locked the account). Callers in `authenticate` and `verify_second_factor` `await` it.

- [ ] **Step 1: Make the API-docs test hermetic**

In `backend/tests/conftest.py`, directly after `os.environ["COOKIE_SECURE"] = "false"`, add:

```python
os.environ["EXPOSE_DOCS"] = "false"  # a developer .env may enable docs; tests expect them hidden
```

Run: `EXPOSE_DOCS=true uv run pytest tests/api/test_health.py -q`
Expected: `6 passed` (before this line, `test_api_docs_are_hidden_by_default` fails when the environment enables docs).

- [ ] **Step 2: Write the failing concurrency test**

`backend/tests/api/test_lockout_atomic.py`:

```python
"""Failed-login counting must be atomic: two requests holding stale user state must each add
one failure, so the fifth failure locks the account even when counted concurrently."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import User
from app.services.auth import register_failure
from tests.factories import make_user, reload


async def test_concurrent_failures_are_not_lost(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with db_sessionmaker() as setup:
        user = await make_user(setup, settings)
        user.failed_logins = 3
        await setup.commit()
        user_id = user.id
    now = datetime.now(UTC)
    async with db_sessionmaker() as db_a, db_sessionmaker() as db_b:
        stale_a = await db_a.get_one(User, user_id)
        stale_b = await db_b.get_one(User, user_id)  # both see failed_logins == 3
        assert await register_failure(db_a, stale_a, settings, now) is False
        await db_a.commit()
        assert await register_failure(db_b, stale_b, settings, now) is True
        await db_b.commit()
    async with db_sessionmaker() as check:
        locked = await reload(check, User, user_id)
        assert locked is not None
        assert locked.locked_until is not None and locked.locked_until > now
        assert locked.failed_logins == 0
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/api/test_lockout_atomic.py -v`
Expected: FAIL with `TypeError: register_failure() takes 3 positional arguments but 4 were given`.

- [ ] **Step 4: Make `register_failure` atomic**

In `backend/app/services/auth.py` replace the whole `register_failure` function (currently a synchronous function that mutates `user.failed_logins` in memory) with:

```python
async def register_failure(db: AsyncSession, user: User, settings: Settings, now: datetime) -> bool:
    """Count a failed credential check atomically. Returns True when this failure locked the
    account. Concurrent failures each add one in the database, so a stale in-memory
    ``failed_logins`` cannot lose a count."""
    count = await db.scalar(
        update(User)
        .where(User.id == user.id)
        .values(failed_logins=User.failed_logins + 1)
        .returning(User.failed_logins)
        .execution_options(synchronize_session=False)
    )
    locked = False
    if count is not None and count >= settings.login_max_failures:
        locked_id = await db.scalar(
            update(User)
            .where(User.id == user.id, User.failed_logins >= settings.login_max_failures)
            .values(locked_until=now + timedelta(minutes=settings.lockout_minutes), failed_logins=0)
            .returning(User.id)
            .execution_options(synchronize_session=False)
        )
        locked = locked_id is not None
    await db.refresh(user)
    return locked
```

`update` is already imported in this module. Then change the call site in `authenticate` from

```python
        locked = register_failure(user, settings, moment)
```

to

```python
        locked = await register_failure(db, user, settings, moment)
```

and in `backend/app/services/mfa.py` (`verify_second_factor`, failure branch) change

```python
        if register_failure(user, settings, moment):
```

to

```python
        if await register_failure(db, user, settings, moment):
```

Behaviour kept: the lockout tests in `tests/api/test_auth_login.py` and `tests/api/test_auth_mfa.py` still pass (five failures lock for `lockout_minutes`, the counter resets to 0 on lock, a completed second factor resets it, `is_locked` is unchanged).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_lockout_atomic.py tests/api/test_auth_login.py tests/api/test_auth_mfa.py tests/api/test_mfa_atomic.py -v`
Expected: all passed.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/tests/conftest.py backend/app/services/auth.py backend/app/services/mfa.py backend/tests/api/test_lockout_atomic.py
git commit -m "fix(backend): hermetic docs test and atomic failed-login counter"
```

---

### Task 2: Settings, taxonomy data, document templates, loader and `GET /taxonomy`

**Files:**
- Create: `templates/taxonomy.yaml`, `templates/doc-templates/*.md` (20 files), `backend/app/ingestion/__init__.py` (empty), `backend/app/ingestion/taxonomy.py`, `backend/app/schemas/taxonomy.py`, `backend/app/api/routes/taxonomy.py`
- Modify: `backend/pyproject.toml` (via `uv add`), `backend/app/core/config.py` (replace), `backend/app/api/deps.py` (append after `DbSession`), `backend/app/main.py` (replace)
- Test: `backend/tests/ingestion/__init__.py` (empty), `backend/tests/ingestion/test_taxonomy.py`, `backend/tests/api/test_taxonomy_api.py`

**Interfaces:**
- Consumes: `Settings`, `create_app`, `CurrentUser` (Plan 1).
- Produces:
  - `Settings` fields `templates_dir: str | None = None`, `local_storage_root: str = "./workspace"`, `staging_root: str = "./staging"`, `max_upload_file_mb: int = 50`, `max_upload_batch_mb: int = 500` (all Plan 2 settings are added here so `Settings` and `.env.example` change once).
  - `app.ingestion.taxonomy`: `DocType(id, key, title, folder_id, folder_dir, required, template, normalize, multi, subdir)` with `.is_other`, `.document_dir`; `Folder(id, dir, stage, doc_types)`; `Taxonomy(version, folders, templates_dir)` with `.doc_types`, `.resolve(key) -> DocType` (raises `UnknownDocType`), `.folder(id)`, `.required_types()`, `.template_text(doc_type)`; `load_taxonomy(templates_dir: Path | None = None) -> Taxonomy` (raises `TaxonomyError`); `parse_taxonomy(data, templates_dir)`; `default_templates_dir()`; constant `OTHER = "other"`. The key of a regular type is its id (`srs`); the key of a folder's implicit other type is `<folder-id>/other` (`requirements/other`).
  - `app.api.deps.taxonomy_dep(request) -> Taxonomy`, alias `TaxonomyDep`; `app.state.taxonomy` set by `create_app`.
  - `GET /api/v1/taxonomy` → `TaxonomyOut(version, folders=[FolderOut(id, dir, stage, doc_types=[DocTypeOut(key, id, title, required, normalize, multi)])])`, login required.

- [ ] **Step 1: Dependencies and settings**

```bash
uv add pyyaml
uv add --dev types-PyYAML
```

Expected: `pyyaml>=6.0.3` in `[project].dependencies`, `types-pyyaml` in the dev group (versions verified: PyYAML 6.0.3, types-PyYAML 6.0.12.x).

Replace `backend/app/core/config.py`:

`backend/app/core/config.py`:

```python
from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    session_secret: str = Field(min_length=32)
    secret_encryption_key: str
    public_base_url: str = "http://localhost:3000"
    cookie_secure: bool = True
    expose_docs: bool = False
    session_ttl_hours: int = 8
    login_max_failures: int = 5
    lockout_minutes: int = 15
    rate_limit_auth_per_5min: int = 100
    # Plan 2: templates, storage and upload limits
    templates_dir: str | None = None  # default: <repository root>/templates
    local_storage_root: str = "./workspace"
    staging_root: str = "./staging"
    max_upload_file_mb: int = Field(default=50, ge=1)
    max_upload_batch_mb: int = Field(default=500, ge=1)

    @field_validator("secret_encryption_key")
    @classmethod
    def _valid_fernet_key(cls, value: str) -> str:
        try:
            Fernet(value.encode())
        except ValueError as exc:
            raise ValueError("SECRET_ENCRYPTION_KEY must be a valid Fernet key.") from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
```

- [ ] **Step 2: Taxonomy and templates (repository root)**

`templates/taxonomy.yaml` (spec 5.2 verbatim):

```yaml
version: 1
folders:
  - id: overview
    dir: 01-overview
    stage: Why
    doc_types:
      - { id: readme,          title: Project README,  required: true,  template: readme.md }
      - { id: project-charter, title: Project Charter, required: true,  template: project-charter.md }
      - { id: glossary,        title: Glossary,        required: false, template: glossary.md }
  - id: requirements
    dir: 02-requirements
    stage: What
    doc_types:
      - { id: brd,          title: Business Requirements Document,      required: true,  template: brd.md }
      - { id: srs,          title: Software Requirements Specification, required: true,  template: srs.md }
      - { id: use-cases,    title: Use Cases,    required: false, template: use-cases.md }
      - { id: user-stories, title: User Stories, required: false, template: user-stories.md }
  - id: design
    dir: 03-design
    stage: How
    doc_types:
      - { id: architecture-c4, title: Architecture (C4), required: true,  template: architecture-c4.md }
      - { id: erd,             title: Entity Relationship Diagram, required: false, template: erd.md }
      - { id: workflows,       title: Workflows, required: false, template: workflows.md }
      - { id: api-spec,        title: API Specification, required: false, template: api-spec.md, normalize: false }
  - id: source
    dir: 04-source
    stage: Build
    doc_types:
      - { id: repo-structure,     title: Repository Structure, required: true,  template: repo-structure.md, normalize: false }
      - { id: coding-conventions, title: Coding Conventions,   required: false, template: coding-conventions.md }
      - { id: adr,                title: Architecture Decision Record, required: false, template: adr.md, multi: true, subdir: adr }
  - id: testing
    dir: 05-testing
    stage: Verify
    doc_types:
      - { id: test-plan,   title: Test Plan,   required: true,  template: test-plan.md }
      - { id: test-cases,  title: Test Cases,  required: true,  template: test-cases.md, normalize: false }
      - { id: test-report, title: Test Report, required: false, template: test-report.md, multi: true, subdir: test-reports }
  - id: deployment
    dir: 06-deployment
    stage: Run
    doc_types:
      - { id: deploy-guide,  title: Deployment Guide, required: true,  template: deploy-guide.md }
      - { id: runbook,       title: Runbook,          required: true,  template: runbook.md }
      - { id: release-notes, title: Release Notes,    required: false, template: release-notes.md }
```

One template per document type. Each has the document title as `#` heading and the sections the type must contain, each followed by a one-line `>` guidance; stubs embed them now, the agent plan uses the section list for normalisation.

`templates/doc-templates/adr.md`:

```markdown
# Architecture Decision Record

## Status
> Proposed, accepted, deprecated or superseded (with link).

## Context
> The forces and constraints that led to the decision.

## Decision
> The decision taken, stated in one or two sentences.

## Consequences
> Positive and negative consequences, follow-up actions.
```

`templates/doc-templates/api-spec.md`:

```markdown
# API Specification

## Overview
> Base URL, versioning, authentication and common error format.

## Endpoints
> Each endpoint: method, path, request, response, error codes.

## Data models
> Schemas referenced by the endpoints.
```

`templates/doc-templates/architecture-c4.md`:

```markdown
# Architecture (C4)

## System context
> The system, its users and the external systems it talks to (C4 level 1).

## Containers
> Deployable units, their technology and the protocols between them (C4 level 2).

## Components
> Major components inside each container and their responsibilities (C4 level 3).

## Cross-cutting concerns
> Security, logging, configuration, error handling and observability.

## Architecture decisions
> Links to the ADRs that shaped this architecture.
```

`templates/doc-templates/brd.md`:

```markdown
# Business Requirements Document

## Executive summary
> The business need in one paragraph.

## Business objectives
> Numbered objectives with the metric that proves each one.

## Current process (AS-IS)
> How the work is done today, including systems and pain points.

## Target process (TO-BE)
> How the work will be done after delivery.

## Business requirements
> Numbered requirements (BR-1, BR-2, ...) with priority and owner.

## Constraints and assumptions
> Regulatory, budget, timeline and technical constraints.

## Acceptance criteria
> How the business will judge the delivery as complete.
```

`templates/doc-templates/coding-conventions.md`:

```markdown
# Coding Conventions

## Languages and versions
> Languages, runtimes and framework versions in use.

## Style and formatting
> Formatter, linter and naming rules.

## Project layout
> Where modules, tests and configuration live.

## Review and quality gates
> Pull request rules, required checks, test coverage expectations.
```

`templates/doc-templates/deploy-guide.md`:

```markdown
# Deployment Guide

## Prerequisites
> Infrastructure, accounts, access and tools needed before deployment.

## Configuration
> Environment variables, secrets handling and configuration files (no secret values).

## Deployment steps
> Ordered steps for each environment.

## Verification
> Smoke tests and health checks after deployment.

## Rollback
> How to return to the previous release.
```

`templates/doc-templates/erd.md`:

```markdown
# Entity Relationship Diagram

## Entities
> Each entity with its purpose and key attributes.

## Relationships
> Cardinality and meaning of each relationship.

## Diagram
> The ERD as an image reference or Mermaid block.

## Notes
> Naming conventions, soft deletes, audit columns.
```

`templates/doc-templates/glossary.md`:

```markdown
# Glossary

## Terms
> One row per term: term, definition, source document. Keep customer-specific identifiers and codes verbatim.

## Abbreviations
> Abbreviation, expansion, context.
```

`templates/doc-templates/project-charter.md`:

```markdown
# Project Charter

## Background and problem
> The business situation that motivates the project.

## Objectives and success criteria
> Measurable outcomes the project must deliver.

## Scope
> In-scope deliverables, out-of-scope items and assumptions.

## Stakeholders and roles
> Sponsor, customer representatives, delivery roles and decision rights.

## Milestones and timeline
> Major phases with target dates.

## Risks and constraints
> Known risks, dependencies, budget and regulatory constraints.
```

`templates/doc-templates/readme.md`:

```markdown
# Project README

## Purpose
> One paragraph: what the system does and for whom.

## Scope
> What is in and out of scope for this project.

## Stakeholders
> Customer, product owner, delivery team and their contacts (roles, not personal data).

## Key documents
> Links to the charter, requirements, design, test and deployment documents in this knowledge base.

## Getting started
> How a new team member finds the repository, environments and access requests.
```

`templates/doc-templates/release-notes.md`:

```markdown
# Release Notes

## Release
> Version, date and environments.

## Changes
> New features, improvements and fixes with references.

## Known issues
> Open issues and workarounds.

## Upgrade notes
> Migration steps or configuration changes required.
```

`templates/doc-templates/repo-structure.md`:

```markdown
# Repository Structure

## Repositories
> Each repository with its URL (reference only), purpose and primary language.

## Directory tree
> Generated tree to depth 4 honouring standard ignores.

## Language statistics
> Lines or files per language, generated.
```

`templates/doc-templates/runbook.md`:

```markdown
# Runbook

## Service overview
> What the service does, owners and on-call contacts (roles).

## Monitoring and alerts
> Dashboards, alert rules and what each alert means.

## Routine operations
> Backups, restores, key rotation, scaling.

## Incident procedures
> Symptoms, diagnosis steps and remediation for known failure modes.

## Escalation
> When and to whom to escalate.
```

`templates/doc-templates/srs.md`:

```markdown
# Software Requirements Specification

## Introduction
> Purpose, scope and intended readers of this specification.

## Overall description
> Product context, user classes, operating environment and dependencies.

## Functional requirements
> Numbered requirements (FR-1, FR-2, ...) grouped by feature; keep requirement identifiers from the source.

## Non-functional requirements
> Performance, security, availability, usability and compliance requirements.

## External interfaces
> User, hardware, software and communication interfaces.

## Data requirements
> Key entities, retention and privacy requirements.

## Open questions
> Items awaiting a decision, with owner.
```

`templates/doc-templates/test-cases.md`:

```markdown
# Test Cases

## Test suites
> Suites with their purpose and related requirements.

## Test cases
> Identifier, title, preconditions, steps, expected result, requirement references.
```

`templates/doc-templates/test-plan.md`:

```markdown
# Test Plan

## Scope and objectives
> Features in and out of test scope and the quality goals.

## Test strategy
> Test levels, types, automation approach and tools.

## Environments and data
> Test environments, test data sources and anonymisation.

## Schedule and resources
> Phases, milestones, roles.

## Entry and exit criteria
> Conditions to start and to finish each test phase.

## Risks
> Testing risks and mitigations.
```

`templates/doc-templates/test-report.md`:

```markdown
# Test Report

## Summary
> Period, scope, overall verdict.

## Results
> Executed, passed, failed, blocked per suite.

## Defects
> Open defects with severity and status.

## Recommendations
> Release recommendation and follow-up actions.
```

`templates/doc-templates/use-cases.md`:

```markdown
# Use Cases

## Actors
> Human and system actors with a one-line description each.

## Use case list
> Identifier, name, primary actor, goal.

## Use case details
> For each use case: preconditions, main flow, alternative flows, postconditions.
```

`templates/doc-templates/user-stories.md`:

```markdown
# User Stories

## Epics
> Grouping of stories by business capability.

## Stories
> For each story: identifier, "As a ... I want ... so that ...", acceptance criteria, priority.

## Out of scope
> Stories explicitly deferred.
```

`templates/doc-templates/workflows.md`:

```markdown
# Workflows

## Overview
> The business or system processes this document covers.

## Workflow details
> For each workflow: trigger, steps, roles, decisions, outcomes.

## Exceptions and error paths
> What happens when a step fails or a decision is negative.
```


- [ ] **Step 3: Write the failing tests**

Create `backend/tests/ingestion/__init__.py` (empty).

`backend/tests/ingestion/test_taxonomy.py`:

```python
from pathlib import Path

import pytest

from app.ingestion.taxonomy import (
    TaxonomyError,
    UnknownDocType,
    default_templates_dir,
    load_taxonomy,
)

MINIMAL = """
version: 1
folders:
  - id: overview
    dir: 01-overview
    stage: Why
    doc_types:
      - {{ id: readme, title: Project README, required: true, template: readme.md{extra} }}
"""


def _write(tmp_path: Path, yaml_text: str, templates: tuple[str, ...] = ("readme.md",)) -> Path:
    (tmp_path / "doc-templates").mkdir()
    for name in templates:
        (tmp_path / "doc-templates" / name).write_text("# Template\n")
    (tmp_path / "taxonomy.yaml").write_text(yaml_text)
    return tmp_path


def test_default_taxonomy_matches_spec() -> None:
    taxonomy = load_taxonomy(default_templates_dir())
    assert taxonomy.version == 1
    assert [f.dir for f in taxonomy.folders] == [
        "01-overview",
        "02-requirements",
        "03-design",
        "04-source",
        "05-testing",
        "06-deployment",
    ]
    real_types = [t for t in taxonomy.doc_types if not t.is_other]
    assert len(real_types) == 20
    assert {t.key for t in taxonomy.required_types()} == {
        "readme",
        "project-charter",
        "brd",
        "srs",
        "architecture-c4",
        "repo-structure",
        "test-plan",
        "test-cases",
        "deploy-guide",
        "runbook",
    }
    adr = taxonomy.resolve("adr")
    assert adr.multi is True and adr.document_dir == "04-source/adr"
    assert taxonomy.resolve("api-spec").normalize is False
    assert taxonomy.resolve("srs").document_dir == "02-requirements"
    for doc_type in real_types:
        assert taxonomy.template_text(doc_type).startswith(f"# {doc_type.title}")


def test_every_folder_accepts_other() -> None:
    taxonomy = load_taxonomy(default_templates_dir())
    for folder in taxonomy.folders:
        other = taxonomy.resolve(f"{folder.id}/other")
        assert other.is_other and other.required is False and other.normalize is False
        assert other.folder_dir == folder.dir and other.template is None
    with pytest.raises(UnknownDocType):
        taxonomy.resolve("other")
    with pytest.raises(UnknownDocType):
        taxonomy.resolve("nonsense")


def test_minimal_file_loads(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(_write(tmp_path, MINIMAL.format(extra="")))
    assert [t.key for t in taxonomy.doc_types] == ["readme", "overview/other"]


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        (MINIMAL.format(extra=", template: missing.md"), "does not exist"),
        (MINIMAL.format(extra=", multi: true"), "need a 'subdir'"),
        (MINIMAL.format(extra=", subdir: x"), "only allowed with multi"),
        (MINIMAL.format(extra=", colour: red"), "unknown doc_type keys"),
        (MINIMAL.format(extra="").replace("version: 1", "version: zero"), "positive integer"),
        (MINIMAL.format(extra="").replace("01-overview", "overview"), "02-requirements"),
    ],
)
def test_validation_errors(tmp_path: Path, yaml_text: str, message: str) -> None:
    with pytest.raises(TaxonomyError, match=message):
        load_taxonomy(_write(tmp_path, yaml_text))


def test_duplicate_doc_type_id_is_rejected(tmp_path: Path) -> None:
    duplicated = MINIMAL.format(extra="") + (
        "  - id: requirements\n    dir: 02-requirements\n    stage: What\n    doc_types:\n"
        "      - { id: readme, title: Again, template: readme.md }\n"
    )
    with pytest.raises(TaxonomyError, match="defined twice"):
        load_taxonomy(_write(tmp_path, duplicated))


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TaxonomyError, match="not found"):
        load_taxonomy(tmp_path)
```

`backend/tests/api/test_taxonomy_api.py`:

```python
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from tests.factories import make_session_token, make_user

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def test_taxonomy_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/taxonomy")).status_code == 401


async def test_taxonomy_lists_folders_types_and_other(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings, account_type="customer", email="c@client.com")
    c = await make_client(await make_session_token(db, settings, user))
    response = await c.get("/api/v1/taxonomy")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert [f["dir"] for f in body["folders"]][:2] == ["01-overview", "02-requirements"]
    requirements = body["folders"][1]
    assert requirements["doc_types"][1] == {
        "key": "srs",
        "id": "srs",
        "title": "Software Requirements Specification",
        "required": True,
        "normalize": True,
        "multi": False,
    }
    assert requirements["doc_types"][-1]["key"] == "requirements/other"
    assert requirements["doc_types"][-1]["required"] is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_taxonomy.py tests/api/test_taxonomy_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion'`.

- [ ] **Step 5: Implement the loader, schema, route and wiring**

Create `backend/app/ingestion/__init__.py` (empty).

`backend/app/ingestion/taxonomy.py`:

```python
"""Document taxonomy loaded from ``templates/taxonomy.yaml`` (spec 5.2).

The taxonomy is data, not code: folders, document types, which types are required,
which are normalised and where ``multi`` types live. Every folder implicitly accepts an
``other`` type whose key is ``<folder-id>/other``.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

OTHER = "other"
_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_DIR_RE = re.compile(r"^[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*$")
_FOLDER_KEYS = {"id", "dir", "stage", "doc_types"}
_DOC_TYPE_KEYS = {"id", "title", "required", "template", "normalize", "multi", "subdir"}


class TaxonomyError(ValueError):
    """The taxonomy file is missing, malformed or inconsistent."""


class UnknownDocType(KeyError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


@dataclass(frozen=True)
class DocType:
    id: str
    key: str
    title: str
    folder_id: str
    folder_dir: str
    required: bool = False
    template: str | None = None
    normalize: bool = True
    multi: bool = False
    subdir: str | None = None

    @property
    def is_other(self) -> bool:
        return self.id == OTHER

    @property
    def document_dir(self) -> str:
        """Storage folder (relative to the project root) that holds this type's files."""
        if self.multi and self.subdir:
            return f"{self.folder_dir}/{self.subdir}"
        return self.folder_dir


@dataclass(frozen=True)
class Folder:
    id: str
    dir: str
    stage: str
    doc_types: tuple[DocType, ...]


@dataclass(frozen=True)
class Taxonomy:
    version: int
    folders: tuple[Folder, ...]
    templates_dir: Path

    @property
    def doc_types(self) -> list[DocType]:
        return [doc_type for folder in self.folders for doc_type in folder.doc_types]

    def resolve(self, key: str) -> DocType:
        for doc_type in self.doc_types:
            if doc_type.key == key:
                return doc_type
        raise UnknownDocType(key)

    def folder(self, folder_id: str) -> Folder:
        for folder in self.folders:
            if folder.id == folder_id:
                return folder
        raise TaxonomyError(f"Unknown folder {folder_id!r}.")

    def required_types(self) -> list[DocType]:
        return [doc_type for doc_type in self.doc_types if doc_type.required]

    def template_text(self, doc_type: DocType) -> str:
        if doc_type.template is None:
            raise TaxonomyError(f"Document type {doc_type.key!r} has no template.")
        return (self.templates_dir / "doc-templates" / doc_type.template).read_text(
            encoding="utf-8"
        )


def default_templates_dir() -> Path:
    """``<repository root>/templates`` (this file lives in ``backend/app/ingestion/``)."""
    return Path(__file__).resolve().parents[3] / "templates"


def _require_str(mapping: Mapping[str, Any], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TaxonomyError(f"{where}: {key!r} must be a non-empty string.")
    return value


def _optional_bool(mapping: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise TaxonomyError(f"{where}: {key!r} must be true or false.")
    return value


def _parse_doc_type(raw: Any, folder_id: str, folder_dir: str, templates_dir: Path) -> DocType:
    where = f"folder {folder_id!r}"
    if not isinstance(raw, Mapping):
        raise TaxonomyError(f"{where}: each doc_type must be a mapping.")
    unknown = set(raw) - _DOC_TYPE_KEYS
    if unknown:
        raise TaxonomyError(f"{where}: unknown doc_type keys {sorted(unknown)}.")
    doc_id = _require_str(raw, "id", where)
    where = f"doc type {doc_id!r}"
    if not _ID_RE.fullmatch(doc_id) or doc_id == OTHER:
        raise TaxonomyError(f"{where}: id must be lowercase letters, digits and hyphens.")
    template = _require_str(raw, "template", where)
    if not template.endswith(".md") or "/" in template:
        raise TaxonomyError(f"{where}: template must be a .md file name.")
    if not (templates_dir / "doc-templates" / template).is_file():
        raise TaxonomyError(f"{where}: template file {template!r} does not exist.")
    multi = _optional_bool(raw, "multi", False, where)
    subdir = raw.get("subdir")
    if multi:
        if not isinstance(subdir, str) or not _ID_RE.fullmatch(subdir):
            raise TaxonomyError(f"{where}: multi types need a 'subdir' (lowercase, hyphens).")
    elif subdir is not None:
        raise TaxonomyError(f"{where}: 'subdir' is only allowed with multi: true.")
    return DocType(
        id=doc_id,
        key=doc_id,
        title=_require_str(raw, "title", where),
        folder_id=folder_id,
        folder_dir=folder_dir,
        required=_optional_bool(raw, "required", False, where),
        template=template,
        normalize=_optional_bool(raw, "normalize", True, where),
        multi=multi,
        subdir=subdir if multi else None,
    )


def _other_type(folder_id: str, folder_dir: str) -> DocType:
    return DocType(
        id=OTHER,
        key=f"{folder_id}/{OTHER}",
        title="Other",
        folder_id=folder_id,
        folder_dir=folder_dir,
        required=False,
        template=None,
        normalize=False,
    )


def _parse_folder(raw: Any, templates_dir: Path) -> Folder:
    if not isinstance(raw, Mapping):
        raise TaxonomyError("each folder must be a mapping.")
    unknown = set(raw) - _FOLDER_KEYS
    if unknown:
        raise TaxonomyError(f"folder: unknown keys {sorted(unknown)}.")
    folder_id = _require_str(raw, "id", "folder")
    where = f"folder {folder_id!r}"
    if not _ID_RE.fullmatch(folder_id):
        raise TaxonomyError(f"{where}: id must be lowercase letters, digits and hyphens.")
    folder_dir = _require_str(raw, "dir", where)
    if not _DIR_RE.fullmatch(folder_dir):
        raise TaxonomyError(f"{where}: dir must look like '02-requirements'.")
    stage = _require_str(raw, "stage", where)
    raw_types = raw.get("doc_types")
    if not isinstance(raw_types, list) or not raw_types:
        raise TaxonomyError(f"{where}: doc_types must be a non-empty list.")
    doc_types = [_parse_doc_type(t, folder_id, folder_dir, templates_dir) for t in raw_types]
    doc_types.append(_other_type(folder_id, folder_dir))
    return Folder(id=folder_id, dir=folder_dir, stage=stage, doc_types=tuple(doc_types))


def parse_taxonomy(data: Any, templates_dir: Path) -> Taxonomy:
    if not isinstance(data, Mapping):
        raise TaxonomyError("taxonomy.yaml must be a mapping with 'version' and 'folders'.")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TaxonomyError("'version' must be a positive integer.")
    raw_folders = data.get("folders")
    if not isinstance(raw_folders, list) or not raw_folders:
        raise TaxonomyError("'folders' must be a non-empty list.")
    folders = tuple(_parse_folder(f, templates_dir) for f in raw_folders)
    seen_ids: set[str] = set()
    seen_dirs: set[str] = set()
    seen_types: set[str] = set()
    for folder in folders:
        if folder.id in seen_ids or folder.dir in seen_dirs:
            raise TaxonomyError(f"folder {folder.id!r}: duplicate id or dir.")
        seen_ids.add(folder.id)
        seen_dirs.add(folder.dir)
        for doc_type in folder.doc_types:
            if doc_type.is_other:
                continue
            if doc_type.id in seen_types:
                raise TaxonomyError(f"doc type {doc_type.id!r} is defined twice.")
            seen_types.add(doc_type.id)
    return Taxonomy(version=version, folders=folders, templates_dir=templates_dir)


def load_taxonomy(templates_dir: Path | None = None) -> Taxonomy:
    root = templates_dir or default_templates_dir()
    path = root / "taxonomy.yaml"
    if not path.is_file():
        raise TaxonomyError(f"Taxonomy file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaxonomyError(f"Taxonomy file is not valid YAML: {exc}") from exc
    return parse_taxonomy(data, root)
```

`backend/app/schemas/taxonomy.py`:

```python
from pydantic import BaseModel

from app.ingestion.taxonomy import Taxonomy


class DocTypeOut(BaseModel):
    key: str
    id: str
    title: str
    required: bool
    normalize: bool
    multi: bool


class FolderOut(BaseModel):
    id: str
    dir: str
    stage: str
    doc_types: list[DocTypeOut]


class TaxonomyOut(BaseModel):
    version: int
    folders: list[FolderOut]

    @classmethod
    def from_taxonomy(cls, taxonomy: Taxonomy) -> "TaxonomyOut":
        return cls(
            version=taxonomy.version,
            folders=[
                FolderOut(
                    id=folder.id,
                    dir=folder.dir,
                    stage=folder.stage,
                    doc_types=[
                        DocTypeOut(
                            key=t.key,
                            id=t.id,
                            title=t.title,
                            required=t.required,
                            normalize=t.normalize,
                            multi=t.multi,
                        )
                        for t in folder.doc_types
                    ],
                )
                for folder in taxonomy.folders
            ],
        )
```

`backend/app/api/routes/taxonomy.py`:

```python
from fastapi import APIRouter

from app.api.deps import CurrentUser, TaxonomyDep
from app.schemas.taxonomy import TaxonomyOut

router = APIRouter(tags=["meta"])


@router.get("/taxonomy", response_model=TaxonomyOut)
async def get_taxonomy(_: CurrentUser, taxonomy: TaxonomyDep) -> TaxonomyOut:
    return TaxonomyOut.from_taxonomy(taxonomy)
```

Append to `backend/app/api/deps.py` directly after `DbSession = Annotated[AsyncSession, Depends(get_session)]`, and add `from app.ingestion.taxonomy import Taxonomy` to the imports:

```python
def taxonomy_dep(request: Request) -> Taxonomy:
    taxonomy: Taxonomy = request.app.state.taxonomy
    return taxonomy


TaxonomyDep = Annotated[Taxonomy, Depends(taxonomy_dep)]
```

Replace `backend/app/main.py` (loads and validates the taxonomy when the app is created, stores it on `app.state`, registers the router):

```python
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes import auth, health, projects, users
from app.api.routes import taxonomy as taxonomy_routes
from app.core.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.db.session import dispose_engine, init_engine, is_initialised
from app.ingestion.taxonomy import load_taxonomy

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-qc-agent"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    templates_dir = Path(app_settings.templates_dir) if app_settings.templates_dir else None
    taxonomy = load_taxonomy(templates_dir)  # validates the taxonomy at startup

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not is_initialised():
            init_engine(app_settings.database_url)
        yield
        await dispose_engine()

    app = FastAPI(
        title="QC-Agent",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs" if app_settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if app_settings.expose_docs else None,
    )
    app.state.settings = app_settings
    app.state.taxonomy = taxonomy
    app.state.auth_limiter = SlidingWindowLimiter(
        limit=app_settings.rate_limit_auth_per_5min, window_seconds=300
    )

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "Missing CSRF header."}, status_code=403)
        return await call_next(request)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(users.router, prefix=API_PREFIX)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(taxonomy_routes.router, prefix=API_PREFIX)
    return app
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_taxonomy.py tests/api/test_taxonomy_api.py -v`
Expected: `13 passed` (11 taxonomy, 2 API).

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd ..
git add templates backend/pyproject.toml backend/uv.lock backend/app backend/tests
git commit -m "feat(backend): add taxonomy data, document templates and GET /taxonomy"
cd backend
```

---

### Task 3: `StorageBackend` protocol, `LocalFsBackend`, backend selection and the contract suite

**Files:**
- Create: `backend/app/storage/__init__.py`, `backend/app/storage/base.py`, `backend/app/storage/localfs.py`, `backend/app/storage/select.py`
- Test: `backend/tests/storage/__init__.py` (empty), `backend/tests/storage/conftest.py`, `backend/tests/storage/test_contract.py`, `backend/tests/storage/test_localfs.py`

**Interfaces:**
- Consumes: `Settings.local_storage_root` (Task 2).
- Produces:
  - `app.storage.base`: `StorageBackend` protocol with `async ensure_folder(path)`, `async put_file(path, data: bytes, content_type: str) -> StoredFile`, `async get_file(path) -> bytes`, `async exists(path) -> bool`, `async list_versions(path) -> list[StoredVersion]`, `async get_version(path, version_id) -> bytes`, `async move_to_trash(path)`, `async health() -> HealthStatus`; dataclasses `StoredFile(item_id, version_id, web_url=None)`, `StoredVersion(version_id, size, modified_at)`, `HealthStatus(ok, detail)`; exceptions `StorageError` > `StoragePathError`, `StorageNotFound`; `normalize_path(path) -> str`; `RESERVED_TOP_LEVEL = {".versions", ".trash"}`.
  - `app.storage.localfs.LocalFsBackend(root: Path)` with `.root`; version ids are `"1"`, `"2"`, … per path (the current file is the highest; older content lives in `.versions/<path>/<n>`).
  - `app.storage.select.backend_for(storage: Mapping[str, Any], settings) -> StorageBackend` (`StorageError` for unknown types), `localfs_binding(root) -> {"type": "localfs", "root": root}`, constant `LOCALFS`.
  - Test fixture `backend` in `tests/storage/conftest.py`, parametrised with `"localfs"`; Plan 3 adds `"sharepoint"` and `"gdrive"` params behind `QC_AGENT_LIVE_STORAGE=1` and the contract tests run unchanged.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/storage/__init__.py` (empty).

`backend/tests/storage/conftest.py`:

```python
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
```

`backend/tests/storage/test_contract.py`:

```python
"""Every StorageBackend adapter must pass this suite unchanged."""

import pytest

from app.storage.base import StorageBackend, StorageNotFound, StoragePathError

PATH = "02-requirements/srs--customer-portal.docx"
BAD_PATHS = [
    "../escape.txt",
    "/abs.txt",
    "C:/x.txt",
    "a/../../b",
    "",
    ".",
    "a\\b.txt",
    ".versions/x",
]


async def test_put_get_roundtrip_creates_folders(backend: StorageBackend) -> None:
    stored = await backend.put_file(PATH, b"v1", "application/octet-stream")
    assert stored.item_id and stored.version_id
    assert await backend.get_file(PATH) == b"v1"
    assert await backend.exists(PATH) is True
    assert await backend.exists("02-requirements/missing.docx") is False


async def test_overwrite_keeps_versions(backend: StorageBackend) -> None:
    first = await backend.put_file(PATH, b"v1", "application/octet-stream")
    second = await backend.put_file(PATH, b"v2", "application/octet-stream")
    assert first.version_id != second.version_id
    versions = await backend.list_versions(PATH)
    assert [v.version_id for v in versions] == [first.version_id, second.version_id]
    assert all(v.size > 0 for v in versions)
    assert await backend.get_version(PATH, first.version_id) == b"v1"
    assert await backend.get_version(PATH, second.version_id) == b"v2"
    assert await backend.get_file(PATH) == b"v2"


async def test_ensure_folder_is_idempotent(backend: StorageBackend) -> None:
    await backend.ensure_folder("05-testing/test-reports")
    await backend.ensure_folder("05-testing/test-reports")
    await backend.put_file(
        "05-testing/test-reports/test-report--sprint-1.md", b"# r", "text/markdown"
    )
    assert await backend.exists("05-testing/test-reports/test-report--sprint-1.md")


async def test_missing_file_and_version(backend: StorageBackend) -> None:
    with pytest.raises(StorageNotFound):
        await backend.get_file(PATH)
    await backend.put_file(PATH, b"v1", "application/octet-stream")
    with pytest.raises(StorageNotFound):
        await backend.get_version(PATH, "does-not-exist")
    with pytest.raises(StorageNotFound):
        await backend.move_to_trash("02-requirements/nothing.md")


async def test_move_to_trash(backend: StorageBackend) -> None:
    await backend.put_file(PATH, b"v1", "application/octet-stream")
    await backend.move_to_trash(PATH)
    assert await backend.exists(PATH) is False
    with pytest.raises(StorageNotFound):
        await backend.get_file(PATH)


async def test_unicode_and_spaces_in_names(backend: StorageBackend) -> None:
    path = "01-overview/other--tài liệu (bản cuối).md"
    await backend.put_file(path, "Nội dung".encode(), "text/markdown")
    assert (await backend.get_file(path)).decode() == "Nội dung"


@pytest.mark.parametrize("bad", BAD_PATHS)
async def test_unsafe_paths_are_rejected_everywhere(backend: StorageBackend, bad: str) -> None:
    with pytest.raises(StoragePathError):
        await backend.put_file(bad, b"x", "text/plain")
    with pytest.raises(StoragePathError):
        await backend.get_file(bad)
    with pytest.raises(StoragePathError):
        await backend.exists(bad)
    with pytest.raises(StoragePathError):
        await backend.ensure_folder(bad)
    with pytest.raises(StoragePathError):
        await backend.list_versions(bad)
    with pytest.raises(StoragePathError):
        await backend.get_version(bad, "1")
    with pytest.raises(StoragePathError):
        await backend.move_to_trash(bad)


async def test_health(backend: StorageBackend) -> None:
    status = await backend.health()
    assert status.ok is True
```

`backend/tests/storage/test_localfs.py`:

```python
import os
from pathlib import Path

import pytest

from app.storage.base import StoragePathError
from app.storage.localfs import LocalFsBackend


async def test_layout_on_disk(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path / "root")
    await backend.put_file("02-requirements/srs--a.md", b"one", "text/markdown")
    await backend.put_file("02-requirements/srs--a.md", b"two", "text/markdown")
    assert (tmp_path / "root/02-requirements/srs--a.md").read_bytes() == b"two"
    assert (tmp_path / "root/.versions/02-requirements/srs--a.md/1").read_bytes() == b"one"
    await backend.move_to_trash("02-requirements/srs--a.md")
    assert (tmp_path / "root/.trash/02-requirements/srs--a.md").read_bytes() == b"two"
    assert not list((tmp_path / "root/02-requirements").glob("*.tmp-*"))


async def test_symlink_inside_root_cannot_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "03-design")
    backend = LocalFsBackend(root)
    with pytest.raises(StoragePathError):
        await backend.put_file("03-design/leak.md", b"x", "text/markdown")
    assert not (outside / "leak.md").exists()


async def test_health_reports_unwritable_root(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    status = await LocalFsBackend(blocker / "root").health()
    assert status.ok is False and "not writable" in status.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/storage -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.storage'`.

- [ ] **Step 3: Implement the interface, the local adapter and the selector**

`backend/app/storage/base.py`:

```python
"""Storage backend interface shared by the local, SharePoint and Google Drive adapters (spec 8.1).

Every path is relative to the project root, uses ``/`` as separator and is normalised by
``normalize_path`` before any adapter touches it.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

RESERVED_TOP_LEVEL = frozenset({".versions", ".trash"})
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class StorageError(Exception):
    """Base class for storage failures; the message is safe to show to users."""


class StoragePathError(StorageError):
    """The path is absolute, escapes the project root, or uses reserved names."""


class StorageNotFound(StorageError):
    """The file or version does not exist."""


@dataclass(frozen=True)
class StoredFile:
    item_id: str
    version_id: str
    web_url: str | None = None


@dataclass(frozen=True)
class StoredVersion:
    version_id: str
    size: int
    modified_at: datetime


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    detail: str = ""


def normalize_path(path: str) -> str:
    if "\\" in path or _CONTROL_RE.search(path):
        raise StoragePathError("Path contains characters that are not allowed.")
    if path.startswith("/") or _DRIVE_RE.match(path):
        raise StoragePathError("Path must be relative to the project root.")
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if not parts:
        raise StoragePathError("Path is empty.")
    if ".." in parts:
        raise StoragePathError("Path must not contain '..'.")
    if parts[0] in RESERVED_TOP_LEVEL:
        raise StoragePathError("Path uses a reserved folder name.")
    return "/".join(parts)


class StorageBackend(Protocol):
    async def ensure_folder(self, path: str) -> None: ...

    async def put_file(self, path: str, data: bytes, content_type: str) -> StoredFile: ...

    async def get_file(self, path: str) -> bytes: ...

    async def exists(self, path: str) -> bool: ...

    async def list_versions(self, path: str) -> list[StoredVersion]: ...

    async def get_version(self, path: str, version_id: str) -> bytes: ...

    async def move_to_trash(self, path: str) -> None: ...

    async def health(self) -> HealthStatus: ...
```

`backend/app/storage/localfs.py`:

```python
"""Local filesystem adapter (spec 8.4): files under a root folder, versions as
``.versions/<path>/<n>``, trashed files under ``.trash/<path>``. All blocking I/O runs in a
worker thread so the event loop stays free."""

import asyncio
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.storage.base import (
    HealthStatus,
    StorageNotFound,
    StoragePathError,
    StoredFile,
    StoredVersion,
    normalize_path,
)

VERSIONS_DIR = ".versions"
TRASH_DIR = ".trash"


class LocalFsBackend:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    # -- path safety (synchronous helpers) -------------------------------------------------

    def _target(self, path: str) -> Path:
        relative = normalize_path(path)
        root = self._root.resolve()
        current = root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink():
                raise StoragePathError("Path goes through a symbolic link.")
        resolved = current.resolve()
        if resolved != root and root not in resolved.parents:
            raise StoragePathError("Path escapes the project root.")
        return current

    def _versions_dir(self, path: str) -> Path:
        return self._root / VERSIONS_DIR / normalize_path(path)

    @staticmethod
    def _archived_count(versions_dir: Path) -> int:
        if not versions_dir.is_dir():
            return 0
        return sum(1 for entry in versions_dir.iterdir() if entry.name.isdigit())

    # -- synchronous implementations -------------------------------------------------------

    def _ensure_folder_sync(self, path: str) -> None:
        self._target(path).mkdir(parents=True, exist_ok=True)

    def _put_sync(self, path: str, data: bytes) -> StoredFile:
        target = self._target(path)
        if target.is_dir():
            raise StoragePathError("Path is a folder.")
        target.parent.mkdir(parents=True, exist_ok=True)
        versions_dir = self._versions_dir(path)
        archived = self._archived_count(versions_dir)
        if target.exists():
            versions_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, versions_dir / str(archived + 1))
            archived += 1
        tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return StoredFile(item_id=normalize_path(path), version_id=str(archived + 1))

    def _get_sync(self, path: str) -> bytes:
        target = self._target(path)
        if not target.is_file():
            raise StorageNotFound(f"File not found: {normalize_path(path)}")
        return target.read_bytes()

    def _exists_sync(self, path: str) -> bool:
        return self._target(path).is_file()

    def _list_versions_sync(self, path: str) -> list[StoredVersion]:
        target = self._target(path)
        versions_dir = self._versions_dir(path)
        versions: list[StoredVersion] = []
        archived = self._archived_count(versions_dir)
        for number in range(1, archived + 1):
            stat = (versions_dir / str(number)).stat()
            versions.append(
                StoredVersion(
                    version_id=str(number),
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )
            )
        if target.is_file():
            stat = target.stat()
            versions.append(
                StoredVersion(
                    version_id=str(archived + 1),
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )
            )
        return versions

    def _get_version_sync(self, path: str, version_id: str) -> bytes:
        target = self._target(path)
        versions_dir = self._versions_dir(path)
        archived = self._archived_count(versions_dir)
        if not version_id.isdigit():
            raise StorageNotFound(f"Version not found: {version_id}")
        number = int(version_id)
        if number == archived + 1 and target.is_file():
            return target.read_bytes()
        if 1 <= number <= archived:
            return (versions_dir / str(number)).read_bytes()
        raise StorageNotFound(f"Version not found: {version_id}")

    def _move_to_trash_sync(self, path: str) -> None:
        target = self._target(path)
        if not target.is_file():
            raise StorageNotFound(f"File not found: {normalize_path(path)}")
        destination = self._root / TRASH_DIR / normalize_path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(target, destination)

    def _health_sync(self) -> HealthStatus:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / f".health-{uuid.uuid4().hex}"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            return HealthStatus(ok=False, detail=f"Storage root is not writable ({exc.strerror})")
        return HealthStatus(ok=True, detail="ok")

    # -- StorageBackend protocol -----------------------------------------------------------

    async def ensure_folder(self, path: str) -> None:
        await asyncio.to_thread(self._ensure_folder_sync, path)

    async def put_file(self, path: str, data: bytes, content_type: str) -> StoredFile:
        return await asyncio.to_thread(self._put_sync, path, data)

    async def get_file(self, path: str) -> bytes:
        return await asyncio.to_thread(self._get_sync, path)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._exists_sync, path)

    async def list_versions(self, path: str) -> list[StoredVersion]:
        return await asyncio.to_thread(self._list_versions_sync, path)

    async def get_version(self, path: str, version_id: str) -> bytes:
        return await asyncio.to_thread(self._get_version_sync, path, version_id)

    async def move_to_trash(self, path: str) -> None:
        await asyncio.to_thread(self._move_to_trash_sync, path)

    async def health(self) -> HealthStatus:
        return await asyncio.to_thread(self._health_sync)
```

`backend/app/storage/select.py`:

```python
"""Pick the storage adapter for a project's ``storage`` binding."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.storage.base import StorageBackend, StorageError
from app.storage.localfs import LocalFsBackend

LOCALFS = "localfs"


def localfs_binding(root: str) -> dict[str, Any]:
    return {"type": LOCALFS, "root": root}


def backend_for(storage: Mapping[str, Any], settings: Settings) -> StorageBackend:
    kind = storage.get("type")
    if kind == LOCALFS:
        root = storage.get("root")
        if not isinstance(root, str) or not root:
            raise StorageError("Project storage binding is incomplete.")
        return LocalFsBackend(Path(settings.local_storage_root) / root)
    raise StorageError(f"Storage type {kind!r} is not available in this deployment.")
```

`backend/app/storage/__init__.py`:

```python
from app.storage.base import (
    HealthStatus,
    StorageBackend,
    StorageError,
    StorageNotFound,
    StoragePathError,
    StoredFile,
    StoredVersion,
    normalize_path,
)

__all__ = [
    "HealthStatus",
    "StorageBackend",
    "StorageError",
    "StorageNotFound",
    "StoragePathError",
    "StoredFile",
    "StoredVersion",
    "normalize_path",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/storage -v`
Expected: `18 passed` (15 contract including 8 unsafe-path cases, 3 local-only).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app/storage backend/tests/storage
git commit -m "feat(backend): add StorageBackend interface, local adapter and contract suite"
```

---

### Task 4: Naming, frontmatter, stubs, gap report and version suggestions (pure functions)

**Files:**
- Create: `backend/app/ingestion/naming.py`, `backend/app/ingestion/stubs.py`, `backend/app/ingestion/gaps.py`, `backend/app/ingestion/versioning.py`
- Test: `backend/tests/ingestion/test_naming.py`, `backend/tests/ingestion/test_versioning.py`, `backend/tests/ingestion/test_gaps.py`

**Interfaces:**
- Consumes: `slugify` (Plan 1), `DocType`, `Taxonomy` (Task 2).
- Produces:
  - `app.ingestion.naming`: `title_slug(title) -> str`, `title_from_filename(name) -> str`, `original_path(doc_type, slug, ext)`, `markdown_path(doc_type, slug)`, `normalized_path(doc_type, slug)`, `stub_path(doc_type)`; `Frontmatter` dataclass (fields in the Global Constraints order), `render_frontmatter(fm) -> str`, `render_markdown_file(fm, body) -> str`, `split_frontmatter(text) -> tuple[dict, str]`; constants `QC_AGENT_FORMAT = 2`, `MARKDOWN_EXT`, `NORMALIZED_SUFFIX`.
  - `app.ingestion.stubs.render_stub(doc_type, template_text, fm) -> str`, `STUB_NOTICE`.
  - `app.ingestion.gaps`: `DocumentFact(doc_type, is_stub)`, `GapEntry`, `GapFolder`, `GapReport` (`.required_total`, `.required_present`, `.completeness`, `.to_dict()`), `build_gap_report(taxonomy, facts, *, project_slug, project_name, generated_at) -> GapReport`, `render_gap_report_markdown(report) -> str`, statuses `PRESENT`, `STUB`, `MISSING`.
  - `app.ingestion.versioning`: `VersionCandidate(document_id, title, slug, current_version)`, `VersionSuggestion(document_id, title, current_version, similarity)`, `suggest_versions(title, candidates) -> list[VersionSuggestion]`, `SIMILARITY_THRESHOLD = 0.8`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/ingestion/test_naming.py`:

```python
from datetime import UTC, datetime

from app.ingestion.naming import (
    Frontmatter,
    markdown_path,
    normalized_path,
    original_path,
    render_markdown_file,
    split_frontmatter,
    stub_path,
    title_from_filename,
    title_slug,
)
from app.ingestion.taxonomy import default_templates_dir, load_taxonomy

TAXONOMY = load_taxonomy(default_templates_dir())
UPLOADED_AT = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def _frontmatter(**overrides: object) -> Frontmatter:
    values: dict[str, object] = {
        "document_id": "01J9ABCDEF",
        "version": 3,
        "doc_type": "srs",
        "folder": "02-requirements",
        "title": "Cổng Khách hàng SRS",
        "kind": "converted",
        "source_file": "srs--cong-khach-hang-srs.docx",
        "source_sha256": "3f1c" * 16,
        "uploaded_by": "Nguyen Van A",
        "uploaded_at": UPLOADED_AT,
        "type_selected_by_user": "srs",
        "type_check": "match",
        "language": "vi",
        "visibility": "internal",
    }
    values.update(overrides)
    return Frontmatter(**values)  # type: ignore[arg-type]


def test_paths_follow_the_naming_convention() -> None:
    srs = TAXONOMY.resolve("srs")
    assert (
        original_path(srs, "customer-portal", "docx") == "02-requirements/srs--customer-portal.docx"
    )
    assert markdown_path(srs, "customer-portal") == "02-requirements/srs--customer-portal.md"
    assert (
        normalized_path(srs, "customer-portal")
        == "02-requirements/srs--customer-portal.normalized.md"
    )
    assert stub_path(srs) == "02-requirements/srs.md"
    adr = TAXONOMY.resolve("adr")
    assert original_path(adr, "use-postgres", "md") == "04-source/adr/adr--use-postgres.md"
    other = TAXONOMY.resolve("design/other")
    assert original_path(other, "notes", "pdf") == "03-design/other--notes.pdf"


def test_title_helpers() -> None:
    assert title_slug("Dự án Cổng Khách hàng") == "du-an-cong-khach-hang"
    assert title_from_filename("srs_customer-portal v2.docx") == "srs customer portal v2"
    assert title_from_filename("C:\\Users\\x\\Report.pdf") == "Report"
    assert title_from_filename(".docx") == "Untitled"


def test_frontmatter_round_trip() -> None:
    text = render_markdown_file(_frontmatter(), "# SRS\n\nBody text.\n\n")
    assert text.startswith("---\nqc_agent: 2\ndocument_id: 01J9ABCDEF\nversion: 3\n")
    assert text.endswith("---\n\n# SRS\n\nBody text.\n")
    data, body = split_frontmatter(text)
    assert data["title"] == "Cổng Khách hàng SRS"
    assert data["uploaded_by"] == "Nguyen Van A" and "@" not in text
    assert data["uploaded_at"] == "2026-10-01T09:30:00+00:00"
    assert data["normalized_approved_by"] is None
    assert list(data)[:3] == ["qc_agent", "document_id", "version"]
    assert body == "# SRS\n\nBody text.\n"


def test_stub_and_null_fields_render() -> None:
    text = render_markdown_file(
        _frontmatter(kind="stub", source_file=None, source_sha256=None, language=None), "x"
    )
    data, _ = split_frontmatter(text)
    assert data["kind"] == "stub" and data["source_file"] is None and data["language"] is None
```

`backend/tests/ingestion/test_versioning.py`:

```python
import uuid

from app.ingestion.versioning import VersionCandidate, suggest_versions


def _candidate(title: str, slug: str, version: int = 1) -> VersionCandidate:
    return VersionCandidate(
        document_id=uuid.uuid4(), title=title, slug=slug, current_version=version
    )


def test_similar_titles_are_suggested_in_order() -> None:
    portal = _candidate("Customer Portal SRS", "customer-portal-srs", 2)
    other = _candidate("Payments Gateway SRS", "payments-gateway-srs")
    close = _candidate("Customer Portal SRS v2", "customer-portal-srs-v2")
    result = suggest_versions("Customer Portal SRS (final)", [other, close, portal])
    assert [s.document_id for s in result] == [portal.document_id, close.document_id]
    assert result[0].current_version == 2 and result[0].similarity >= 0.8


def test_unrelated_titles_are_not_suggested() -> None:
    assert (
        suggest_versions("Runbook", [_candidate("Customer Portal SRS", "customer-portal-srs")])
        == []
    )
```

`backend/tests/ingestion/test_gaps.py`:

```python
import json
from datetime import UTC, datetime

from app.ingestion.gaps import (
    MISSING,
    PRESENT,
    STUB,
    DocumentFact,
    build_gap_report,
    render_gap_report_markdown,
)
from app.ingestion.naming import Frontmatter, split_frontmatter
from app.ingestion.stubs import render_stub
from app.ingestion.taxonomy import default_templates_dir, load_taxonomy

TAXONOMY = load_taxonomy(default_templates_dir())
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _report(facts: list[DocumentFact]):  # type: ignore[no-untyped-def]
    return build_gap_report(
        TAXONOMY, facts, project_slug="demo", project_name="Demo", generated_at=NOW
    )


def test_statuses_and_completeness() -> None:
    report = _report(
        [
            DocumentFact("srs", False),
            DocumentFact("srs", False),
            DocumentFact("readme", True),
            DocumentFact("requirements/other", False),
        ]
    )
    by_type = {e.doc_type: e for f in report.folders for e in f.entries}
    assert by_type["srs"].status == PRESENT and by_type["srs"].documents == 2
    assert by_type["readme"].status == STUB
    assert by_type["brd"].status == MISSING
    assert "requirements/other" not in by_type
    assert report.required_total == 10 and report.required_present == 1
    assert report.completeness == 0.1


def test_empty_project_has_zero_completeness_and_json_shape() -> None:
    report = _report([])
    data = json.loads(json.dumps(report.to_dict()))
    assert data["completeness"] == 0 and data["required_total"] == 10
    assert [f["dir"] for f in data["folders"]][0] == "01-overview"
    assert data["folders"][0]["doc_types"][0] == {
        "doc_type": "readme",
        "title": "Project README",
        "required": True,
        "status": "missing",
        "documents": 0,
    }


def test_markdown_rendering() -> None:
    text = render_gap_report_markdown(_report([DocumentFact("runbook", False)]))
    assert text.startswith("# Gap report: Demo\n")
    assert "Required document types present: 1 of 10 (10%)." in text
    assert "| Runbook | yes | present | 1 |" in text
    assert "| Release Notes | no | missing | 0 |" in text


def test_stub_rendering_uses_template_and_notice() -> None:
    srs = TAXONOMY.resolve("srs")
    fm = Frontmatter(
        document_id="doc",
        version=1,
        doc_type="srs",
        folder="02-requirements",
        title="Software Requirements Specification",
        kind="stub",
        source_file=None,
        source_sha256=None,
        uploaded_by="Owner",
        uploaded_at=NOW,
        type_selected_by_user="srs",
        type_check="skipped",
        language="en",
        visibility="internal",
    )
    text = render_stub(srs, TAXONOMY.template_text(srs), fm)
    data, body = split_frontmatter(text)
    assert data["kind"] == "stub"
    assert body.startswith(
        "> Placeholder: no Software Requirements Specification has been uploaded"
    )
    assert "# Software Requirements Specification" in body and "## Functional requirements" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_naming.py tests/ingestion/test_versioning.py tests/ingestion/test_gaps.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.naming'`.

- [ ] **Step 3: Implement**

`backend/app/ingestion/naming.py`:

```python
"""File names and Markdown frontmatter for the knowledge base (spec 5.3)."""

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

import yaml

from app.core.slugs import slugify
from app.ingestion.taxonomy import DocType

QC_AGENT_FORMAT = 2
MARKDOWN_EXT = "md"
NORMALIZED_SUFFIX = ".normalized.md"  # reserved for the agent plan
_SEPARATORS = re.compile(r"[_\-\s]+")


def title_slug(title: str) -> str:
    return slugify(title, max_len=80)


def title_from_filename(name: str) -> str:
    """Default document title: the file stem with separators turned into spaces."""
    base = PurePosixPath(name.replace("\\", "/")).name
    stem, dot, _ext = base.rpartition(".")
    cleaned = _SEPARATORS.sub(" ", stem if dot else base).strip()
    return cleaned[:200] or "Untitled"


def original_path(doc_type: DocType, slug: str, ext: str) -> str:
    return f"{doc_type.document_dir}/{doc_type.id}--{slug}.{ext}"


def markdown_path(doc_type: DocType, slug: str) -> str:
    return f"{doc_type.document_dir}/{doc_type.id}--{slug}.{MARKDOWN_EXT}"


def normalized_path(doc_type: DocType, slug: str) -> str:
    return f"{doc_type.document_dir}/{doc_type.id}--{slug}{NORMALIZED_SUFFIX}"


def stub_path(doc_type: DocType) -> str:
    return f"{doc_type.folder_dir}/{doc_type.id}.{MARKDOWN_EXT}"


@dataclass(frozen=True)
class Frontmatter:
    document_id: str
    version: int
    doc_type: str
    folder: str
    title: str
    kind: str  # converted | normalized | stub
    source_file: str | None
    source_sha256: str | None
    uploaded_by: str  # display name only, never an e-mail
    uploaded_at: datetime
    type_selected_by_user: str
    type_check: str  # match | mismatch_kept | mismatch_changed | skipped
    language: str | None
    visibility: str  # internal | shared


def render_frontmatter(fm: Frontmatter) -> str:
    data: dict[str, Any] = {"qc_agent": QC_AGENT_FORMAT}
    for key, value in asdict(fm).items():
        data[key] = value.isoformat() if isinstance(value, datetime) else value
    data["normalized_approved_by"] = None
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def render_markdown_file(fm: Frontmatter, body: str) -> str:
    return render_frontmatter(fm) + "\n" + body.strip("\n") + "\n"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body). Raises ValueError when there is no frontmatter."""
    if not text.startswith("---\n"):
        raise ValueError("Markdown file has no frontmatter.")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Frontmatter is not terminated.")
    data = yaml.safe_load(text[4:end])
    if not isinstance(data, dict):
        raise ValueError("Frontmatter is not a mapping.")
    return data, text[end + 5 :].lstrip("\n")
```

`backend/app/ingestion/stubs.py`:

```python
"""Stub documents for missing required types (spec 5.5)."""

from app.ingestion.naming import Frontmatter, render_markdown_file
from app.ingestion.taxonomy import DocType

STUB_NOTICE = (
    "> Placeholder: no {title} has been uploaded for this project yet. "
    "Upload one and this stub is replaced."
)


def render_stub(doc_type: DocType, template_text: str, fm: Frontmatter) -> str:
    body = STUB_NOTICE.format(title=doc_type.title) + "\n\n" + template_text.strip("\n")
    return render_markdown_file(fm, body)
```

`backend/app/ingestion/gaps.py`:

```python
"""Gap report: per folder, each document type is present, stub or missing (spec 5.5)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.ingestion.taxonomy import Taxonomy

PRESENT = "present"
STUB = "stub"
MISSING = "missing"


@dataclass(frozen=True)
class DocumentFact:
    """The two facts about a document the report needs; decoupled from the ORM."""

    doc_type: str  # taxonomy key
    is_stub: bool


@dataclass(frozen=True)
class GapEntry:
    doc_type: str
    title: str
    required: bool
    status: str
    documents: int


@dataclass(frozen=True)
class GapFolder:
    id: str
    dir: str
    stage: str
    entries: tuple[GapEntry, ...]


@dataclass(frozen=True)
class GapReport:
    project_slug: str
    project_name: str
    generated_at: datetime
    folders: tuple[GapFolder, ...]

    @property
    def required_total(self) -> int:
        return sum(1 for f in self.folders for e in f.entries if e.required)

    @property
    def required_present(self) -> int:
        return sum(1 for f in self.folders for e in f.entries if e.required and e.status == PRESENT)

    @property
    def completeness(self) -> float:
        return 1.0 if self.required_total == 0 else self.required_present / self.required_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "qc_agent": 2,
            "project": {"slug": self.project_slug, "name": self.project_name},
            "generated_at": self.generated_at.isoformat(),
            "required_total": self.required_total,
            "required_present": self.required_present,
            "completeness": round(self.completeness, 4),
            "folders": [
                {
                    "id": f.id,
                    "dir": f.dir,
                    "stage": f.stage,
                    "doc_types": [
                        {
                            "doc_type": e.doc_type,
                            "title": e.title,
                            "required": e.required,
                            "status": e.status,
                            "documents": e.documents,
                        }
                        for e in f.entries
                    ],
                }
                for f in self.folders
            ],
        }


def build_gap_report(
    taxonomy: Taxonomy,
    facts: Iterable[DocumentFact],
    *,
    project_slug: str,
    project_name: str,
    generated_at: datetime,
) -> GapReport:
    real: dict[str, int] = {}
    stubs: set[str] = set()
    for fact in facts:
        if fact.is_stub:
            stubs.add(fact.doc_type)
        else:
            real[fact.doc_type] = real.get(fact.doc_type, 0) + 1
    folders: list[GapFolder] = []
    for folder in taxonomy.folders:
        entries: list[GapEntry] = []
        for doc_type in folder.doc_types:
            if doc_type.is_other:
                continue
            count = real.get(doc_type.key, 0)
            if count:
                status = PRESENT
            elif doc_type.key in stubs:
                status = STUB
            else:
                status = MISSING
            entries.append(
                GapEntry(
                    doc_type=doc_type.key,
                    title=doc_type.title,
                    required=doc_type.required,
                    status=status,
                    documents=count,
                )
            )
        folders.append(
            GapFolder(id=folder.id, dir=folder.dir, stage=folder.stage, entries=tuple(entries))
        )
    return GapReport(
        project_slug=project_slug,
        project_name=project_name,
        generated_at=generated_at,
        folders=tuple(folders),
    )


def render_gap_report_markdown(report: GapReport) -> str:
    lines = [
        f"# Gap report: {report.project_name}",
        "",
        f"Generated {report.generated_at.isoformat()} by QC-Agent.",
        "",
        f"Required document types present: {report.required_present} of "
        f"{report.required_total} ({report.completeness:.0%}).",
        "",
    ]
    for folder in report.folders:
        lines += [
            f"## {folder.dir} ({folder.stage})",
            "",
            "| Document type | Required | Status | Documents |",
            "| --- | --- | --- | --- |",
        ]
        for entry in folder.entries:
            required = "yes" if entry.required else "no"
            lines.append(f"| {entry.title} | {required} | {entry.status} | {entry.documents} |")
        lines.append("")
    return "\n".join(lines)
```

`backend/app/ingestion/versioning.py`:

```python
"""Version suggestions: an existing document of the same type with a similar title (spec 5.4)."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.ingestion.naming import title_slug

SIMILARITY_THRESHOLD = 0.8


@dataclass(frozen=True)
class VersionCandidate:
    document_id: uuid.UUID
    title: str
    slug: str
    current_version: int


@dataclass(frozen=True)
class VersionSuggestion:
    document_id: uuid.UUID
    title: str
    current_version: int
    similarity: float


def suggest_versions(title: str, candidates: Iterable[VersionCandidate]) -> list[VersionSuggestion]:
    wanted = title_slug(title)
    suggestions = []
    for candidate in candidates:
        ratio = SequenceMatcher(None, wanted, candidate.slug).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            suggestions.append(
                VersionSuggestion(
                    document_id=candidate.document_id,
                    title=candidate.title,
                    current_version=candidate.current_version,
                    similarity=round(ratio, 3),
                )
            )
    suggestions.sort(key=lambda s: (-s.similarity, s.title))
    return suggestions
```

Note on Markdown uploads: when the uploaded file is itself `.md`, `original_path` and `markdown_path` coincide by the spec's naming. Publishing (Task 11) writes the original bytes first and the frontmatter version second, so the original is storage version *n* and the converted file is *n+1*; `document_versions.original_storage_version` points at the original bytes and `GET …/original` serves them from version history.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_naming.py tests/ingestion/test_versioning.py tests/ingestion/test_gaps.py -v`
Expected: `10 passed`.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app/ingestion backend/tests/ingestion
git commit -m "feat(backend): add naming, frontmatter, stubs, gap report and version suggestions"
```

---

### Task 5: Ingestion data model and migration 0002

**Files:**
- Create: `backend/app/db/models/ingestion.py`, `backend/migrations/versions/0002_ingestion.py`
- Modify: `backend/app/db/models/projects.py` (two columns), `backend/app/db/models/__init__.py` (replace)
- Test: `backend/tests/db/test_models.py` (append), `backend/tests/db/test_migrations.py` (unchanged; must still pass)

**Interfaces:**
- Consumes: `Base`, `Project`, `User` (Plan 1).
- Produces: ORM models importable from `app.db.models`: `Upload(id, project_id, uploaded_by, repo_ref, created_at)`, `UploadItem(id, upload_id, original_name, ext, size, sha256, staging_path, selected_doc_type, final_doc_type, title, intent, target_document_id, visibility, status, type_check, check_explanation, suggested_doc_type, version_hint_document_id, conversion_meta, error, created_at, updated_at)`, `Document(id, project_id, folder_id, doc_type, title, slug, visibility, current_version, is_stub, created_by, created_at, updated_at)`, `DocumentVersion(id, document_id, version, sha256, original_path, original_storage_version, markdown_path, markdown_storage_version, markdown_text, uploaded_by, upload_item_id, created_at)`; constants `ITEM_STATUSES`, `TERMINAL_STATUSES`, `INTENTS`, `VISIBILITIES`, `TYPE_CHECKS`; `Project.storage: dict`, `Project.llm_consent: dict | None`. Rules encoded in the schema: `documents.slug` is `""` for stubs and non-empty otherwise (`ck_documents_stub_slug`); `(project_id, doc_type, slug)` unique; `(document_id, version)` unique; `upload_item_id` unique; status/intent/visibility/type_check check constraints.

- [ ] **Step 1: Write the failing tests**

Change the import at the top of `backend/tests/db/test_models.py` to

```python
from app.db.models import (
    AuditLog,
    Document,
    DocumentVersion,
    Project,
    ProjectMember,
    Upload,
    UploadItem,
    User,
)
```

and append:

```python
async def test_project_storage_and_consent_columns(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.flush()
    project = Project(
        slug="demo", name="Demo", created_by=user.id, storage={"type": "localfs", "root": "demo"}
    )
    db.add(project)
    await db.commit()
    assert project.storage == {"type": "localfs", "root": "demo"}
    assert project.llm_consent is None


async def _project(db: AsyncSession) -> tuple[User, Project]:
    user = _user()
    db.add(user)
    await db.flush()
    project = Project(slug="demo", name="Demo", created_by=user.id, storage={})
    db.add(project)
    await db.flush()
    return user, project


async def test_document_defaults_and_stub_slug_rule(db: AsyncSession) -> None:
    user, project = await _project(db)
    document = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        created_by=user.id,
    )
    db.add(document)
    await db.commit()
    assert document.visibility == "internal" and document.current_version == 0
    assert document.is_stub is False and document.updated_at is not None
    db.add(
        Document(
            project_id=project.id,
            folder_id="requirements",
            doc_type="brd",
            title="BRD",
            slug="brd",
            is_stub=True,
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_document_slug_is_unique_per_project_and_type(db: AsyncSession) -> None:
    user, project = await _project(db)
    for doc_type in ("srs", "brd"):
        db.add(
            Document(
                project_id=project.id,
                folder_id="requirements",
                doc_type=doc_type,
                title="Portal",
                slug="portal",
                created_by=user.id,
            )
        )
    await db.commit()  # same slug, different types: allowed
    db.add(
        Document(
            project_id=project.id,
            folder_id="requirements",
            doc_type="srs",
            title="Portal",
            slug="portal",
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_upload_item_status_is_constrained(db: AsyncSession) -> None:
    user, project = await _project(db)
    upload = Upload(project_id=project.id, uploaded_by=user.id)
    db.add(upload)
    await db.flush()
    db.add(
        UploadItem(
            upload_id=upload.id,
            original_name="a.docx",
            ext="docx",
            size=1,
            sha256="0" * 64,
            staging_path="x/a.docx",
            selected_doc_type="srs",
            title="A",
            status="teleporting",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_document_version_unique_per_document(db: AsyncSession) -> None:
    user, project = await _project(db)
    document = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        created_by=user.id,
    )
    db.add(document)
    await db.flush()
    for _ in range(2):
        db.add(
            DocumentVersion(
                document_id=document.id,
                version=1,
                sha256="0" * 64,
                markdown_path="02-requirements/srs--srs.md",
                markdown_storage_version="1",
                markdown_text="# SRS",
                uploaded_by=user.id,
            )
        )
    with pytest.raises(IntegrityError):
        await db.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'Document' from 'app.db.models'`.

- [ ] **Step 3: Implement the models**

In `backend/app/db/models/projects.py`, add two columns to `Project` directly after `settings`:

```python
    storage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    llm_consent: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
```

`backend/app/db/models/ingestion.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ITEM_STATUSES = (
    "uploaded",
    "converting",
    "checking",
    "needs_confirmation",
    "publishing",
    "published",
    "failed",
)
TERMINAL_STATUSES = ("published", "failed")
INTENTS = ("new", "version")
VISIBILITIES = ("internal", "shared")
TYPE_CHECKS = ("match", "mismatch_kept", "mismatch_changed", "skipped")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    repo_ref: Mapped[str | None] = mapped_column(String(500))  # repository reference, later plan
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("project_id", "doc_type", "slug", name="uq_documents_project_type_slug"),
        CheckConstraint(f"visibility IN ({_in_list(VISIBILITIES)})", name="visibility"),
        CheckConstraint(
            "(is_stub AND slug = '') OR (NOT is_stub AND slug <> '')", name="stub_slug"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[str] = mapped_column(String(40))
    doc_type: Mapped[str] = mapped_column(String(80))  # taxonomy key, e.g. "srs" or "design/other"
    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))  # title slug; "" for stubs
    visibility: Mapped[str] = mapped_column(String(8), default="internal")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    is_stub: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UploadItem(Base):
    __tablename__ = "upload_items"
    __table_args__ = (
        CheckConstraint(f"status IN ({_in_list(ITEM_STATUSES)})", name="status"),
        CheckConstraint(f"intent IN ({_in_list(INTENTS)})", name="intent"),
        CheckConstraint(f"visibility IN ({_in_list(VISIBILITIES)})", name="visibility"),
        CheckConstraint(
            f"type_check IS NULL OR type_check IN ({_in_list(TYPE_CHECKS)})", name="type_check"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    ext: Mapped[str] = mapped_column(String(8))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    staging_path: Mapped[str] = mapped_column(String(500))  # relative to STAGING_ROOT
    selected_doc_type: Mapped[str] = mapped_column(String(80))
    final_doc_type: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    intent: Mapped[str] = mapped_column(String(8), default="new")
    target_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    visibility: Mapped[str] = mapped_column(String(8), default="internal")
    status: Mapped[str] = mapped_column(String(24), default="uploaded", index=True)
    type_check: Mapped[str | None] = mapped_column(String(24))
    check_explanation: Mapped[str | None] = mapped_column(Text)
    suggested_doc_type: Mapped[str | None] = mapped_column(String(80))
    version_hint_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    conversion_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_document_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    original_path: Mapped[str | None] = mapped_column(String(500))  # None for stubs
    original_storage_version: Mapped[str | None] = mapped_column(String(100))
    markdown_path: Mapped[str] = mapped_column(String(500))
    markdown_storage_version: Mapped[str] = mapped_column(String(100))
    markdown_text: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    upload_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("upload_items.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`backend/app/db/models/__init__.py`:

```python
from app.db.models.audit import AuditLog
from app.db.models.identity import ACCOUNT_TYPES, AuthSession, User
from app.db.models.ingestion import (
    INTENTS,
    ITEM_STATUSES,
    TERMINAL_STATUSES,
    TYPE_CHECKS,
    VISIBILITIES,
    Document,
    DocumentVersion,
    Upload,
    UploadItem,
)
from app.db.models.projects import PROJECT_ROLES, Project, ProjectMember

__all__ = [
    "ACCOUNT_TYPES",
    "INTENTS",
    "ITEM_STATUSES",
    "PROJECT_ROLES",
    "TERMINAL_STATUSES",
    "TYPE_CHECKS",
    "VISIBILITIES",
    "AuditLog",
    "AuthSession",
    "Document",
    "DocumentVersion",
    "Project",
    "ProjectMember",
    "Upload",
    "UploadItem",
    "User",
]
```

- [ ] **Step 4: Run the model tests**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: `10 passed` (the session-scoped `_schema` fixture builds tables from the metadata, so these pass before the migration exists).

- [ ] **Step 5: Write the migration**

Generate against the dev database (`.env` points at `qc_agent`, which is at revision 0001):

```bash
uv run alembic revision --autogenerate --rev-id 0002 -m "ingestion"
```

Then replace the generated `backend/migrations/versions/0002_ingestion.py` with the content below. It equals the autogenerate output plus the `projects.storage` backfill (add nullable → backfill from the slug → set NOT NULL), which autogenerate cannot write. If your autogenerate output orders constraints differently, keep the file below; the migration test is the arbiter.

`backend/migrations/versions/0002_ingestion.py`:

```python
"""ingestion: project storage binding, consent, uploads, documents

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "projects", sa.Column("storage", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "projects",
        sa.Column("llm_consent", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Existing projects are bound to local storage under their slug; their workspace is
    # provisioned lazily on the first publish (ensure_workspace is idempotent).
    op.execute("UPDATE projects SET storage = jsonb_build_object('type', 'localfs', 'root', slug)")
    op.alter_column("projects", "storage", nullable=False)

    op.create_table(
        "uploads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("repo_ref", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_uploads_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_uploads_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )
    op.create_index(op.f("ix_uploads_project_id"), "uploads", ["project_id"], unique=False)
    op.create_index(op.f("ix_uploads_uploaded_by"), "uploads", ["uploaded_by"], unique=False)

    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.String(length=40), nullable=False),
        sa.Column("doc_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("visibility", sa.String(length=8), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("is_stub", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(is_stub AND slug = '') OR (NOT is_stub AND slug <> '')",
            name=op.f("ck_documents_stub_slug"),
        ),
        sa.CheckConstraint(
            "visibility IN ('internal', 'shared')", name=op.f("ck_documents_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_documents_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_documents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint(
            "project_id", "doc_type", "slug", name=op.f("uq_documents_project_type_slug")
        ),
    )
    op.create_index(op.f("ix_documents_project_id"), "documents", ["project_id"], unique=False)

    op.create_table(
        "upload_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("upload_id", sa.UUID(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("ext", sa.String(length=8), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("staging_path", sa.String(length=500), nullable=False),
        sa.Column("selected_doc_type", sa.String(length=80), nullable=False),
        sa.Column("final_doc_type", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("intent", sa.String(length=8), nullable=False),
        sa.Column("target_document_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("type_check", sa.String(length=24), nullable=True),
        sa.Column("check_explanation", sa.Text(), nullable=True),
        sa.Column("suggested_doc_type", sa.String(length=80), nullable=True),
        sa.Column("version_hint_document_id", sa.UUID(), nullable=True),
        sa.Column("conversion_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("intent IN ('new', 'version')", name=op.f("ck_upload_items_intent")),
        sa.CheckConstraint(
            "status IN ('uploaded', 'converting', 'checking', 'needs_confirmation', "
            "'publishing', 'published', 'failed')",
            name=op.f("ck_upload_items_status"),
        ),
        sa.CheckConstraint(
            "type_check IS NULL OR type_check IN ('match', 'mismatch_kept', "
            "'mismatch_changed', 'skipped')",
            name=op.f("ck_upload_items_type_check"),
        ),
        sa.CheckConstraint(
            "visibility IN ('internal', 'shared')", name=op.f("ck_upload_items_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["target_document_id"],
            ["documents.id"],
            name=op.f("fk_upload_items_target_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["uploads.id"],
            name=op.f("fk_upload_items_upload_id_uploads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_hint_document_id"],
            ["documents.id"],
            name=op.f("fk_upload_items_version_hint_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_items")),
    )
    op.create_index(op.f("ix_upload_items_status"), "upload_items", ["status"], unique=False)
    op.create_index(op.f("ix_upload_items_upload_id"), "upload_items", ["upload_id"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_path", sa.String(length=500), nullable=True),
        sa.Column("original_storage_version", sa.String(length=100), nullable=True),
        sa.Column("markdown_path", sa.String(length=500), nullable=False),
        sa.Column("markdown_storage_version", sa.String(length=100), nullable=False),
        sa.Column("markdown_text", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("upload_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upload_item_id"],
            ["upload_items.id"],
            name=op.f("fk_document_versions_upload_item_id_upload_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_document_versions_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "document_id", "version", name=op.f("uq_document_versions_document_version")
        ),
        sa.UniqueConstraint("upload_item_id", name=op.f("uq_document_versions_upload_item_id")),
    )
    op.create_index(
        op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index(op.f("ix_upload_items_upload_id"), table_name="upload_items")
    op.drop_index(op.f("ix_upload_items_status"), table_name="upload_items")
    op.drop_table("upload_items")
    op.drop_index(op.f("ix_documents_project_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_uploads_uploaded_by"), table_name="uploads")
    op.drop_index(op.f("ix_uploads_project_id"), table_name="uploads")
    op.drop_table("uploads")
    op.drop_column("projects", "llm_consent")
    op.drop_column("projects", "storage")
```

- [ ] **Step 6: Verify the migration against the models**

```bash
uv run alembic upgrade head
uv run alembic check
uv run pytest tests/db -v
```

Expected: upgrade succeeds; `No new upgrade operations detected.`; `tests/db/test_migrations.py::test_migrations_match_models` passes (it applies 0001 and 0002 to an empty throwaway database and diffs against the ORM metadata).

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app/db backend/migrations backend/tests/db
git commit -m "feat(backend): add ingestion data model and migration 0002"
```

---

### Task 6: Project storage binding, workspace provisioning and LLM consent

**Files:**
- Create: `backend/app/services/workspace.py`, `backend/app/services/consent.py`
- Modify: `backend/app/services/projects.py` (replace), `backend/app/schemas/projects.py` (replace), `backend/app/api/routes/projects.py` (replace), `backend/tests/conftest.py` (replace), `backend/tests/factories.py` (replace)
- Test: `backend/tests/api/test_consent.py`

**Interfaces:**
- Consumes: `Taxonomy`, `TaxonomyDep` (Task 2); `StorageBackend`, `backend_for`, `localfs_binding` (Task 3); naming/stubs/gaps (Task 4); models (Task 5); `ProjectOwner`, `audit.record` (Plan 1).
- Produces:
  - `app.services.workspace`: `ensure_workspace(db, *, project, backend, taxonomy, actor, now=None)` (idempotent: folders, stubs for required types without any document, repair of missing stub files, reports, sets `project.storage["provisioned_at"]`), `create_stub(...) -> Document`, `refresh_reports(db, *, project, backend, taxonomy, now) -> GapReport`, `document_facts(db, project_id)`, `render_project_yaml(project, taxonomy, report)`, `stub_frontmatter(...)`, `sha256_hex(data)`, `is_provisioned(project)`; constants `PROJECT_YAML`, `REPORTS_DIR`, `GAP_REPORT_MD`, `GAP_REPORT_JSON`, `PROVISIONED_AT`.
  - `app.services.consent`: `has_consent(project) -> bool`, `record_consent(db, project, *, actor, confirmed_by_name, now=None) -> dict` (commits; audit `project.llm_consent`), `ConsentError(message)`.
  - `app.services.projects.create_project(db, *, name, client_name, creator, settings, taxonomy) -> Project` now binds `storage=localfs_binding(slug)` and provisions the workspace before committing; a `StorageError` propagates and nothing is committed (route → 503).
  - Schemas: `ProjectStorageOut(type, root)`, `LlmConsentOut(confirmed_by_name, confirmed_at)`, `LlmConsentRequest(confirmed_by_name)`; `ProjectOut` gains `storage` (internal roles only) and `llm_consent` (all roles).
  - Route `POST /projects/{project_id}/llm-consent` (owner, 201, 409 when already confirmed).
  - Test fixtures: `taxonomy`, `storage_root`, `staging_root`; `db_sessionmaker` also wipes the temporary storage and staging roots per test; factories `make_project(db, settings, taxonomy, *, owner, name="Demo Project", client_name="ACME", consent=True) -> Project`, `add_member(db, project, user, role)`.

- [ ] **Step 1: Test fixtures**

Replace `backend/tests/conftest.py` (temporary storage/staging roots for the whole session, wiped per test; `taxonomy`, `storage_root`, `staging_root` fixtures):

```python
import asyncio
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://qc:qc@localhost:5434/qc_agent_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-production")
os.environ.setdefault("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["COOKIE_SECURE"] = "false"
os.environ["EXPOSE_DOCS"] = "false"  # a developer .env may enable docs; tests expect them hidden
_DATA_ROOT = Path(tempfile.mkdtemp(prefix="qc-agent-tests-"))
os.environ["LOCAL_STORAGE_ROOT"] = str(_DATA_ROOT / "workspace")
os.environ["STAGING_ROOT"] = str(_DATA_ROOT / "staging")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db import models  # noqa: E402,F401  - registers tables on Base.metadata
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, init_engine  # noqa: E402
from app.ingestion.taxonomy import Taxonomy, load_taxonomy  # noqa: E402
from app.main import create_app  # noqa: E402

BASE_URL = "http://testserver"
CSRF = {"X-QC-Agent": "1"}


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    if os.environ.get("QC_SKIP_DB"):
        return

    async def build() -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(build())


@pytest.fixture
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@pytest.fixture
def taxonomy() -> Taxonomy:
    return load_taxonomy()


@pytest.fixture
def storage_root(settings: Settings) -> Path:
    return Path(settings.local_storage_root)


@pytest.fixture
def staging_root(settings: Settings) -> Path:
    return Path(settings.staging_root)


@pytest.fixture
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    maker = init_engine(os.environ["DATABASE_URL"], null_pool=True)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with maker() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
    for root in (os.environ["LOCAL_STORAGE_ROOT"], os.environ["STAGING_ROOT"]):
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=True)
    yield maker
    await dispose_engine()


@pytest.fixture
async def db(db_sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with db_sessionmaker() as session:
        yield session


@pytest.fixture
def make_app(db_sessionmaker: async_sessionmaker[AsyncSession]) -> Callable[..., FastAPI]:
    def _make(**overrides: Any) -> FastAPI:
        return create_app(Settings(**overrides))  # type: ignore[call-arg]

    return _make


@pytest.fixture
def app(make_app: Callable[..., FastAPI]) -> FastAPI:
    return make_app()


@pytest.fixture
async def make_client(
    app: FastAPI,
) -> AsyncIterator[Callable[..., Awaitable[AsyncClient]]]:
    clients: list[AsyncClient] = []

    async def _make(token: str | None = None, app_: FastAPI | None = None) -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app_ or app), base_url=BASE_URL, headers=CSRF
        )
        if token is not None:
            client.cookies.set("qc_session", token)
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


@pytest.fixture
async def client(make_client: Callable[..., Awaitable[AsyncClient]]) -> AsyncClient:
    return await make_client()
```

Replace `backend/tests/factories.py`:

`backend/tests/factories.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.passwords import hash_password
from app.core.tokens import hash_token, new_session_token
from app.db.models import AuthSession, Project, ProjectMember, User
from app.ingestion.taxonomy import Taxonomy
from app.services.consent import record_consent
from app.services.projects import create_project

DEFAULT_PASSWORD = "correct-horse-battery-staple"


async def make_user(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str = "alice@example.com",
    password: str = DEFAULT_PASSWORD,
    display_name: str = "Alice",
    account_type: str = "internal",
    is_admin: bool = False,
    is_active: bool = True,
    must_change_password: bool = False,
    mfa_secret: str | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        account_type=account_type,
        is_admin=is_admin,
        is_active=is_active,
        must_change_password=must_change_password,
    )
    if mfa_secret is not None:
        user.mfa_secret_enc = SecretBox(settings.secret_encryption_key).encrypt(mfa_secret)
        user.mfa_enabled = True
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_session_token(
    db: AsyncSession,
    settings: Settings,
    user: User,
    *,
    mfa_verified: bool = True,
    expires_in: timedelta = timedelta(hours=8),
) -> str:
    token = new_session_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token, settings.session_secret),
            mfa_verified=mfa_verified,
            expires_at=datetime.now(UTC) + expires_in,
        )
    )
    await db.commit()
    return token


async def reload[T](db: AsyncSession, model: type[T], obj_id: uuid.UUID | Any) -> T | None:
    db.expire_all()
    return await db.get(model, obj_id)


async def make_project(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    *,
    owner: User,
    name: str = "Demo Project",
    client_name: str | None = "ACME",
    consent: bool = True,
) -> Project:
    """A project with its workspace provisioned (folders, stubs, reports) and, by default, the
    LLM data-processing confirmation recorded so uploads are allowed."""
    project = await create_project(
        db, name=name, client_name=client_name, creator=owner, settings=settings, taxonomy=taxonomy
    )
    if consent:
        await record_consent(db, project, actor=owner, confirmed_by_name="Customer Rep")
    await db.refresh(project)
    return project


async def add_member(db: AsyncSession, project: Project, user: User, role: str) -> None:
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
    await db.commit()
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/api/test_consent.py`:

```python
"""Project creation provisions the workspace; the owner records the LLM data-processing
confirmation; uploads stay blocked until then (checked in test_uploads)."""

import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, Document, DocumentVersion, Project
from app.ingestion.naming import split_frontmatter
from app.ingestion.taxonomy import Taxonomy
from app.services.workspace import ensure_workspace
from app.storage.select import backend_for
from tests.factories import add_member, make_project, make_session_token, make_user

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def test_project_creation_provisions_workspace(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    owner = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, owner))
    response = await c.post("/api/v1/projects", json={"name": "Dự án Cổng Khách hàng"})
    assert response.status_code == 201
    body = response.json()
    assert body["storage"] == {"type": "localfs", "root": "du-an-cong-khach-hang"}
    assert body["llm_consent"] is None
    root = storage_root / "du-an-cong-khach-hang"
    for folder in (
        "01-overview",
        "02-requirements",
        "03-design",
        "04-source",
        "05-testing",
        "06-deployment",
        "_reports",
    ):
        assert (root / folder).is_dir(), folder
    assert (root / "04-source/adr").is_dir() and (root / "05-testing/test-reports").is_dir()
    project_yaml = yaml.safe_load((root / "project.yaml").read_text())
    assert project_yaml["project"]["slug"] == "du-an-cong-khach-hang"
    assert project_yaml["required_present"] == 0 and project_yaml["required_total"] == 10
    report = json.loads((root / "_reports/gap-report.json").read_text())
    statuses = {t["doc_type"]: t["status"] for f in report["folders"] for t in f["doc_types"]}
    assert statuses["srs"] == "stub" and statuses["glossary"] == "missing"
    assert (root / "_reports/gap-report.md").read_text().startswith("# Gap report:")
    stubs = (await db.scalars(select(Document).where(Document.is_stub.is_(True)))).all()
    assert len(stubs) == 10 and all(s.slug == "" and s.visibility == "internal" for s in stubs)
    srs_stub = (root / "02-requirements/srs.md").read_text()
    data, stub_body = split_frontmatter(srs_stub)
    assert data["kind"] == "stub" and data["uploaded_by"] == "Alice" and "@" not in srs_stub
    assert stub_body.startswith("> Placeholder:")
    project = (await db.scalars(select(Project))).one()
    assert "provisioned_at" in project.storage


async def test_ensure_workspace_is_idempotent_and_repairs_missing_stub(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    stub_file = storage_root / "demo/02-requirements/srs.md"
    stub_file.unlink()
    backend = backend_for(project.storage, settings)
    await ensure_workspace(db, project=project, backend=backend, taxonomy=taxonomy, actor=owner)
    await db.commit()
    assert stub_file.exists()
    assert len((await db.scalars(select(Document).where(Document.is_stub.is_(True)))).all()) == 10
    versions = (await db.scalars(select(DocumentVersion))).all()
    assert len(versions) == 10


async def test_owner_records_consent_once(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    editor = await make_user(db, settings, email="editor@example.com", display_name="Ed")
    project = await make_project(db, settings, taxonomy, owner=owner, consent=False)
    await add_member(db, project, editor, "editor")
    owner_c = await make_client(await make_session_token(db, settings, owner))
    editor_c = await make_client(await make_session_token(db, settings, editor))
    url = f"/api/v1/projects/{project.id}/llm-consent"
    assert (await editor_c.post(url, json={"confirmed_by_name": "X"})).status_code == 403
    assert (await owner_c.post(url, json={"confirmed_by_name": "   "})).status_code == 422
    response = await owner_c.post(url, json={"confirmed_by_name": "  Tran Thi B  "})
    assert response.status_code == 201
    assert response.json()["confirmed_by_name"] == "Tran Thi B"
    again = await owner_c.post(url, json={"confirmed_by_name": "Tran Thi B"})
    assert again.status_code == 409
    shown = (await owner_c.get(f"/api/v1/projects/{project.id}")).json()
    assert shown["llm_consent"]["confirmed_by_name"] == "Tran Thi B"
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "project.llm_consent" in actions
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_consent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.consent'` (raised while importing `tests/factories.py`).

- [ ] **Step 4: Implement workspace and consent services**

`backend/app/services/workspace.py`:

```python
"""Project workspace in storage: the six folders, ``project.yaml``, stubs for required types and
the gap report (spec 5.1, 5.5). ``ensure_workspace`` is idempotent: it runs at project creation
and again from the first publish of a project that predates provisioning."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentVersion, Project, User
from app.ingestion.gaps import (
    DocumentFact,
    GapReport,
    build_gap_report,
    render_gap_report_markdown,
)
from app.ingestion.naming import Frontmatter, stub_path
from app.ingestion.stubs import render_stub
from app.ingestion.taxonomy import DocType, Taxonomy
from app.storage.base import StorageBackend

PROJECT_YAML = "project.yaml"
REPORTS_DIR = "_reports"
GAP_REPORT_MD = f"{REPORTS_DIR}/gap-report.md"
GAP_REPORT_JSON = f"{REPORTS_DIR}/gap-report.json"
PROVISIONED_AT = "provisioned_at"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def document_facts(db: AsyncSession, project_id: uuid.UUID) -> list[DocumentFact]:
    rows = (
        await db.execute(
            select(Document.doc_type, Document.is_stub).where(Document.project_id == project_id)
        )
    ).all()
    return [DocumentFact(doc_type=doc_type, is_stub=is_stub) for doc_type, is_stub in rows]


def render_project_yaml(project: Project, taxonomy: Taxonomy, report: GapReport) -> str:
    data: dict[str, Any] = {
        "qc_agent": 2,
        "project": {
            "id": str(project.id),
            "slug": project.slug,
            "name": project.name,
            "client_name": project.client_name,
        },
        "taxonomy_version": taxonomy.version,
        "folders": [folder.dir for folder in taxonomy.folders],
        "documents": sum(e.documents for f in report.folders for e in f.entries),
        "required_present": report.required_present,
        "required_total": report.required_total,
        "updated_at": report.generated_at.isoformat(),
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


async def refresh_reports(
    db: AsyncSession,
    *,
    project: Project,
    backend: StorageBackend,
    taxonomy: Taxonomy,
    now: datetime,
) -> GapReport:
    report = build_gap_report(
        taxonomy,
        await document_facts(db, project.id),
        project_slug=project.slug,
        project_name=project.name,
        generated_at=now,
    )
    await backend.put_file(
        GAP_REPORT_MD, render_gap_report_markdown(report).encode("utf-8"), "text/markdown"
    )
    await backend.put_file(
        GAP_REPORT_JSON,
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False).encode("utf-8"),
        "application/json",
    )
    await backend.put_file(
        PROJECT_YAML, render_project_yaml(project, taxonomy, report).encode("utf-8"), "text/yaml"
    )
    return report


def stub_frontmatter(
    document: Document, doc_type: DocType, actor: User, now: datetime
) -> Frontmatter:
    return Frontmatter(
        document_id=str(document.id),
        version=1,
        doc_type=doc_type.id,
        folder=doc_type.folder_dir,
        title=doc_type.title,
        kind="stub",
        source_file=None,
        source_sha256=None,
        uploaded_by=actor.display_name,
        uploaded_at=now,
        type_selected_by_user=doc_type.key,
        type_check="skipped",
        language="en",
        visibility="internal",
    )


async def create_stub(
    db: AsyncSession,
    *,
    project: Project,
    doc_type: DocType,
    taxonomy: Taxonomy,
    backend: StorageBackend,
    actor: User,
    now: datetime,
) -> Document:
    document = Document(
        project_id=project.id,
        folder_id=doc_type.folder_id,
        doc_type=doc_type.key,
        title=doc_type.title,
        slug="",
        visibility="internal",
        current_version=1,
        is_stub=True,
        created_by=actor.id,
    )
    db.add(document)
    await db.flush()
    text = render_stub(
        doc_type, taxonomy.template_text(doc_type), stub_frontmatter(document, doc_type, actor, now)
    )
    data = text.encode("utf-8")
    stored = await backend.put_file(stub_path(doc_type), data, "text/markdown")
    db.add(
        DocumentVersion(
            document_id=document.id,
            version=1,
            sha256=sha256_hex(data),
            original_path=None,
            original_storage_version=None,
            markdown_path=stub_path(doc_type),
            markdown_storage_version=stored.version_id,
            markdown_text=text,
            uploaded_by=actor.id,
            upload_item_id=None,
        )
    )
    return document


async def ensure_workspace(
    db: AsyncSession,
    *,
    project: Project,
    backend: StorageBackend,
    taxonomy: Taxonomy,
    actor: User,
    now: datetime | None = None,
) -> None:
    """Create folders, stubs for required types without any document, repair stub files that
    disappeared from storage, then write the reports. Safe to call repeatedly."""
    moment = now or datetime.now(UTC)
    for folder in taxonomy.folders:
        await backend.ensure_folder(folder.dir)
        for doc_type in folder.doc_types:
            if doc_type.multi:
                await backend.ensure_folder(doc_type.document_dir)
    await backend.ensure_folder(REPORTS_DIR)
    typed = set(
        (await db.scalars(select(Document.doc_type).where(Document.project_id == project.id))).all()
    )
    for doc_type in taxonomy.required_types():
        if doc_type.key not in typed:
            await create_stub(
                db,
                project=project,
                doc_type=doc_type,
                taxonomy=taxonomy,
                backend=backend,
                actor=actor,
                now=moment,
            )
    stubs = (
        await db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(Document.project_id == project.id, Document.is_stub.is_(True))
        )
    ).all()
    for _document, version in stubs:
        if not await backend.exists(version.markdown_path):
            stored = await backend.put_file(
                version.markdown_path, version.markdown_text.encode("utf-8"), "text/markdown"
            )
            version.markdown_storage_version = stored.version_id
    await refresh_reports(db, project=project, backend=backend, taxonomy=taxonomy, now=moment)
    project.storage = {**project.storage, PROVISIONED_AT: moment.isoformat()}


def is_provisioned(project: Project) -> bool:
    return PROVISIONED_AT in project.storage
```

`backend/app/services/consent.py`:

```python
"""Per-project confirmation that converted document text may be sent to the Claude API
(spec 13 "Data processing"). Required before the first upload."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, User
from app.services import audit


class ConsentError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def has_consent(project: Project) -> bool:
    return bool(project.llm_consent)


async def record_consent(
    db: AsyncSession,
    project: Project,
    *,
    actor: User,
    confirmed_by_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if has_consent(project):
        raise ConsentError("LLM data processing is already confirmed for this project.")
    moment = now or datetime.now(UTC)
    consent = {
        "confirmed_by_name": confirmed_by_name.strip(),
        "confirmed_at": moment.isoformat(),
        "confirmed_by_user_id": str(actor.id),
    }
    project.llm_consent = consent
    await audit.record(
        db,
        "project.llm_consent",
        user_id=actor.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"confirmed_by_name": consent["confirmed_by_name"]},
    )
    await db.commit()
    return consent
```

- [ ] **Step 5: Bind storage at project creation; schemas and routes**

Replace `backend/app/services/projects.py`:

`backend/app/services/projects.py`:

```python
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.slugs import slugify, unique_slug
from app.db.models import Project, ProjectMember, User
from app.ingestion.taxonomy import Taxonomy
from app.schemas.projects import MemberIn, MemberOut, ProjectSettings
from app.services import audit
from app.services.workspace import ensure_workspace
from app.storage.select import backend_for, localfs_binding


class MemberValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def create_project(
    db: AsyncSession,
    *,
    name: str,
    client_name: str | None,
    creator: User,
    settings: Settings,
    taxonomy: Taxonomy,
) -> Project:
    """Create the project, bind it to local storage under its slug and provision the workspace
    (folders, stubs, reports) before committing. A storage failure raises ``StorageError`` and
    nothing is committed."""
    base = slugify(name)
    taken = set((await db.scalars(select(Project.slug).where(Project.slug.startswith(base)))).all())
    slug = unique_slug(base, taken)
    project = Project(
        slug=slug,
        name=name,
        client_name=client_name,
        settings=ProjectSettings().model_dump(),
        storage=localfs_binding(slug),
        created_by=creator.id,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=creator.id, role="owner"))
    backend = backend_for(project.storage, settings)
    await ensure_workspace(db, project=project, backend=backend, taxonomy=taxonomy, actor=creator)
    await audit.record(
        db,
        "project.create",
        user_id=creator.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
    )
    await db.commit()
    return project


async def list_projects_for(db: AsyncSession, user: User) -> list[tuple[Project, str]]:
    if user.is_admin:
        projects = (
            await db.scalars(
                select(Project).where(Project.archived_at.is_(None)).order_by(Project.name)
            )
        ).all()
        return [(p, "owner") for p in projects]
    rows = (
        await db.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, Project.archived_at.is_(None))
            .order_by(Project.name)
        )
    ).all()
    return [(project, role) for project, role in rows]


async def replace_members(
    db: AsyncSession, project: Project, members: list[MemberIn], *, actor_id: uuid.UUID
) -> None:
    ids = [m.user_id for m in members]
    if len(set(ids)) != len(ids):
        raise MemberValidationError("Each user may appear only once.")
    if not any(m.role == "owner" for m in members):
        raise MemberValidationError("A project needs at least one owner.")
    users = {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()}
    for member in members:
        user = users.get(member.user_id)
        if user is None or not user.is_active:
            raise MemberValidationError(f"User {member.user_id} does not exist or is inactive.")
        if user.account_type == "customer" and member.role != "client":
            raise MemberValidationError("Customer accounts can only have the client role.")
        if user.account_type == "internal" and member.role == "client":
            raise MemberValidationError("Internal accounts cannot have the client role.")
    await db.execute(delete(ProjectMember).where(ProjectMember.project_id == project.id))
    db.add_all(
        ProjectMember(project_id=project.id, user_id=m.user_id, role=m.role) for m in members
    )
    await audit.record(
        db,
        "project.members_replaced",
        user_id=actor_id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"members": [{"user_id": str(m.user_id), "role": m.role} for m in members]},
    )
    await db.commit()


async def list_members(db: AsyncSession, project_id: uuid.UUID) -> list[MemberOut]:
    rows = (
        await db.execute(
            select(User, ProjectMember.role)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.display_name)
        )
    ).all()
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            account_type=u.account_type,
            role=role,
        )
        for u, role in rows
    ]
```

Replace `backend/app/schemas/projects.py`:

`backend/app/schemas/projects.py`:

```python
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(default="claude-opus-5", min_length=1, max_length=100)
    check_budget_usd: float = Field(default=1.0, gt=0, le=50)
    normalize_budget_usd: float = Field(default=2.0, gt=0, le=50)


class ProjectSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1, max_length=100)
    check_budget_usd: float | None = Field(default=None, gt=0, le=50)
    normalize_budget_usd: float | None = Field(default=None, gt=0, le=50)


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Project name is required.")
    return cleaned


class ProjectCreate(BaseModel):
    name: str = Field(max_length=200)
    client_name: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    settings: ProjectSettingsPatch | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class ProjectStorageOut(BaseModel):
    type: str
    root: str


class LlmConsentOut(BaseModel):
    confirmed_by_name: str
    confirmed_at: datetime


class LlmConsentRequest(BaseModel):
    confirmed_by_name: str = Field(min_length=1, max_length=200)

    @field_validator("confirmed_by_name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("The confirming person's name is required.")
        return cleaned


class ProjectOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    client_name: str | None
    created_at: datetime
    my_role: str
    settings: ProjectSettings | None
    storage: ProjectStorageOut | None
    llm_consent: LlmConsentOut | None


class MemberIn(BaseModel):
    user_id: uuid.UUID
    role: Literal["owner", "editor", "viewer", "client"]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    account_type: str
    role: str
```

Replace `backend/app/api/routes/projects.py`:

`backend/app/api/routes/projects.py`:

```python
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.api.deps import (
    INTERNAL_ROLES,
    AnyMember,
    AppSettings,
    CurrentUser,
    DbSession,
    InternalMember,
    ProjectOwner,
    TaxonomyDep,
)
from app.db.models import Project
from app.schemas.projects import (
    LlmConsentOut,
    LlmConsentRequest,
    MemberIn,
    MemberOut,
    ProjectCreate,
    ProjectOut,
    ProjectSettings,
    ProjectStorageOut,
    ProjectUpdate,
)
from app.services import audit
from app.services import consent as consent_service
from app.services import projects as projects_service
from app.storage.base import StorageError

router = APIRouter(prefix="/projects", tags=["projects"])


def _consent_out(project: Project) -> LlmConsentOut | None:
    if not project.llm_consent:
        return None
    return LlmConsentOut(
        confirmed_by_name=project.llm_consent["confirmed_by_name"],
        confirmed_at=project.llm_consent["confirmed_at"],
    )


def _out(project: Project, role: str) -> ProjectOut:
    internal = role in INTERNAL_ROLES
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        client_name=project.client_name,
        created_at=project.created_at,
        my_role=role,
        settings=ProjectSettings(**project.settings) if internal else None,
        storage=(
            ProjectStorageOut(type=project.storage["type"], root=project.storage["root"])
            if internal and project.storage
            else None
        ),
        llm_consent=_consent_out(project),
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DbSession) -> list[ProjectOut]:
    return [_out(p, role) for p, role in await projects_service.list_projects_for(db, user)]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    taxonomy: TaxonomyDep,
) -> ProjectOut:
    if user.account_type != "internal":
        raise HTTPException(status_code=403, detail="Only internal users can create projects.")
    try:
        project = await projects_service.create_project(
            db,
            name=body.name,
            client_name=body.client_name,
            creator=user,
            settings=settings,
            taxonomy=taxonomy,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail="Storage is unavailable; the project was not created."
        ) from exc
    await db.refresh(project)
    return _out(project, "owner")


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(ctx: AnyMember) -> ProjectOut:
    return _out(ctx.project, ctx.role)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(body: ProjectUpdate, ctx: ProjectOwner, db: DbSession) -> ProjectOut:
    project = ctx.project
    if body.name is not None:
        project.name = body.name
    if "client_name" in body.model_fields_set:
        project.client_name = body.client_name
    if body.settings is not None:
        merged = {**project.settings, **body.settings.model_dump(exclude_none=True)}
        project.settings = ProjectSettings(**merged).model_dump()
    await audit.record(
        db,
        "project.update",
        user_id=ctx.user.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"fields": sorted(body.model_fields_set)},
    )
    await db.commit()
    return _out(project, ctx.role)


@router.delete("/{project_id}", status_code=204)
async def archive_project(ctx: ProjectOwner, db: DbSession) -> None:
    ctx.project.archived_at = datetime.now(UTC)
    await audit.record(
        db,
        "project.archive",
        user_id=ctx.user.id,
        project_id=ctx.project.id,
        target_type="project",
        target_id=str(ctx.project.id),
    )
    await db.commit()


@router.get("/{project_id}/members", response_model=list[MemberOut])
async def get_members(ctx: InternalMember, db: DbSession) -> list[MemberOut]:
    return await projects_service.list_members(db, ctx.project.id)


@router.put("/{project_id}/members", response_model=list[MemberOut])
async def put_members(members: list[MemberIn], ctx: ProjectOwner, db: DbSession) -> list[MemberOut]:
    try:
        await projects_service.replace_members(db, ctx.project, members, actor_id=ctx.user.id)
    except projects_service.MemberValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return await projects_service.list_members(db, ctx.project.id)


@router.post("/{project_id}/llm-consent", response_model=LlmConsentOut, status_code=201)
async def record_llm_consent(
    body: LlmConsentRequest, ctx: ProjectOwner, db: DbSession
) -> LlmConsentOut:
    try:
        await consent_service.record_consent(
            db, ctx.project, actor=ctx.user, confirmed_by_name=body.confirmed_by_name
        )
    except consent_service.ConsentError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    consent = _consent_out(ctx.project)
    assert consent is not None  # noqa: S101 - just recorded
    return consent
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_consent.py tests/api/test_projects.py -v`
Expected: all passed (project tests from Plan 1 still pass; their projects now get a workspace under the temporary storage root).

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app backend/tests
git commit -m "feat(backend): bind projects to local storage, provision workspaces, record LLM consent"
```

---

### Task 7: Deterministic converters (markitdown, PyMuPDF, text, CSV) and runtime fixture generators

**Files:**
- Create: `backend/app/ingestion/converters/__init__.py`, `base.py`, `office.py`, `pdf.py`, `text.py`; `backend/tests/helpers/__init__.py` (empty), `backend/tests/helpers/files.py`
- Modify: `backend/pyproject.toml` (dependencies via `uv add`; mypy section)
- Test: `backend/tests/ingestion/test_converters.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure).
- Produces:
  - `app.ingestion.converters`: `convert_file(path: Path, ext: str) -> ConversionResult` (synchronous; callers use `asyncio.to_thread`), `ConversionResult(markdown, meta: ConversionMeta, warnings: list[str])`, `ConversionMeta(converter, chars, pages, outline, language)` with `.to_dict()`, `ConversionError(message)`, `Converter` protocol (`id`, `convert(path)`), `CONVERTERS`, `CONVERTIBLE_EXTENSIONS`, warning codes `LOW_TEXT = "low_text"`, `CSV_TRUNCATED = "csv_truncated"`.
  - Behaviour: docx/pptx/xlsx/html via markitdown after a container check; pdf via PyMuPDF for pages and password detection, markitdown for text with PyMuPDF text fallback, `low_text` when under 200 characters per page; md/txt UTF-8 (BOM stripped) with LF line endings; csv → Markdown table capped at 500 data rows with a truncation note; outline = first 30 headings; language via langdetect (None when undetectable); converter ids like `markitdown/0.1.8`, `pymupdf/1.28.2`, `builtin-text/1`, `builtin-csv/1`.
  - `tests.helpers.files`: `make_docx(path, headings, paragraphs)`, `make_pptx(path, slides)`, `make_xlsx(path, sheet, rows)`, `make_pdf(path, pages, *, password=None)`, `make_zip(path, entries, *, symlink=None)`, `pdf_bytes(pages)`, `docx_bytes(paragraphs)`.

- [ ] **Step 1: Dependencies and mypy configuration**

```bash
uv add "markitdown[docx,pptx,xlsx,pdf]" pymupdf langdetect
uv add --dev python-docx python-pptx openpyxl
```

Expected: `markitdown[docx,pptx,xlsx,pdf]>=0.1.8`, `pymupdf>=1.28.2`, `langdetect>=1.0.9` in dependencies (markitdown pulls `magika`, `onnxruntime`, `mammoth`, `pdfminer.six`, `openpyxl`, `pandas`, `python-pptx`); `python-docx`, `python-pptx`, `openpyxl` in the dev group.

In `backend/pyproject.toml` replace the `[tool.mypy]` section and the override that follows it with:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
exclude = ["migrations/"]
untyped_calls_exclude = ["pymupdf"]  # ships py.typed but leaves Document untyped

[[tool.mypy.overrides]]
module = ["pyotp", "langdetect", "langdetect.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: Fixture generators and failing tests**

Create `backend/tests/helpers/__init__.py` (empty).

`backend/tests/helpers/files.py`:

```python
"""Synthetic fixture files generated at test time; nothing binary is committed and no customer
content is used."""

import io
import stat
import zipfile
from pathlib import Path

import openpyxl
import pymupdf
from docx import Document as DocxDocument
from pptx import Presentation


def make_docx(path: Path, headings: list[tuple[int, str]], paragraphs: list[str]) -> Path:
    document = DocxDocument()
    for level, text in headings:
        document.add_heading(text, level=level)
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(str(path))
    return path


def make_pptx(path: Path, slides: list[tuple[str, str]]) -> Path:
    presentation = Presentation()
    layout = presentation.slide_layouts[1]
    for title, body in slides:
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    presentation.save(str(path))
    return path


def make_xlsx(path: Path, sheet: str, rows: list[list[str]]) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in rows:
        worksheet.append(row)
    workbook.save(str(path))
    return path


def make_pdf(path: Path, pages: list[str], *, password: str | None = None) -> Path:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        y = 72
        for line in text.splitlines() or [""]:
            page.insert_text((72, y), line, fontsize=11)
            y += 14
    if password:
        document.save(
            str(path),
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password,
        )
    else:
        document.save(str(path))
    document.close()
    return path


def make_zip(
    path: Path,
    entries: dict[str, bytes],
    *,
    symlink: str | None = None,
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        if symlink is not None:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "target.txt")
    return path


def pdf_bytes(pages: list[str]) -> bytes:
    document = pymupdf.open()
    for text in pages:
        document.new_page().insert_text((72, 72), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return bytes(data)


def docx_bytes(paragraphs: list[str]) -> bytes:
    buffer = io.BytesIO()
    document = DocxDocument()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()
```

`backend/tests/ingestion/test_converters.py`:

```python
from pathlib import Path

import pytest

from app.ingestion.converters import (
    CSV_TRUNCATED,
    LOW_TEXT,
    ConversionError,
    convert_file,
)
from tests.helpers.files import make_docx, make_pdf, make_pptx, make_xlsx

VI_TEXT = (
    "Hệ thống cho phép người dùng đăng nhập bằng mật khẩu và mã xác thực hai lớp. "
    "Tài liệu này mô tả yêu cầu phần mềm cho cổng khách hàng."
)
EN_TEXT = (
    "The system shall allow users to log in with a password and a one-time code. "
    "This document describes the software requirements for the customer portal."
)


def test_docx_headings_outline_and_language(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "srs.docx",
        headings=[(1, "Software Requirements"), (2, "Scope")],
        paragraphs=[VI_TEXT, VI_TEXT],
    )
    result = convert_file(path, "docx")
    assert result.markdown.startswith("# Software Requirements\n")
    assert result.meta.outline == ["# Software Requirements", "## Scope"]
    assert result.meta.language == "vi"
    assert result.meta.converter.startswith("markitdown/")
    assert result.meta.pages is None and result.meta.chars == len(result.markdown)
    assert result.warnings == []


def test_pptx_and_xlsx(tmp_path: Path) -> None:
    pptx = convert_file(make_pptx(tmp_path / "plan.pptx", [("Test Plan", EN_TEXT)]), "pptx")
    assert "# Test Plan" in pptx.markdown and pptx.meta.language == "en"
    xlsx = convert_file(
        make_xlsx(tmp_path / "cases.xlsx", "Cases", [["ID", "Title"], ["TC-1", "Login works"]]),
        "xlsx",
    )
    assert "## Cases" in xlsx.markdown and "| TC-1 | Login works |" in xlsx.markdown


def test_html(tmp_path: Path) -> None:
    path = tmp_path / "runbook.html"
    path.write_text(f"<html><body><h1>Runbook</h1><p>{EN_TEXT}</p><h2>Steps</h2></body></html>")
    result = convert_file(path, "html")
    assert result.meta.outline == ["# Runbook", "## Steps"]


def test_pdf_pages_and_text(tmp_path: Path) -> None:
    page = "\n".join([EN_TEXT] * 3)  # about 450 characters per page, above the low-text bar
    path = make_pdf(tmp_path / "guide.pdf", [page, page, page])
    result = convert_file(path, "pdf")
    assert result.meta.pages == 3
    assert "customer portal" in result.markdown
    assert "\x0c" not in result.markdown
    assert result.warnings == []


def test_blank_pdf_gets_low_text_warning_and_pymupdf_fallback(tmp_path: Path) -> None:
    result = convert_file(make_pdf(tmp_path / "scan.pdf", ["", "", ""]), "pdf")
    assert result.meta.pages == 3
    assert LOW_TEXT in result.warnings
    assert result.meta.converter.startswith("pymupdf/")
    assert result.meta.language is None


def test_password_protected_pdf_is_rejected_with_a_clear_reason(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "secret.pdf", [EN_TEXT], password="pw")
    with pytest.raises(ConversionError, match="password-protected"):
        convert_file(path, "pdf")


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx", "pdf"])
def test_mismatched_content_is_rejected(tmp_path: Path, ext: str) -> None:
    path = tmp_path / f"fake.{ext}"
    path.write_bytes(b"this is plain text pretending to be a document")
    with pytest.raises(ConversionError, match="does not match"):
        convert_file(path, ext)


def test_zip_disguised_as_docx_is_rejected(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "fake.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ConversionError, match="does not match"):
        convert_file(path, "docx")


def test_markdown_and_text_pass_through_with_normalised_newlines(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(b"\xef\xbb\xbf# Notes\r\n\r\nLine one\r\nLine two")
    result = convert_file(path, "md")
    assert result.markdown == "# Notes\n\nLine one\nLine two\n"
    assert result.meta.converter == "builtin-text/1"
    txt = tmp_path / "plain.txt"
    txt.write_bytes("Ghi chú\n".encode())
    assert convert_file(txt, "txt").markdown == "Ghi chú\n"


def test_non_utf8_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"caf\xe9")
    with pytest.raises(ConversionError, match="UTF-8"):
        convert_file(path, "txt")


def test_csv_becomes_table_and_is_capped(tmp_path: Path) -> None:
    path = tmp_path / "cases.csv"
    rows = ["id,title,expected"] + [f"TC-{i},Case {i}|x,ok" for i in range(600)]
    path.write_text("\n".join(rows))
    result = convert_file(path, "csv")
    assert result.markdown.startswith("| id | title | expected |\n| --- | --- | --- |\n")
    assert "| TC-0 | Case 0\\|x | ok |" in result.markdown
    assert "TC-500" not in result.markdown
    assert CSV_TRUNCATED in result.warnings
    assert result.markdown.rstrip().endswith("> Truncated: showing 500 of 600 rows.")


def test_unknown_extension(tmp_path: Path) -> None:
    with pytest.raises(ConversionError, match="cannot be converted"):
        convert_file(tmp_path / "x.exe", "exe")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_converters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.converters'`.

- [ ] **Step 4: Implement the converters**

`backend/app/ingestion/converters/base.py`:

```python
"""Converter interface and shared helpers (spec 6.3 step 2)."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0  # langdetect is otherwise non-deterministic for short texts

LOW_TEXT = "low_text"
CSV_TRUNCATED = "csv_truncated"
LOW_TEXT_CHARS_PER_PAGE = 200
OUTLINE_LIMIT = 30
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LANGUAGE_SAMPLE_CHARS = 20_000
_LANGUAGE_MIN_CHARS = 20


class ConversionError(Exception):
    """Conversion failed; the message is shown to the uploader."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ConversionMeta:
    converter: str  # "<id>/<version>"
    chars: int
    pages: int | None = None
    outline: list[str] = field(default_factory=list)
    language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "converter": self.converter,
            "chars": self.chars,
            "pages": self.pages,
            "outline": list(self.outline),
            "language": self.language,
        }


@dataclass(frozen=True)
class ConversionResult:
    markdown: str
    meta: ConversionMeta
    warnings: list[str] = field(default_factory=list)


class Converter(Protocol):
    id: str

    def convert(self, path: Path) -> ConversionResult: ...


def normalize_newlines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    return text.strip("\n") + "\n" if text.strip() else ""


def extract_outline(markdown: str, limit: int = OUTLINE_LIMIT) -> list[str]:
    outline: list[str] = []
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            outline.append(f"{match.group(1)} {match.group(2)}")
            if len(outline) >= limit:
                break
    return outline


def detect_language(text: str) -> str | None:
    sample = text[:_LANGUAGE_SAMPLE_CHARS]
    if len(sample.strip()) < _LANGUAGE_MIN_CHARS:
        return None
    try:
        return str(detect(sample))
    except LangDetectException:
        return None


def build_result(
    markdown: str, *, converter: str, pages: int | None = None, warnings: list[str] | None = None
) -> ConversionResult:
    normalized = normalize_newlines(markdown)
    result_warnings = list(warnings or [])
    if (
        pages
        and len(normalized) / pages < LOW_TEXT_CHARS_PER_PAGE
        and LOW_TEXT not in result_warnings
    ):
        result_warnings.append(LOW_TEXT)
    meta = ConversionMeta(
        converter=converter,
        chars=len(normalized),
        pages=pages,
        outline=extract_outline(normalized),
        language=detect_language(normalized),
    )
    return ConversionResult(markdown=normalized, meta=meta, warnings=result_warnings)
```

`backend/app/ingestion/converters/office.py`:

```python
"""markitdown-based conversion for docx, pptx, xlsx and html.

Verified against markitdown 0.1.8: ``MarkItDown().convert(path, stream_info=StreamInfo(...))``
returns ``DocumentConverterResult`` whose ``text_content`` equals ``markdown``. markitdown
sniffs content and silently converts unrecognised bytes as plain text (and extracts plain zip
archives), so OOXML containers are validated here before conversion.
"""

import zipfile
from importlib.metadata import version
from pathlib import Path

from markitdown import MarkItDown, MarkItDownException, StreamInfo

from app.ingestion.converters.base import ConversionError, ConversionResult, build_result

OOXML_EXTENSIONS = frozenset({"docx", "pptx", "xlsx"})
_engine: MarkItDown | None = None


def markitdown_engine() -> MarkItDown:
    global _engine
    if _engine is None:
        _engine = MarkItDown(enable_plugins=False)
    return _engine


def markitdown_version() -> str:
    return f"markitdown/{version('markitdown')}"


def check_container(path: Path, ext: str) -> None:
    """Reject files whose bytes do not match their extension."""
    if ext in OOXML_EXTENSIONS:
        if not zipfile.is_zipfile(path):
            raise ConversionError("File content does not match its extension.")
        with zipfile.ZipFile(path) as archive:
            if "[Content_Types].xml" not in archive.namelist():
                raise ConversionError("File content does not match its extension.")
    elif ext == "pdf":
        with path.open("rb") as handle:
            if not handle.read(5).startswith(b"%PDF-"):
                raise ConversionError("File content does not match its extension.")


def markitdown_text(path: Path, ext: str) -> str:
    try:
        result = markitdown_engine().convert(str(path), stream_info=StreamInfo(extension=f".{ext}"))
    except MarkItDownException as exc:
        raise ConversionError(f"The file could not be converted ({type(exc).__name__}).") from exc
    return str(result.text_content)


class OfficeConverter:
    """docx, pptx, xlsx and html via markitdown."""

    id = "markitdown"

    def __init__(self, ext: str) -> None:
        self._ext = ext

    def convert(self, path: Path) -> ConversionResult:
        check_container(path, self._ext)
        return build_result(markitdown_text(path, self._ext), converter=markitdown_version())
```

`backend/app/ingestion/converters/pdf.py`:

```python
"""PDF conversion: markitdown text with a pymupdf fallback; pymupdf provides the page count
and detects password protection (spec 6.3 step 2, 14)."""

from pathlib import Path

import pymupdf

from app.ingestion.converters.base import ConversionError, ConversionResult, build_result
from app.ingestion.converters.office import check_container, markitdown_text, markitdown_version


def pymupdf_version() -> str:
    return f"pymupdf/{pymupdf.VersionBind}"


class PdfConverter:
    id = "pdf"

    def convert(self, path: Path) -> ConversionResult:
        check_container(path, "pdf")
        try:
            document = pymupdf.open(str(path))
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError) as exc:
            raise ConversionError("File is not a readable PDF.") from exc
        with document:
            if document.needs_pass:
                raise ConversionError(
                    "PDF is password-protected. Remove the password and upload again."
                )
            pages = int(document.page_count)
            fallback = "\n\n".join(
                str(document.load_page(index).get_text("text")) for index in range(pages)
            )
        try:
            markdown = markitdown_text(path, "pdf")
            converter = markitdown_version()
        except ConversionError:
            markdown = ""
            converter = pymupdf_version()
        if not markdown.strip():
            markdown = fallback
            converter = pymupdf_version()
        return build_result(markdown, converter=converter, pages=pages)
```

`backend/app/ingestion/converters/text.py`:

```python
"""Built-in converters for Markdown, plain text and CSV."""

import csv
import io
from pathlib import Path

from app.ingestion.converters.base import (
    CSV_TRUNCATED,
    ConversionError,
    ConversionResult,
    build_result,
)

CSV_ROW_LIMIT = 500
_BUILTIN_TEXT = "builtin-text/1"
_BUILTIN_CSV = "builtin-csv/1"


def decode_utf8(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConversionError("Text files must be UTF-8 encoded.") from exc


class TextConverter:
    """md and txt: UTF-8 normalised, LF line endings, content otherwise untouched."""

    id = "text"

    def convert(self, path: Path) -> ConversionResult:
        return build_result(decode_utf8(path), converter=_BUILTIN_TEXT)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


class CsvConverter:
    """csv: a Markdown table capped at CSV_ROW_LIMIT data rows."""

    id = "csv"

    def convert(self, path: Path) -> ConversionResult:
        text = decode_utf8(path)
        rows = list(csv.reader(io.StringIO(text)))
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if not rows:
            raise ConversionError("CSV file has no rows.")
        header, data = rows[0], rows[1:]
        width = max(len(row) for row in rows)
        header = header + [""] * (width - len(header))
        lines = [
            "| " + " | ".join(_cell(c) for c in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in data[:CSV_ROW_LIMIT]:
            padded = row + [""] * (width - len(row))
            lines.append("| " + " | ".join(_cell(c) for c in padded) + " |")
        warnings: list[str] = []
        if len(data) > CSV_ROW_LIMIT:
            warnings.append(CSV_TRUNCATED)
            lines += ["", f"> Truncated: showing {CSV_ROW_LIMIT} of {len(data)} rows."]
        return build_result("\n".join(lines), converter=_BUILTIN_CSV, warnings=warnings)
```

`backend/app/ingestion/converters/__init__.py`:

```python
"""Deterministic conversion of uploaded files to Markdown (spec 6.3 step 2).

``convert_file`` is synchronous and CPU/IO bound; callers run it in a worker thread.
"""

from pathlib import Path

from app.ingestion.converters.base import (
    CSV_TRUNCATED,
    LOW_TEXT,
    ConversionError,
    ConversionMeta,
    ConversionResult,
    Converter,
)
from app.ingestion.converters.office import OfficeConverter
from app.ingestion.converters.pdf import PdfConverter
from app.ingestion.converters.text import CsvConverter, TextConverter

CONVERTERS: dict[str, Converter] = {
    "docx": OfficeConverter("docx"),
    "pptx": OfficeConverter("pptx"),
    "xlsx": OfficeConverter("xlsx"),
    "html": OfficeConverter("html"),
    "pdf": PdfConverter(),
    "md": TextConverter(),
    "txt": TextConverter(),
    "csv": CsvConverter(),
}

CONVERTIBLE_EXTENSIONS = frozenset(CONVERTERS)


def convert_file(path: Path, ext: str) -> ConversionResult:
    converter = CONVERTERS.get(ext)
    if converter is None:
        raise ConversionError(f"Files of type .{ext} cannot be converted.")
    return converter.convert(path)


__all__ = [
    "CONVERTERS",
    "CONVERTIBLE_EXTENSIONS",
    "CSV_TRUNCATED",
    "LOW_TEXT",
    "ConversionError",
    "ConversionMeta",
    "ConversionResult",
    "Converter",
    "convert_file",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_converters.py -v`
Expected: `15 passed`. (PyMuPDF prints three `DeprecationWarning: builtin type SwigPy… has no __module__ attribute` lines at interpreter exit; they are harmless.)

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/pyproject.toml backend/uv.lock backend/app/ingestion/converters backend/tests/helpers backend/tests/ingestion/test_converters.py
git commit -m "feat(backend): add deterministic converters for office, pdf, text and csv"
```

---

### Task 8: Upload validation, file-name sanitising, staging and zip safety

**Files:**
- Create: `backend/app/ingestion/intake.py`
- Modify: `backend/pyproject.toml` (`uv add anyio`)
- Test: `backend/tests/ingestion/test_intake.py`

**Interfaces:**
- Consumes: `make_zip` (Task 7).
- Produces: `app.ingestion.intake`: `ALLOWED_EXTENSIONS`, `IntakeLimits(max_file_bytes, max_batch_bytes, zip_max_entries=200)` with `.from_megabytes(file_mb, batch_mb)`, `StagedFile(name, ext, path, size, sha256)`, `Rejection(name, reason)`, `ReadChunk = Callable[[int], Awaitable[bytes]]`, `file_extension(name) -> str | None`, `sanitize_filename(name) -> str`, `extension_rejection(name) -> Rejection | None`, `size_limit_reason(limits)`, `batch_limit_reason(limits)`, `async stage_stream(read, dest, *, max_bytes) -> tuple[int, str] | None` (streams 1 MiB chunks while hashing; None and no file when the cap is exceeded), `zip_entry_rejection(info, limits) -> Rejection | None`, `expand_zip(staged, dest_dir, limits) -> tuple[list[StagedFile], list[Rejection]]` (synchronous; callers use `asyncio.to_thread`).

- [ ] **Step 1: Dependency**

```bash
uv add anyio
```

Expected: `anyio>=4.15.1` in dependencies (already installed transitively through Starlette; declared because `stage_stream` imports it directly).

- [ ] **Step 2: Write the failing tests**

`backend/tests/ingestion/test_intake.py`:

```python
import hashlib
import zipfile
from pathlib import Path

from app.ingestion.intake import (
    IntakeLimits,
    StagedFile,
    expand_zip,
    extension_rejection,
    file_extension,
    sanitize_filename,
    stage_stream,
    zip_entry_rejection,
)
from tests.helpers.files import make_zip

LIMITS = IntakeLimits(max_file_bytes=1024, max_batch_bytes=4096, zip_max_entries=5)


def test_sanitize_filename() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\me\\Báo cáo (final).docx") == "Báo cáo (final).docx"
    assert sanitize_filename("  weird\x00name?.pdf  ") == "weirdname_.pdf"
    assert sanitize_filename("...") == "file"
    long_name = "a" * 300 + ".docx"
    assert (
        sanitize_filename(long_name).endswith(".docx") and len(sanitize_filename(long_name)) <= 200
    )


def test_extension_rules() -> None:
    assert file_extension("Report.PDF") == "pdf"
    assert file_extension("page.htm") == "html"
    assert file_extension("noext") is None
    assert extension_rejection("virus.exe") is not None
    assert extension_rejection("ok.docx") is None


def _reader(data: bytes):  # type: ignore[no-untyped-def]
    view = memoryview(data)
    position = 0

    async def read(size: int) -> bytes:
        nonlocal position
        chunk = bytes(view[position : position + size])
        position += size
        return chunk

    return read


async def test_stage_stream_hashes_and_enforces_cap(tmp_path: Path) -> None:
    data = b"x" * 1000
    result = await stage_stream(_reader(data), tmp_path / "in" / "a.bin", max_bytes=1024)
    assert result == (1000, hashlib.sha256(data).hexdigest())
    assert (tmp_path / "in" / "a.bin").read_bytes() == data
    too_big = await stage_stream(_reader(b"y" * 2000), tmp_path / "in" / "b.bin", max_bytes=1024)
    assert too_big is None and not (tmp_path / "in" / "b.bin").exists()


def _staged(path: Path) -> StagedFile:
    data = path.read_bytes()
    return StagedFile(
        name=path.name,
        ext="zip",
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_zip_safety(tmp_path: Path) -> None:
    archive = make_zip(
        tmp_path / "export.zip",
        {
            "docs/Requirements.md": b"# Req",
            "../evil.md": b"x",
            "/abs.md": b"x",
            "docs/nested.zip": b"PK\x03\x04",
            "docs/script.exe": b"x",
            "__MACOSX/._Requirements.md": b"junk",
            "docs/.DS_Store": b"junk",
            "big.txt": b"z" * 2000,
        },
        symlink="docs/link.md",
    )
    limits = IntakeLimits(max_file_bytes=1024, max_batch_bytes=4096, zip_max_entries=20)
    files, rejections = expand_zip(_staged(archive), tmp_path / "out", limits)
    assert [f.name for f in files] == ["Requirements.md"]
    assert files[0].path.parent == tmp_path / "out" and files[0].path.read_bytes() == b"# Req"
    reasons = {r.name: r.reason for r in rejections}
    assert reasons["../evil.md"] == "Zip entry path is not allowed."
    assert reasons["/abs.md"] == "Zip entry path is not allowed."
    assert reasons["docs/nested.zip"] == "Nested zip archives are not extracted."
    assert reasons["docs/script.exe"].startswith("File type is not supported.")
    assert reasons["docs/link.md"] == "Symbolic links in zip archives are not allowed."
    assert reasons["big.txt"] == "File exceeds the 0 MB limit."
    assert "__MACOSX/._Requirements.md" not in reasons and "docs/.DS_Store" not in reasons


def test_encrypted_entry_rule() -> None:
    info = zipfile.ZipInfo("docs/secret.md")
    info.flag_bits |= 0x1
    rejection = zip_entry_rejection(info, LIMITS)
    assert rejection is not None and rejection.reason == "Encrypted zip entries are not supported."
    assert zip_entry_rejection(zipfile.ZipInfo("docs/fine.md"), LIMITS) is None


def test_zip_entry_count_and_batch_limits(tmp_path: Path) -> None:
    many = make_zip(tmp_path / "many.zip", {f"f{i}.md": b"x" for i in range(6)})
    files, rejections = expand_zip(_staged(many), tmp_path / "out", LIMITS)
    assert files == [] and rejections[0].reason == "Zip archive has more than 5 entries."
    batch = make_zip(tmp_path / "batch.zip", {f"f{i}.md": b"x" * 1000 for i in range(5)})
    files, rejections = expand_zip(_staged(batch), tmp_path / "out2", LIMITS)
    assert len(files) == 4 and rejections[0].reason == "Upload batch exceeds the 0 MB limit."


def test_invalid_zip(tmp_path: Path) -> None:
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    files, rejections = expand_zip(_staged(broken), tmp_path / "out", LIMITS)
    assert files == [] and rejections == [
        type(rejections[0])("broken.zip", "File is not a valid zip archive.")
    ]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_intake.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.intake'`.

- [ ] **Step 4: Implement**

`backend/app/ingestion/intake.py`:

```python
"""Upload validation, file-name sanitising, staging and zip safety (spec 6.3 step 1, 13).

Everything here is framework-free: the API layer passes an async ``read`` callable (an
``UploadFile.read`` fits) and receives ``StagedFile`` records that point into the staging
directory. Blocking file work runs in worker threads.
"""

import asyncio
import hashlib
import re
import stat
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import anyio

ALLOWED_EXTENSIONS = frozenset({"docx", "pdf", "xlsx", "pptx", "md", "txt", "html", "csv", "zip"})
CHUNK_SIZE = 1024 * 1024
MAX_FILENAME_LENGTH = 200
ZIP_MAX_ENTRIES = 200
_EXTENSION_ALIASES = {"htm": "html"}
_UNSAFE_CHARS = re.compile(r"[^\w .()\-]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

ReadChunk = Callable[[int], Awaitable[bytes]]


@dataclass(frozen=True)
class IntakeLimits:
    max_file_bytes: int
    max_batch_bytes: int
    zip_max_entries: int = ZIP_MAX_ENTRIES

    @classmethod
    def from_megabytes(cls, max_file_mb: int, max_batch_mb: int) -> "IntakeLimits":
        return cls(
            max_file_bytes=max_file_mb * 1024 * 1024, max_batch_bytes=max_batch_mb * 1024 * 1024
        )


@dataclass(frozen=True)
class StagedFile:
    name: str  # sanitised original file name
    ext: str
    path: Path  # absolute path inside the staging directory
    size: int
    sha256: str


@dataclass(frozen=True)
class Rejection:
    name: str
    reason: str


def file_extension(name: str) -> str | None:
    suffix = PurePosixPath(name).suffix.lower().lstrip(".")
    if not suffix:
        return None
    return _EXTENSION_ALIASES.get(suffix, suffix)


def sanitize_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable())
    base = _UNSAFE_CHARS.sub("_", base)
    base = _WHITESPACE.sub(" ", base).strip(" .")
    if not base:
        return "file"
    if len(base) > MAX_FILENAME_LENGTH:
        stem, dot, ext = base.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            base = stem[: MAX_FILENAME_LENGTH - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            base = base[:MAX_FILENAME_LENGTH].rstrip(" .")
    return base


def extension_rejection(name: str) -> Rejection | None:
    ext = file_extension(name)
    if ext is None or ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return Rejection(name, f"File type is not supported. Allowed: {allowed}.")
    return None


def size_limit_reason(limits: IntakeLimits) -> str:
    return f"File exceeds the {limits.max_file_bytes // (1024 * 1024)} MB limit."


def batch_limit_reason(limits: IntakeLimits) -> str:
    return f"Upload batch exceeds the {limits.max_batch_bytes // (1024 * 1024)} MB limit."


async def stage_stream(read: ReadChunk, dest: Path, *, max_bytes: int) -> tuple[int, str] | None:
    """Stream to ``dest`` while hashing. Returns (size, sha256) or None when the cap is exceeded
    (the partial file is removed)."""
    await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    async with await anyio.open_file(dest, "wb") as handle:
        while True:
            chunk = await read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                break
            digest.update(chunk)
            await handle.write(chunk)
    if size > max_bytes:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        return None
    return size, digest.hexdigest()


def zip_entry_rejection(info: zipfile.ZipInfo, limits: IntakeLimits) -> Rejection | None:
    raw = info.filename.replace("\\", "/")
    parts = [part for part in raw.split("/") if part]
    if not parts or raw.startswith("/") or _DRIVE_RE.match(raw) or ".." in parts:
        return Rejection(info.filename, "Zip entry path is not allowed.")
    if stat.S_ISLNK(info.external_attr >> 16):
        return Rejection(info.filename, "Symbolic links in zip archives are not allowed.")
    if info.flag_bits & 0x1:
        return Rejection(info.filename, "Encrypted zip entries are not supported.")
    ext = file_extension(parts[-1])
    if ext == "zip":
        return Rejection(info.filename, "Nested zip archives are not extracted.")
    if ext is None or ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS - {"zip"}))
        return Rejection(info.filename, f"File type is not supported. Allowed: {allowed}.")
    if info.file_size > limits.max_file_bytes:
        return Rejection(info.filename, size_limit_reason(limits))
    return None


def _is_hidden(info: zipfile.ZipInfo) -> bool:
    parts = [part for part in info.filename.replace("\\", "/").split("/") if part]
    return not parts or parts[0] == "__MACOSX" or parts[-1].startswith(".")


def _extract_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path, limits: IntakeLimits
) -> tuple[int, str] | None:
    digest = hashlib.sha256()
    size = 0
    with archive.open(info) as source, dest.open("wb") as handle:
        while True:
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            size += len(chunk)
            if size > limits.max_file_bytes:
                break
            digest.update(chunk)
            handle.write(chunk)
    if size > limits.max_file_bytes:
        dest.unlink(missing_ok=True)
        return None
    return size, digest.hexdigest()


def expand_zip(
    staged: StagedFile, dest_dir: Path, limits: IntakeLimits
) -> tuple[list[StagedFile], list[Rejection]]:
    """Extract the safe entries of a zip into ``dest_dir``; every unsafe entry becomes a
    rejection. Hidden entries (``__MACOSX``, dot files) are skipped silently."""
    try:
        archive = zipfile.ZipFile(staged.path)
    except zipfile.BadZipFile:
        return [], [Rejection(staged.name, "File is not a valid zip archive.")]
    with archive:
        entries = [
            info for info in archive.infolist() if not info.is_dir() and not _is_hidden(info)
        ]
        if len(entries) > limits.zip_max_entries:
            reason = f"Zip archive has more than {limits.zip_max_entries} entries."
            return [], [Rejection(staged.name, reason)]
        files: list[StagedFile] = []
        rejections: list[Rejection] = []
        total = 0
        dest_dir.mkdir(parents=True, exist_ok=True)
        for info in entries:
            rejection = zip_entry_rejection(info, limits)
            if rejection is not None:
                rejections.append(rejection)
                continue
            name = sanitize_filename(info.filename.replace("\\", "/").rsplit("/", 1)[-1])
            ext = file_extension(name)
            if ext is None:
                continue
            if total + info.file_size > limits.max_batch_bytes:
                rejections.append(Rejection(info.filename, batch_limit_reason(limits)))
                continue
            dest = dest_dir / f"{uuid.uuid4().hex}.{ext}"
            extracted = _extract_entry(archive, info, dest, limits)
            if extracted is None:
                rejections.append(Rejection(info.filename, size_limit_reason(limits)))
                continue
            size, sha256 = extracted
            total += size
            files.append(StagedFile(name=name, ext=ext, path=dest, size=size, sha256=sha256))
    return files, rejections
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_intake.py -v`
Expected: `7 passed`.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/pyproject.toml backend/uv.lock backend/app/ingestion/intake.py backend/tests/ingestion/test_intake.py
git commit -m "feat(backend): add upload validation, staging and zip safety"
```

---

### Task 9: Analyzer interface, `SkipAnalyzer`, `FakeAnalyzer`, injection through `create_app`

**Files:**
- Create: `backend/app/agent/__init__.py` (empty), `backend/app/agent/analyzer.py`, `backend/app/agent/fake.py`
- Modify: `backend/app/main.py` (signature, import, one state line), `backend/tests/conftest.py` (`make_app`)
- Test: `backend/tests/agent/__init__.py` (empty), `backend/tests/agent/test_analyzers.py`

**Interfaces:**
- Consumes: `create_app` (Task 2).
- Produces:
  - `app.agent.analyzer`: `Analyzer` protocol with `async check(batch: CheckBatch) -> CheckResult`; dataclasses `ExistingDocument(document_id, doc_type, title)`, `CheckItem(item_id, file_name, selected_doc_type, title, outline, preview, language)`, `CheckBatch(project_id, items, allowed_doc_types, existing_documents=[])`, `ItemVerdict(item_id, verdict: "match"|"mismatch"|"skipped", explanation="", suggested_doc_type=None, version_of_document_id=None, confidence=None)`, `CheckResult(verdicts, cost_usd=0.0)`; `SkipAnalyzer` (every item `skipped`, explanation `SKIP_EXPLANATION`). Plan 4 adds `normalize` and the SDK implementation behind the same protocol.
  - `app.agent.fake`: `ScriptedVerdict(verdict, explanation="", suggested_doc_type=None, version_of_document_id=None, confidence=0.9)`, `FakeAnalyzer(scripted: Mapping[file_name, ScriptedVerdict] | None = None, *, error: Exception | None = None)` with `.batches` recording every call; unscripted items get `match`.
  - `create_app(settings=None, *, analyzer: Analyzer | None = None)`; `app.state.analyzer`; test fixture `make_app(*, analyzer=None, **overrides)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/agent/__init__.py` (empty).

`backend/tests/agent/test_analyzers.py`:

```python
import uuid

import pytest

from app.agent.analyzer import CheckBatch, CheckItem, SkipAnalyzer
from app.agent.fake import FakeAnalyzer, ScriptedVerdict


def _batch() -> CheckBatch:
    item = CheckItem(
        item_id=uuid.uuid4(),
        file_name="srs.docx",
        selected_doc_type="srs",
        title="SRS",
        outline=["# SRS"],
        preview="The system shall...",
        language="en",
    )
    other = CheckItem(
        item_id=uuid.uuid4(),
        file_name="plan.docx",
        selected_doc_type="srs",
        title="Plan",
        outline=["# Test Plan"],
        preview="Scope of testing",
        language="en",
    )
    return CheckBatch(
        project_id=uuid.uuid4(), items=[item, other], allowed_doc_types=["srs", "test-plan"]
    )


async def test_skip_analyzer_skips_everything() -> None:
    batch = _batch()
    result = await SkipAnalyzer().check(batch)
    assert [v.verdict for v in result.verdicts] == ["skipped", "skipped"]
    assert [v.item_id for v in result.verdicts] == [i.item_id for i in batch.items]


async def test_fake_analyzer_scripts_by_file_name_and_records_batches() -> None:
    fake = FakeAnalyzer(
        {"plan.docx": ScriptedVerdict("mismatch", "Looks like a test plan.", "test-plan")}
    )
    batch = _batch()
    result = await fake.check(batch)
    assert fake.batches == [batch]
    assert result.verdicts[0].verdict == "match"
    assert result.verdicts[1].verdict == "mismatch"
    assert result.verdicts[1].suggested_doc_type == "test-plan"


async def test_fake_analyzer_can_fail() -> None:
    fake = FakeAnalyzer(error=RuntimeError("agent unavailable"))
    with pytest.raises(RuntimeError):
        await fake.check(_batch())


def test_create_app_uses_skip_analyzer_by_default_and_accepts_injection() -> None:
    from app.core.config import Settings
    from app.main import create_app

    assert isinstance(create_app(Settings()).state.analyzer, SkipAnalyzer)  # type: ignore[call-arg]
    fake = FakeAnalyzer()
    assert create_app(Settings(), analyzer=fake).state.analyzer is fake  # type: ignore[call-arg]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent'`.

- [ ] **Step 3: Implement**

Create `backend/app/agent/__init__.py` (empty).

`backend/app/agent/analyzer.py`:

```python
"""Analyzer interface (spec 7.1, check only). The agent plan adds the SDK implementation and
``normalize``; this plan ships ``SkipAnalyzer`` for production and ``FakeAnalyzer`` for tests."""

import uuid
from dataclasses import dataclass, field
from typing import Literal, Protocol

Verdict = Literal["match", "mismatch", "skipped"]
SKIP_EXPLANATION = "Type check is not available yet; the selected type was kept."


@dataclass(frozen=True)
class ExistingDocument:
    document_id: uuid.UUID
    doc_type: str
    title: str


@dataclass(frozen=True)
class CheckItem:
    item_id: uuid.UUID
    file_name: str
    selected_doc_type: str
    title: str
    outline: list[str]
    preview: str
    language: str | None


@dataclass(frozen=True)
class CheckBatch:
    project_id: uuid.UUID
    items: list[CheckItem]
    allowed_doc_types: list[str]
    existing_documents: list[ExistingDocument] = field(default_factory=list)


@dataclass(frozen=True)
class ItemVerdict:
    item_id: uuid.UUID
    verdict: Verdict
    explanation: str = ""
    suggested_doc_type: str | None = None
    version_of_document_id: uuid.UUID | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class CheckResult:
    verdicts: list[ItemVerdict]
    cost_usd: float = 0.0


class Analyzer(Protocol):
    async def check(self, batch: CheckBatch) -> CheckResult: ...


class SkipAnalyzer:
    """Production default until the agent plan: every item is ``skipped``."""

    async def check(self, batch: CheckBatch) -> CheckResult:
        return CheckResult(
            verdicts=[
                ItemVerdict(item_id=item.item_id, verdict="skipped", explanation=SKIP_EXPLANATION)
                for item in batch.items
            ]
        )
```

`backend/app/agent/fake.py`:

```python
"""Scripted analyzer for tests: verdicts keyed by file name, batches recorded."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.agent.analyzer import CheckBatch, CheckResult, ItemVerdict, Verdict


@dataclass(frozen=True)
class ScriptedVerdict:
    verdict: Verdict
    explanation: str = ""
    suggested_doc_type: str | None = None
    version_of_document_id: uuid.UUID | None = None
    confidence: float | None = 0.9


class FakeAnalyzer:
    def __init__(
        self,
        scripted: Mapping[str, ScriptedVerdict] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.scripted = dict(scripted or {})
        self.error = error
        self.batches: list[CheckBatch] = []

    async def check(self, batch: CheckBatch) -> CheckResult:
        self.batches.append(batch)
        if self.error is not None:
            raise self.error
        verdicts = []
        for item in batch.items:
            script = self.scripted.get(item.file_name, ScriptedVerdict("match", "Content matches."))
            verdicts.append(
                ItemVerdict(
                    item_id=item.item_id,
                    verdict=script.verdict,
                    explanation=script.explanation,
                    suggested_doc_type=script.suggested_doc_type,
                    version_of_document_id=script.version_of_document_id,
                    confidence=script.confidence,
                )
            )
        return CheckResult(verdicts=verdicts, cost_usd=0.0)
```

In `backend/app/main.py`: add `from app.agent.analyzer import Analyzer, SkipAnalyzer` to the imports, change the factory signature to

```python
def create_app(settings: Settings | None = None, *, analyzer: Analyzer | None = None) -> FastAPI:
```

and add, directly after `app.state.taxonomy = taxonomy`:

```python
    app.state.analyzer = analyzer or SkipAnalyzer()
```

In `backend/tests/conftest.py` add `from app.agent.analyzer import Analyzer  # noqa: E402` to the imports and replace the `make_app` fixture with:

```python
@pytest.fixture
def make_app(db_sessionmaker: async_sessionmaker[AsyncSession]) -> Callable[..., FastAPI]:
    def _make(*, analyzer: Analyzer | None = None, **overrides: Any) -> FastAPI:
        return create_app(Settings(**overrides), analyzer=analyzer)  # type: ignore[call-arg]

    return _make
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent tests/api/test_health.py -v`
Expected: all passed (`4` in `tests/agent`).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app/agent backend/app/main.py backend/tests/agent backend/tests/conftest.py
git commit -m "feat(backend): add analyzer interface with skip and fake implementations"
```

---

### Task 10: Upload intake service

**Files:**
- Create: `backend/app/schemas/uploads.py`, `backend/app/services/uploads.py`
- Test: `backend/tests/ingestion/test_upload_service.py`

**Interfaces:**
- Consumes: intake functions (Task 8), `title_from_filename` (Task 4), `Taxonomy` (Task 2), models (Task 5), `make_project`, `make_zip`, `docx_bytes` (Tasks 6–7).
- Produces:
  - `app.schemas.uploads`: `UploadItemSpec(doc_type, title=None, intent="new"|"version", target_document_id=None, visibility="internal"|"shared")` (extra fields forbidden; blank titles become None), `RejectionOut`, `UploadItemOut`, `UploadOut`, `TaskOut(item, project_id, project_name)`, `ConfirmTypeRequest(doc_type)`.
  - `app.services.uploads`: `IncomingFile(name, read)`, `StagedItem(file, spec)`, `staging_dir_for(staging_root, upload_id) -> Path`, `async stage_files(files, specs, *, staging_dir, limits) -> tuple[list[StagedItem], list[Rejection]]`, `async create_upload(db, *, project, uploader, role, upload_id, staged, rejections, taxonomy, staging_root) -> tuple[Upload, list[Rejection]]` (commits; audit `upload.created`; raises `UploadError(message, rejections)` and rolls back when nothing was accepted), `list_items(db, upload_id)`, `published_document_ids(db, item_ids) -> dict[item_id, document_id]`, `my_tasks(db, user) -> list[tuple[UploadItem, Project]]`, `may_act_on_item(upload, role, user) -> bool`, `confirm_type(db, item, *, doc_type_key, taxonomy, actor, project_id)`, `retry_item(db, item, *, actor, project_id)`, `ItemStateError(message)`, `NO_CHANGE_REASON`.
  - `UploadItem.staging_path` is relative to `STAGING_ROOT`: `<upload_id>/incoming/<hex>.<ext>` for direct files, `<upload_id>/items/<hex>.<ext>` for zip entries.

- [ ] **Step 1: Write the failing tests**

`backend/tests/ingestion/test_upload_service.py`:

```python
"""Intake service: staging, zip expansion, item specs and the rules applied when items are
created (forced visibility for clients, version targets, early no-change rejection)."""

import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Document, DocumentVersion, Upload, UploadItem
from app.ingestion.intake import IntakeLimits
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services.uploads import (
    IncomingFile,
    UploadError,
    create_upload,
    stage_files,
    staging_dir_for,
)
from tests.factories import make_project, make_user
from tests.helpers.files import docx_bytes, make_zip

LIMITS = IntakeLimits.from_megabytes(1, 2)
SRS = docx_bytes(["The system shall allow users to log in."])


def _reader(data: bytes):  # type: ignore[no-untyped-def]
    view = memoryview(data)
    position = 0

    async def read(size: int) -> bytes:
        nonlocal position
        chunk = bytes(view[position : position + size])
        position += size
        return chunk

    return read


async def test_stage_files_expands_zip_and_keeps_entry_titles_open(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "export.zip", {"a/Glossary.md": b"# G", "a/Cases.csv": b"id\n1"})
    staged, rejections = await stage_files(
        [
            IncomingFile("SRS final.docx", _reader(SRS)),
            IncomingFile("export.zip", _reader(archive.read_bytes())),
            IncomingFile("notes.exe", _reader(b"x")),
            IncomingFile("v2.zip", _reader(archive.read_bytes())),
        ],
        [
            UploadItemSpec(doc_type="srs", title="Custom title"),
            UploadItemSpec(doc_type="glossary", title="Should not apply to entries"),
            UploadItemSpec(doc_type="srs"),
            UploadItemSpec(doc_type="srs", intent="version", target_document_id=uuid.uuid4()),
        ],
        staging_dir=tmp_path / "staging" / "u1",
        limits=LIMITS,
    )
    assert [(s.file.name, s.spec.title) for s in staged] == [
        ("SRS final.docx", "Custom title"),
        ("Glossary.md", None),
        ("Cases.csv", None),
    ]
    assert all(
        s.file.path.is_file() and s.file.path.is_relative_to(tmp_path / "staging") for s in staged
    )
    assert [r.name for r in rejections] == ["notes.exe", "v2.zip"]
    assert rejections[1].reason == "Zip archives cannot be uploaded as a new version."


async def test_create_upload_rules(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, staging_root: Path
) -> None:
    owner = await make_user(db, settings)
    client_user = await make_user(db, settings, email="c@client.com", account_type="customer")
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    other_project = await make_project(db, settings, taxonomy, owner=owner, name="Other")
    internal_doc = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        current_version=1,
        created_by=owner.id,
    )
    foreign_doc = Document(
        project_id=other_project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        current_version=1,
        created_by=owner.id,
    )
    db.add_all([internal_doc, foreign_doc])
    await db.flush()
    db.add(
        DocumentVersion(
            document_id=internal_doc.id,
            version=1,
            sha256=hashlib.sha256(SRS).hexdigest(),
            original_path="02-requirements/srs--srs.docx",
            original_storage_version="1",
            markdown_path="02-requirements/srs--srs.md",
            markdown_storage_version="1",
            markdown_text="# SRS",
            uploaded_by=owner.id,
        )
    )
    await db.commit()
    upload_id = uuid.uuid4()
    files = [
        IncomingFile("brd.docx", _reader(SRS)),
        IncomingFile("poem.docx", _reader(SRS)),
        IncomingFile("no-target.docx", _reader(SRS)),
        IncomingFile("foreign.docx", _reader(SRS)),
        IncomingFile("same-bytes.docx", _reader(SRS)),
        IncomingFile("hidden-target.docx", _reader(SRS)),
    ]
    specs = [
        UploadItemSpec(doc_type="brd", visibility="internal"),
        UploadItemSpec(doc_type="poem"),
        UploadItemSpec(doc_type="srs", intent="version"),
        UploadItemSpec(doc_type="srs", intent="version", target_document_id=foreign_doc.id),
        UploadItemSpec(doc_type="srs", intent="version", target_document_id=internal_doc.id),
        UploadItemSpec(doc_type="srs", intent="version", target_document_id=internal_doc.id),
    ]
    staged, rejections = await stage_files(
        files[:5] + files[5:],
        specs,
        staging_dir=staging_dir_for(staging_root, upload_id),
        limits=LIMITS,
    )
    assert rejections == []
    # the client uploads: visibility forced to shared, internal target hidden (404-style)
    upload, rejected = await create_upload(
        db,
        project=project,
        uploader=client_user,
        role="client",
        upload_id=upload_id,
        staged=staged,
        rejections=rejections,
        taxonomy=taxonomy,
        staging_root=staging_root,
    )
    reasons = {r.name: r.reason for r in rejected}
    assert reasons["poem.docx"] == "Unknown document type 'poem'."
    assert reasons["no-target.docx"] == "A target document is required for a new version."
    assert reasons["foreign.docx"] == "Target document not found."
    assert reasons["same-bytes.docx"] == "Target document not found."  # internal doc, client
    assert reasons["hidden-target.docx"] == "Target document not found."
    items = (await db.scalars(select(UploadItem).where(UploadItem.upload_id == upload.id))).all()
    assert [i.original_name for i in items] == ["brd.docx"]
    assert items[0].visibility == "shared" and items[0].title == "brd"
    assert items[0].staging_path.startswith(f"{upload_id}/incoming/")
    assert (staging_root / items[0].staging_path).is_file()


async def test_create_upload_no_change_for_internal_user_and_all_rejected(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, staging_root: Path
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    document = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        current_version=1,
        created_by=owner.id,
    )
    db.add(document)
    await db.flush()
    db.add(
        DocumentVersion(
            document_id=document.id,
            version=1,
            sha256=hashlib.sha256(SRS).hexdigest(),
            original_path="02-requirements/srs--srs.docx",
            original_storage_version="1",
            markdown_path="02-requirements/srs--srs.md",
            markdown_storage_version="1",
            markdown_text="# SRS",
            uploaded_by=owner.id,
        )
    )
    await db.commit()
    upload_id = uuid.uuid4()
    staged, rejections = await stage_files(
        [IncomingFile("same.docx", _reader(SRS))],
        [UploadItemSpec(doc_type="srs", intent="version", target_document_id=document.id)],
        staging_dir=staging_dir_for(staging_root, upload_id),
        limits=LIMITS,
    )
    with pytest.raises(UploadError) as excinfo:
        await create_upload(
            db,
            project=project,
            uploader=owner,
            role="owner",
            upload_id=upload_id,
            staged=staged,
            rejections=rejections,
            taxonomy=taxonomy,
            staging_root=staging_root,
        )
    assert excinfo.value.message == "No files were accepted."
    assert [r.reason for r in excinfo.value.rejections] == [
        "No change: this file is identical to the current version."
    ]
    assert (await db.scalars(select(Upload))).all() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_upload_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.uploads'`.

- [ ] **Step 3: Implement schemas and service**

`backend/app/schemas/uploads.py`:

```python
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UploadItemSpec(BaseModel):
    """Per-file metadata sent in the ``items`` JSON part, in the same order as ``files``."""

    model_config = ConfigDict(extra="forbid")

    doc_type: str = Field(min_length=1, max_length=80)
    title: str | None = Field(default=None, max_length=200)
    intent: Literal["new", "version"] = "new"
    target_document_id: uuid.UUID | None = None
    visibility: Literal["internal", "shared"] = "internal"

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class RejectionOut(BaseModel):
    name: str
    reason: str


class UploadItemOut(BaseModel):
    id: uuid.UUID
    upload_id: uuid.UUID
    original_name: str
    ext: str
    size: int
    sha256: str
    selected_doc_type: str
    final_doc_type: str | None
    title: str
    intent: str
    target_document_id: uuid.UUID | None
    visibility: str
    status: str
    type_check: str | None
    check_explanation: str | None
    suggested_doc_type: str | None
    version_hint_document_id: uuid.UUID | None
    warnings: list[str]
    conversion_meta: dict[str, Any]
    error: str | None
    document_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class UploadOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    uploaded_by: uuid.UUID
    created_at: datetime
    items: list[UploadItemOut]
    rejected: list[RejectionOut]


class TaskOut(BaseModel):
    item: UploadItemOut
    project_id: uuid.UUID
    project_name: str


class ConfirmTypeRequest(BaseModel):
    doc_type: str = Field(min_length=1, max_length=80)
```

`backend/app/services/uploads.py`:

```python
"""Upload intake into staging and the database, plus item actions (confirm type, retry)."""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentVersion, Project, Upload, UploadItem, User
from app.ingestion.intake import (
    IntakeLimits,
    ReadChunk,
    Rejection,
    StagedFile,
    batch_limit_reason,
    expand_zip,
    extension_rejection,
    file_extension,
    sanitize_filename,
    size_limit_reason,
    stage_stream,
)
from app.ingestion.naming import title_from_filename
from app.ingestion.taxonomy import Taxonomy, UnknownDocType
from app.schemas.uploads import UploadItemSpec
from app.services import audit

NO_CHANGE_REASON = "No change: this file is identical to the current version."


class UploadError(Exception):
    def __init__(self, message: str, rejections: Sequence[Rejection] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.rejections = list(rejections)


class ItemStateError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class IncomingFile:
    name: str
    read: ReadChunk


@dataclass(frozen=True)
class StagedItem:
    file: StagedFile
    spec: UploadItemSpec


def staging_dir_for(staging_root: Path, upload_id: uuid.UUID) -> Path:
    return staging_root / str(upload_id)


async def stage_files(
    files: Sequence[IncomingFile],
    specs: Sequence[UploadItemSpec],
    *,
    staging_dir: Path,
    limits: IntakeLimits,
) -> tuple[list[StagedItem], list[Rejection]]:
    """Stream every file into ``staging_dir`` and expand zip archives. Zip entries inherit the
    archive's spec except the title, which defaults to the entry's file name."""
    staged: list[StagedItem] = []
    rejections: list[Rejection] = []
    total = 0
    for incoming, spec in zip(files, specs, strict=True):
        name = sanitize_filename(incoming.name)
        rejection = extension_rejection(name)
        if rejection is not None:
            rejections.append(rejection)
            continue
        ext = file_extension(name) or ""
        dest = staging_dir / "incoming" / f"{uuid.uuid4().hex}.{ext}"
        result = await stage_stream(incoming.read, dest, max_bytes=limits.max_file_bytes)
        if result is None:
            rejections.append(Rejection(name, size_limit_reason(limits)))
            continue
        size, sha256 = result
        total += size
        if total > limits.max_batch_bytes:
            await asyncio.to_thread(dest.unlink, missing_ok=True)
            rejections.append(Rejection(name, batch_limit_reason(limits)))
            continue
        file = StagedFile(name=name, ext=ext, path=dest, size=size, sha256=sha256)
        if ext != "zip":
            staged.append(StagedItem(file=file, spec=spec))
            continue
        if spec.intent == "version":
            rejections.append(Rejection(name, "Zip archives cannot be uploaded as a new version."))
            continue
        entries, zip_rejections = await asyncio.to_thread(
            expand_zip, file, staging_dir / "items", limits
        )
        rejections.extend(zip_rejections)
        entry_spec = spec.model_copy(update={"title": None})
        staged.extend(StagedItem(file=entry, spec=entry_spec) for entry in entries)
    return staged, rejections


async def _version_target_rejection(
    db: AsyncSession, project: Project, role: str, item: StagedItem
) -> Rejection | None:
    spec = item.spec
    if spec.target_document_id is None:
        return Rejection(item.file.name, "A target document is required for a new version.")
    target = await db.get(Document, spec.target_document_id)
    hidden = target is None or target.project_id != project.id or target.is_stub
    if hidden or (role == "client" and target is not None and target.visibility != "shared"):
        return Rejection(item.file.name, "Target document not found.")
    assert target is not None  # noqa: S101 - narrowed above for the type checker
    if target.doc_type != spec.doc_type:
        return Rejection(
            item.file.name,
            "The new version must have the same document type as the existing document.",
        )
    current = await db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == target.id,
            DocumentVersion.version == target.current_version,
        )
    )
    if current is not None and current.sha256 == item.file.sha256:
        return Rejection(item.file.name, NO_CHANGE_REASON)
    return None


async def create_upload(
    db: AsyncSession,
    *,
    project: Project,
    uploader: User,
    role: str,
    upload_id: uuid.UUID,
    staged: Sequence[StagedItem],
    rejections: Sequence[Rejection],
    taxonomy: Taxonomy,
    staging_root: Path,
) -> tuple[Upload, list[Rejection]]:
    """Create the upload and one item per accepted file. Client uploads are forced to
    ``shared``. Raises ``UploadError`` when no file was accepted."""
    all_rejections = list(rejections)
    upload = Upload(id=upload_id, project_id=project.id, uploaded_by=uploader.id)
    db.add(upload)
    await db.flush()
    accepted = 0
    for item in staged:
        spec = item.spec
        try:
            doc_type = taxonomy.resolve(spec.doc_type)
        except UnknownDocType:
            all_rejections.append(
                Rejection(item.file.name, f"Unknown document type {spec.doc_type!r}.")
            )
            continue
        if spec.intent == "version":
            rejection = await _version_target_rejection(db, project, role, item)
            if rejection is not None:
                all_rejections.append(rejection)
                continue
        db.add(
            UploadItem(
                upload_id=upload.id,
                original_name=item.file.name,
                ext=item.file.ext,
                size=item.file.size,
                sha256=item.file.sha256,
                staging_path=item.file.path.relative_to(staging_root).as_posix(),
                selected_doc_type=doc_type.key,
                title=(spec.title or title_from_filename(item.file.name))[:200],
                intent=spec.intent,
                target_document_id=spec.target_document_id if spec.intent == "version" else None,
                visibility="shared" if role == "client" else spec.visibility,
                status="uploaded",
            )
        )
        accepted += 1
    if accepted == 0:
        await db.rollback()
        raise UploadError("No files were accepted.", all_rejections)
    await audit.record(
        db,
        "upload.created",
        user_id=uploader.id,
        project_id=project.id,
        target_type="upload",
        target_id=str(upload.id),
        details={"items": accepted, "rejected": len(all_rejections)},
    )
    await db.commit()
    return upload, all_rejections


async def list_items(db: AsyncSession, upload_id: uuid.UUID) -> list[UploadItem]:
    return list(
        (
            await db.scalars(
                select(UploadItem)
                .where(UploadItem.upload_id == upload_id)
                .order_by(UploadItem.created_at, UploadItem.original_name)
            )
        ).all()
    )


async def published_document_ids(
    db: AsyncSession, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    if not item_ids:
        return {}
    rows = (
        await db.execute(
            select(DocumentVersion.upload_item_id, DocumentVersion.document_id).where(
                DocumentVersion.upload_item_id.in_(list(item_ids))
            )
        )
    ).all()
    return {item_id: document_id for item_id, document_id in rows if item_id is not None}


async def my_tasks(db: AsyncSession, user: User) -> list[tuple[UploadItem, Project]]:
    rows = (
        await db.execute(
            select(UploadItem, Project)
            .join(Upload, Upload.id == UploadItem.upload_id)
            .join(Project, Project.id == Upload.project_id)
            .where(
                Upload.uploaded_by == user.id,
                UploadItem.status == "needs_confirmation",
                Project.archived_at.is_(None),
            )
            .order_by(UploadItem.updated_at)
        )
    ).all()
    return [(item, project) for item, project in rows]


def may_act_on_item(upload: Upload, role: str, user: User) -> bool:
    return upload.uploaded_by == user.id or role == "owner"


async def confirm_type(
    db: AsyncSession,
    item: UploadItem,
    *,
    doc_type_key: str,
    taxonomy: Taxonomy,
    actor: User,
    project_id: uuid.UUID,
) -> None:
    if item.status != "needs_confirmation":
        raise ItemStateError("This item is not waiting for a type confirmation.")
    try:
        doc_type = taxonomy.resolve(doc_type_key)
    except UnknownDocType:
        raise ItemStateError(f"Unknown document type {doc_type_key!r}.") from None
    item.final_doc_type = doc_type.key
    item.type_check = (
        "mismatch_kept" if doc_type.key == item.selected_doc_type else "mismatch_changed"
    )
    item.status = "publishing"
    item.updated_at = datetime.now(UTC)
    await audit.record(
        db,
        "upload_item.type_confirmed",
        user_id=actor.id,
        project_id=project_id,
        target_type="upload_item",
        target_id=str(item.id),
        details={"selected": item.selected_doc_type, "final": doc_type.key},
    )
    await db.commit()


async def retry_item(
    db: AsyncSession, item: UploadItem, *, actor: User, project_id: uuid.UUID
) -> None:
    if item.status != "failed":
        raise ItemStateError("Only failed items can be retried.")
    item.status = "uploaded"
    item.error = None
    item.updated_at = datetime.now(UTC)
    await audit.record(
        db,
        "upload_item.retried",
        user_id=actor.id,
        project_id=project_id,
        target_type="upload_item",
        target_id=str(item.id),
    )
    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_upload_service.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app/schemas/uploads.py backend/app/services/uploads.py backend/tests/ingestion/test_upload_service.py
git commit -m "feat(backend): add upload intake service"
```

---

### Task 11: Deterministic publish and the per-item pipeline

**Files:**
- Create: `backend/app/services/publish.py`, `backend/app/services/pipeline.py`, `backend/tests/helpers/ingest.py`
- Test: `backend/tests/ingestion/test_publish.py`, `backend/tests/ingestion/test_pipeline.py`

**Interfaces:**
- Consumes: converters (Task 7), uploads service (Task 10), workspace (Task 6), naming (Task 4), storage (Task 3), analyzer (Task 9), `get_sessionmaker` (Plan 1).
- Produces:
  - `app.services.publish`: `publish_item(db, *, item, upload, project, uploader, backend, taxonomy, staging_root, now=None) -> DocumentVersion` (no commit; acquires the project advisory lock; idempotent), `NoChange`, `PublishError(message)`, `acquire_project_lock(db, project_id)`, `project_lock_key(project_id) -> int`, `content_type_for(ext)`, `CONTENT_TYPES`, `MARKDOWN_SUFFIX = ".md"` (converted text is staged next to the original as `<staging_path>.md`).
  - `app.services.pipeline`: `PipelineContext(settings, taxonomy, analyzer)` with `.staging_root`, `async transition(db, item_id, from_statuses, to_status, **values) -> bool` (no commit), `async convert_item(ctx, maker, item_id) -> bool`, `async check_items(ctx, maker, upload_id, item_ids) -> list[item_id]`, `async publish_item_by_id(ctx, maker, item_id)`, `async run_upload(ctx, upload_id, item_ids=None)`, `async publish_confirmed_item(ctx, item_id)`, `async requeue_stale_items(ctx) -> int`; constants `ACTIVE_STATUSES`, `NO_CHANGE_ERROR`, `LOW_TEXT_EXPLANATION`, `CHECK_FAILED_EXPLANATION`.
  - State machine: `uploaded → converting → checking → publishing → published`; `checking → needs_confirmation` on `mismatch`; `failed` from `converting` (conversion error, missing staged file) or `publishing` (no change, storage/publish error); low-text items and analyzer failures set `type_check = skipped` and publish; a confirmation sets `publishing` and `publish_confirmed_item` finishes it.
  - `tests.helpers.ingest`: `bytes_reader(data)`, `pipeline_context(settings, taxonomy, analyzer=None)`, `async ingest(db, settings, taxonomy, *, project, uploader, role, files, specs, analyzer=None, run=True) -> (Upload, list[UploadItem], list[Rejection])`.

- [ ] **Step 1: Test helper and failing tests**

`backend/tests/helpers/ingest.py`:

```python
"""Run the real intake + pipeline from tests without HTTP: stage bytes, create the upload and
run ``run_upload`` with the given analyzer (SkipAnalyzer by default)."""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.analyzer import Analyzer, SkipAnalyzer
from app.core.config import Settings
from app.db.models import Project, Upload, UploadItem, User
from app.ingestion.intake import IntakeLimits, Rejection
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services.pipeline import PipelineContext, run_upload
from app.services.uploads import (
    IncomingFile,
    create_upload,
    list_items,
    stage_files,
    staging_dir_for,
)


def bytes_reader(data: bytes):  # type: ignore[no-untyped-def]
    view = memoryview(data)
    position = 0

    async def read(size: int) -> bytes:
        nonlocal position
        chunk = bytes(view[position : position + size])
        position += size
        return chunk

    return read


def pipeline_context(
    settings: Settings, taxonomy: Taxonomy, analyzer: Analyzer | None = None
) -> PipelineContext:
    return PipelineContext(
        settings=settings, taxonomy=taxonomy, analyzer=analyzer or SkipAnalyzer()
    )


async def ingest(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    *,
    project: Project,
    uploader: User,
    role: str,
    files: Sequence[tuple[str, bytes]],
    specs: Sequence[UploadItemSpec],
    analyzer: Analyzer | None = None,
    run: bool = True,
) -> tuple[Upload, list[UploadItem], list[Rejection]]:
    ctx = pipeline_context(settings, taxonomy, analyzer)
    upload_id = uuid.uuid4()
    limits = IntakeLimits.from_megabytes(settings.max_upload_file_mb, settings.max_upload_batch_mb)
    staged, rejections = await stage_files(
        [IncomingFile(name=name, read=bytes_reader(data)) for name, data in files],
        specs,
        staging_dir=staging_dir_for(ctx.staging_root, upload_id),
        limits=limits,
    )
    upload, rejected = await create_upload(
        db,
        project=project,
        uploader=uploader,
        role=role,
        upload_id=upload_id,
        staged=staged,
        rejections=rejections,
        taxonomy=taxonomy,
        staging_root=ctx.staging_root,
    )
    if run:
        await run_upload(ctx, upload.id)
    db.expire_all()
    return upload, await list_items(db, upload.id), rejected
```

`backend/tests/ingestion/test_publish.py`:

```python
"""Publish rules at the service level: naming, frontmatter, versions, no-change, stub removal,
reports, idempotency. Files go through the real intake and pipeline with the SkipAnalyzer."""

import asyncio
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, Document, DocumentVersion, Project, UploadItem, User
from app.db.session import get_sessionmaker
from app.ingestion.naming import split_frontmatter
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services.pipeline import publish_item_by_id, run_upload
from app.services.uploads import list_items
from tests.factories import make_project, make_user
from tests.helpers.files import docx_bytes
from tests.helpers.ingest import ingest, pipeline_context

SRS_V1 = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
SRS_V2 = docx_bytes(
    ["The system shall allow users to log in with a password, a one-time code and MFA."]
)


async def _setup(db: AsyncSession, settings: Settings, taxonomy: Taxonomy) -> tuple[User, Project]:
    owner = await make_user(db, settings, display_name="Nguyen Van A")
    return owner, await make_project(db, settings, taxonomy, owner=owner, name="Demo")


async def test_new_document_is_published_with_naming_and_frontmatter(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, rejected = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("Customer Portal SRS.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    assert rejected == [] and [i.status for i in items] == ["published"]
    assert items[0].type_check == "skipped" and items[0].title == "Customer Portal SRS"
    document = (
        await db.scalars(
            select(Document).where(Document.doc_type == "srs", Document.is_stub.is_(False))
        )
    ).one()
    assert document.slug == "customer-portal-srs" and document.current_version == 1
    version = (
        await db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id))
    ).one()
    assert version.original_path == "02-requirements/srs--customer-portal-srs.docx"
    assert version.markdown_path == "02-requirements/srs--customer-portal-srs.md"
    assert version.sha256 == hashlib.sha256(SRS_V1).hexdigest()
    assert version.upload_item_id == items[0].id
    root = storage_root / "demo"
    assert (root / version.original_path).read_bytes() == SRS_V1
    markdown = (root / version.markdown_path).read_text()
    frontmatter, body = split_frontmatter(markdown)
    assert frontmatter["qc_agent"] == 2 and frontmatter["document_id"] == str(document.id)
    assert frontmatter["doc_type"] == "srs" and frontmatter["folder"] == "02-requirements"
    assert frontmatter["uploaded_by"] == "Nguyen Van A" and frontmatter["type_check"] == "skipped"
    assert frontmatter["source_sha256"] == version.sha256 and frontmatter["language"] == "en"
    assert "one-time code" in body and version.markdown_text == markdown
    # the SRS stub is gone, the gap report says present
    assert not (root / "02-requirements/srs.md").exists()
    assert (root / ".trash/02-requirements/srs.md").exists()
    stubs = (await db.scalars(select(Document).where(Document.is_stub.is_(True)))).all()
    assert len(stubs) == 9
    report = json.loads((root / "_reports/gap-report.json").read_text())
    assert report["required_present"] == 1
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "upload.created" in actions and "upload_item.published" in actions


async def test_new_version_overwrites_paths_and_identical_file_is_no_change(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs", title="Portal SRS")],
    )
    document = (await db.scalars(select(Document).where(Document.slug == "portal-srs"))).one()
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs-v2.docx", SRS_V2)],
        specs=[UploadItemSpec(doc_type="srs", intent="version", target_document_id=document.id)],
    )
    assert items[0].status == "published"
    await db.refresh(document)
    assert document.current_version == 2
    versions = (
        await db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version)
        )
    ).all()
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].original_path == versions[1].original_path
    assert versions[0].original_storage_version != versions[1].original_storage_version
    root = storage_root / "demo"
    assert (root / versions[1].original_path).read_bytes() == SRS_V2
    assert (
        root / ".versions" / versions[0].original_path / versions[0].original_storage_version
    ).read_bytes() == SRS_V1
    # identical bytes again: rejected early at intake
    _, items, rejected = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("same.docx", SRS_V2), ("notes.md", b"# Notes\n")],
        specs=[
            UploadItemSpec(doc_type="srs", intent="version", target_document_id=document.id),
            UploadItemSpec(doc_type="overview/other"),
        ],
    )
    assert [r.reason for r in rejected] == [
        "No change: this file is identical to the current version."
    ]
    assert [i.original_name for i in items] == ["notes.md"]
    await db.refresh(document)
    assert document.current_version == 2


async def test_slug_collision_other_type_and_multi_subdir(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("a.md", b"# ADR 1\n"), ("b.md", b"# ADR 1 again\n"), ("notes.txt", b"free text\n")],
        specs=[
            UploadItemSpec(doc_type="adr", title="Use PostgreSQL"),
            UploadItemSpec(doc_type="adr", title="Use PostgreSQL"),
            UploadItemSpec(doc_type="design/other", title="Whiteboard notes"),
        ],
    )
    assert [i.status for i in items] == ["published"] * 3
    paths = sorted(
        str(p.relative_to(storage_root / "demo"))
        for p in (storage_root / "demo").rglob("*--*")
        if p.is_file()
    )
    assert paths == [
        "03-design/other--whiteboard-notes.md",
        "03-design/other--whiteboard-notes.txt",
        "04-source/adr/adr--use-postgresql-2.md",
        "04-source/adr/adr--use-postgresql.md",
    ]


async def test_edited_stub_is_kept(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    stub = storage_root / "demo/06-deployment/runbook.md"
    stub.write_text(stub.read_text() + "\nSomeone started writing here.\n")
    await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("runbook.md", b"# Runbook\n\nRestart the service.\n")],
        specs=[UploadItemSpec(doc_type="runbook")],
    )
    assert stub.exists() and "Someone started writing here." in stub.read_text()
    runbooks = (await db.scalars(select(Document).where(Document.doc_type == "runbook"))).all()
    assert {d.is_stub for d in runbooks} == {True, False}


async def test_publish_is_idempotent_on_retry(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS_V1)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    item = items[0]
    item.status = "publishing"  # as if the process died after committing the version row
    await db.commit()
    await publish_item_by_id(pipeline_context(settings, taxonomy), get_sessionmaker(), item.id)
    db.expire_all()
    refreshed = await db.get_one(UploadItem, item.id)
    assert refreshed.status == "published"
    versions = (
        await db.scalars(select(DocumentVersion).where(DocumentVersion.upload_item_id == item.id))
    ).all()
    assert len(versions) == 1


async def test_title_equal_to_type_name_does_not_collide_with_stub(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("Readme.md", b"# Project\n\nWhat it does.\n")],
        specs=[UploadItemSpec(doc_type="readme")],
    )
    assert items[0].status == "published" and items[0].title == "Readme"
    document = (
        await db.scalars(select(Document).where(Document.doc_type == "readme"))
    ).one()  # the stub row is gone, only the real document remains
    assert document.slug == "readme" and document.is_stub is False
    assert (storage_root / "demo/01-overview/readme--readme.md").exists()
    assert not (storage_root / "demo/01-overview/readme.md").exists()


async def test_concurrent_publishes_in_one_project_get_distinct_slugs(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner, project = await _setup(db, settings, taxonomy)
    ctx = pipeline_context(settings, taxonomy)
    uploads = []
    for data in (SRS_V1, SRS_V2):
        upload, _, _ = await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=owner,
            role="owner",
            files=[("srs.docx", data)],
            specs=[UploadItemSpec(doc_type="srs", title="Portal SRS")],
            run=False,
        )
        uploads.append(upload)
    await asyncio.gather(*(run_upload(ctx, upload.id) for upload in uploads))
    db.expire_all()
    documents = (
        await db.scalars(
            select(Document).where(Document.doc_type == "srs", Document.is_stub.is_(False))
        )
    ).all()
    assert sorted(d.slug for d in documents) == ["portal-srs", "portal-srs-2"]
    statuses = [i.status for u in uploads for i in await list_items(db, u.id)]
    assert statuses == ["published", "published"]
```

`backend/tests/ingestion/test_pipeline.py`:

```python
"""The per-item state machine with a scripted analyzer."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import Document, UploadItem
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services.pipeline import publish_confirmed_item, requeue_stale_items
from app.services.uploads import confirm_type
from tests.factories import make_project, make_user
from tests.helpers.files import docx_bytes, pdf_bytes
from tests.helpers.ingest import ingest, pipeline_context

PLAN = docx_bytes(
    ["Scope of testing: login, upload and publish flows. Entry criteria: build green."]
)
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])


async def test_match_publishes_and_mismatch_waits_for_confirmation(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    fake = FakeAnalyzer(
        {"plan.docx": ScriptedVerdict("mismatch", "This reads like a test plan.", "test-plan")}
    )
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS), ("plan.docx", PLAN)],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="srs", title="Plan")],
        analyzer=fake,
    )
    by_name = {i.original_name: i for i in items}
    assert by_name["srs.docx"].status == "published" and by_name["srs.docx"].type_check == "match"
    waiting = by_name["plan.docx"]
    assert waiting.status == "needs_confirmation"
    assert waiting.check_explanation == "This reads like a test plan."
    assert waiting.suggested_doc_type == "test-plan"
    assert len(fake.batches) == 1 and len(fake.batches[0].items) == 2
    previews = {i.file_name: i.preview for i in fake.batches[0].items}
    assert previews["srs.docx"].startswith("The system shall")
    # the uploader changes the type; the item publishes into 05-testing
    await confirm_type(
        db, waiting, doc_type_key="test-plan", taxonomy=taxonomy, actor=owner, project_id=project.id
    )
    await publish_confirmed_item(pipeline_context(settings, taxonomy, fake), waiting.id)
    db.expire_all()
    done = await db.get_one(UploadItem, waiting.id)
    assert done.status == "published" and done.type_check == "mismatch_changed"
    assert done.final_doc_type == "test-plan"
    assert (storage_root / "demo/05-testing/test-plan--plan.docx").exists()
    frontmatter = (storage_root / "demo/05-testing/test-plan--plan.md").read_text()
    assert (
        "type_selected_by_user: srs" in frontmatter
        and "type_check: mismatch_changed" in frontmatter
    )


async def test_keeping_the_type_records_mismatch_kept(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Looks wrong.", "test-plan")})
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("plan.docx", PLAN)],
        specs=[UploadItemSpec(doc_type="srs")],
        analyzer=fake,
    )
    await confirm_type(
        db, items[0], doc_type_key="srs", taxonomy=taxonomy, actor=owner, project_id=project.id
    )
    await publish_confirmed_item(pipeline_context(settings, taxonomy, fake), items[0].id)
    db.expire_all()
    done = await db.get_one(UploadItem, items[0].id)
    assert done.status == "published" and done.type_check == "mismatch_kept"


async def test_analyzer_failure_and_low_text_skip_the_check(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS), ("scan.pdf", pdf_bytes(["", ""]))],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="deploy-guide")],
        analyzer=FakeAnalyzer(error=RuntimeError("agent down")),
    )
    by_name = {i.original_name: i for i in items}
    assert by_name["srs.docx"].status == "published" and by_name["srs.docx"].type_check == "skipped"
    assert (
        by_name["srs.docx"].check_explanation
        == "The type check could not run; the selected type was kept."
    )
    scan = by_name["scan.pdf"]
    assert scan.status == "published" and scan.type_check == "skipped"
    assert "low_text" in scan.conversion_meta["warnings"]


async def test_conversion_failure_marks_item_failed_with_reason(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    _, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("broken.docx", b"not really a docx")],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    assert items[0].status == "failed"
    assert items[0].error == "File content does not match its extension."
    assert (await db.scalars(select(Document).where(Document.is_stub.is_(False)))).all() == []


async def test_requeue_restarts_items_left_in_progress(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, taxonomy: Taxonomy
) -> None:
    import asyncio

    async with db_sessionmaker() as db:
        owner = await make_user(db, settings)
        project = await make_project(db, settings, taxonomy, owner=owner)
        _, items, _ = await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=owner,
            role="owner",
            files=[("srs.docx", SRS)],
            specs=[UploadItemSpec(doc_type="srs")],
            run=False,
        )
        items[0].status = "converting"  # as if the process died mid-conversion
        await db.commit()
        item_id = items[0].id
    count = await requeue_stale_items(pipeline_context(settings, taxonomy))
    assert count == 1
    await asyncio.sleep(0)
    for _ in range(100):
        async with db_sessionmaker() as db:
            item = await db.get_one(UploadItem, item_id)
            if item.status in ("published", "failed"):
                break
        await asyncio.sleep(0.05)
    assert item.status == "published"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_publish.py tests/ingestion/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.pipeline'`.

- [ ] **Step 3: Implement publish**

`backend/app/services/publish.py`:

```python
"""Deterministic publish of one upload item (spec 6.3 step 5, 5.4, 5.5, 6.4).

Runs under a PostgreSQL advisory lock per project. Writes the original and the converted
Markdown (with frontmatter) to storage, records storage version ids, creates or extends the
document, removes an unchanged stub, regenerates the reports. Idempotent: an item that already
has a document version is returned as-is.
"""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import BigInteger, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slugs import unique_slug
from app.db.models import Document, DocumentVersion, Project, Upload, UploadItem, User
from app.ingestion.naming import (
    Frontmatter,
    markdown_path,
    original_path,
    render_markdown_file,
    title_slug,
)
from app.ingestion.taxonomy import DocType, Taxonomy
from app.services.workspace import (
    ensure_workspace,
    is_provisioned,
    refresh_reports,
    sha256_hex,
)
from app.storage.base import StorageBackend, StorageNotFound

CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "txt": "text/plain",
    "html": "text/html",
    "csv": "text/csv",
}
MARKDOWN_SUFFIX = ".md"  # converted text sits next to the staged original: <staging_path>.md


class NoChange(Exception):
    """The uploaded file is byte-identical to the document's current version."""


class PublishError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def content_type_for(ext: str) -> str:
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def project_lock_key(project_id: uuid.UUID) -> int:
    digest = hashlib.sha256(project_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def acquire_project_lock(db: AsyncSession, project_id: uuid.UUID) -> None:
    """Transaction-scoped advisory lock; released automatically at commit or rollback."""
    await db.execute(
        select(func.pg_advisory_xact_lock(literal(project_lock_key(project_id), BigInteger)))
    )


async def _taken_slugs(db: AsyncSession, project_id: uuid.UUID, doc_type: DocType) -> set[str]:
    return set(
        (
            await db.scalars(
                select(Document.slug).where(
                    Document.project_id == project_id,
                    Document.doc_type == doc_type.key,
                    Document.is_stub.is_(False),
                )
            )
        ).all()
    )


async def _remove_unchanged_stub(
    db: AsyncSession, project: Project, doc_type: DocType, backend: StorageBackend
) -> None:
    row = (
        await db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(
                Document.project_id == project.id,
                Document.doc_type == doc_type.key,
                Document.is_stub.is_(True),
            )
        )
    ).first()
    if row is None:
        return
    stub, version = row
    try:
        current = await backend.get_file(version.markdown_path)
    except StorageNotFound:
        current = None
    if current is None or sha256_hex(current) == version.sha256:
        if current is not None:
            await backend.move_to_trash(version.markdown_path)
        await db.delete(stub)
        await db.flush()


async def publish_item(
    db: AsyncSession,
    *,
    item: UploadItem,
    upload: Upload,
    project: Project,
    uploader: User,
    backend: StorageBackend,
    taxonomy: Taxonomy,
    staging_root: Path,
    now: datetime | None = None,
) -> DocumentVersion:
    moment = now or datetime.now(UTC)
    existing = await db.scalar(
        select(DocumentVersion).where(DocumentVersion.upload_item_id == item.id)
    )
    if existing is not None:
        return existing
    await acquire_project_lock(db, project.id)
    if not is_provisioned(project):
        await ensure_workspace(
            db, project=project, backend=backend, taxonomy=taxonomy, actor=uploader, now=moment
        )
    doc_type = taxonomy.resolve(item.final_doc_type or item.selected_doc_type)
    staged = staging_root / item.staging_path
    try:
        data = await asyncio.to_thread(staged.read_bytes)
        markdown = await asyncio.to_thread(
            staged.with_name(staged.name + MARKDOWN_SUFFIX).read_text, encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise PublishError("Staged file is no longer available; upload the file again.") from exc

    if item.intent == "version":
        document = (
            await db.get(Document, item.target_document_id) if item.target_document_id else None
        )
        if document is None or document.project_id != project.id or document.is_stub:
            raise PublishError("Target document not found.")
        current = await db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.version == document.current_version,
            )
        )
        if current is not None and current.sha256 == item.sha256:
            raise NoChange()
        version = document.current_version + 1
    else:
        slug = unique_slug(title_slug(item.title), await _taken_slugs(db, project.id, doc_type))
        document = Document(
            project_id=project.id,
            folder_id=doc_type.folder_id,
            doc_type=doc_type.key,
            title=item.title,
            slug=slug,
            visibility=item.visibility,
            current_version=0,
            is_stub=False,
            created_by=uploader.id,
        )
        db.add(document)
        await db.flush()
        version = 1

    orig_path = original_path(doc_type, document.slug, item.ext)
    md_path = markdown_path(doc_type, document.slug)
    frontmatter = Frontmatter(
        document_id=str(document.id),
        version=version,
        doc_type=doc_type.id,
        folder=doc_type.folder_dir,
        title=document.title,
        kind="converted",
        source_file=PurePosixPath(orig_path).name,
        source_sha256=item.sha256,
        uploaded_by=uploader.display_name,
        uploaded_at=moment,
        type_selected_by_user=item.selected_doc_type,
        type_check=item.type_check or "skipped",
        language=item.conversion_meta.get("language"),
        visibility=document.visibility,
    )
    markdown_text = render_markdown_file(frontmatter, markdown)
    stored_original = await backend.put_file(orig_path, data, content_type_for(item.ext))
    stored_markdown = await backend.put_file(
        md_path, markdown_text.encode("utf-8"), "text/markdown"
    )
    document_version = DocumentVersion(
        document_id=document.id,
        version=version,
        sha256=item.sha256,
        original_path=orig_path,
        original_storage_version=stored_original.version_id,
        markdown_path=md_path,
        markdown_storage_version=stored_markdown.version_id,
        markdown_text=markdown_text,
        uploaded_by=uploader.id,
        upload_item_id=item.id,
    )
    db.add(document_version)
    document.current_version = version
    document.updated_at = moment
    await db.flush()
    await _remove_unchanged_stub(db, project, doc_type, backend)
    await refresh_reports(db, project=project, backend=backend, taxonomy=taxonomy, now=moment)
    return document_version
```

- [ ] **Step 4: Implement the pipeline**

`backend/app/services/pipeline.py`:

```python
"""Per-item state machine (spec 6.2): uploaded → converting → checking → (needs_confirmation)
→ publishing → published | failed. Runs as a FastAPI background task after the upload request
and from the confirm-type and retry endpoints; ``requeue_stale_items`` restarts work left in a
non-terminal state when the process starts."""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.analyzer import Analyzer, CheckBatch, CheckItem, ExistingDocument, ItemVerdict
from app.core.config import Settings
from app.db.models import Document, Project, Upload, UploadItem, User
from app.db.session import get_sessionmaker
from app.ingestion.converters import LOW_TEXT, ConversionError, convert_file
from app.ingestion.taxonomy import Taxonomy, UnknownDocType
from app.services import audit
from app.services.publish import MARKDOWN_SUFFIX, NoChange, PublishError, publish_item
from app.storage.base import StorageError
from app.storage.select import backend_for

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("uploaded", "converting", "checking", "publishing")
NO_CHANGE_ERROR = "No change: this file is identical to the current version."
LOW_TEXT_EXPLANATION = "The file has little extractable text; the type check was skipped."
CHECK_FAILED_EXPLANATION = "The type check could not run; the selected type was kept."
PREVIEW_CHARS = 2000
_background: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class PipelineContext:
    settings: Settings
    taxonomy: Taxonomy
    analyzer: Analyzer

    @property
    def staging_root(self) -> Path:
        return Path(self.settings.staging_root)


async def transition(
    db: AsyncSession,
    item_id: uuid.UUID,
    from_statuses: Sequence[str],
    to_status: str,
    **values: Any,
) -> bool:
    """Atomically move an item between states; False when it was not in ``from_statuses``."""
    moved = await db.scalar(
        update(UploadItem)
        .where(UploadItem.id == item_id, UploadItem.status.in_(list(from_statuses)))
        .values(status=to_status, updated_at=datetime.now(UTC), **values)
        .returning(UploadItem.id)
        .execution_options(synchronize_session=False)
    )
    return moved is not None


async def _fail(
    db: AsyncSession, item_id: uuid.UUID, project_id: uuid.UUID, from_status: str, error: str
) -> None:
    """Mark an item failed. Takes ids, not ORM objects: callers may have rolled back, which
    expires loaded attributes and would trigger implicit I/O on access."""
    await transition(db, item_id, (from_status,), "failed", error=error)
    await audit.record(
        db,
        "upload_item.failed",
        project_id=project_id,
        target_type="upload_item",
        target_id=str(item_id),
        details={"error": error},
    )
    await db.commit()


async def convert_item(
    ctx: PipelineContext, maker: async_sessionmaker[AsyncSession], item_id: uuid.UUID
) -> bool:
    async with maker() as db:
        if not await transition(db, item_id, ("uploaded",), "converting"):
            return False
        await db.commit()
        item = await db.get_one(UploadItem, item_id)
        upload = await db.get_one(Upload, item.upload_id)
        project_id = upload.project_id
        path = ctx.staging_root / item.staging_path
        try:
            result = await asyncio.to_thread(convert_file, path, item.ext)
            await asyncio.to_thread(
                path.with_name(path.name + MARKDOWN_SUFFIX).write_text,
                result.markdown,
                encoding="utf-8",
            )
        except ConversionError as exc:
            await _fail(db, item_id, project_id, "converting", exc.message)
            return False
        except FileNotFoundError:
            await _fail(
                db,
                item_id,
                project_id,
                "converting",
                "Staged file is no longer available; upload the file again.",
            )
            return False
        except Exception:
            logger.exception("Conversion crashed for upload item %s", item_id)
            await _fail(db, item_id, project_id, "converting", "Conversion failed unexpectedly.")
            return False
        meta = {**result.meta.to_dict(), "warnings": list(result.warnings)}
        await transition(db, item_id, ("converting",), "checking", conversion_meta=meta)
        await db.commit()
        return True


async def _preview(ctx: PipelineContext, item: UploadItem) -> str:
    path = ctx.staging_root / item.staging_path
    text = await asyncio.to_thread(
        path.with_name(path.name + MARKDOWN_SUFFIX).read_text, encoding="utf-8"
    )
    return text[:PREVIEW_CHARS]


async def _build_batch(
    ctx: PipelineContext, db: AsyncSession, project: Project, items: Sequence[UploadItem]
) -> CheckBatch:
    existing = (
        await db.scalars(
            select(Document).where(Document.project_id == project.id, Document.is_stub.is_(False))
        )
    ).all()
    check_items = [
        CheckItem(
            item_id=item.id,
            file_name=item.original_name,
            selected_doc_type=item.selected_doc_type,
            title=item.title,
            outline=list(item.conversion_meta.get("outline", [])),
            preview=await _preview(ctx, item),
            language=item.conversion_meta.get("language"),
        )
        for item in items
    ]
    return CheckBatch(
        project_id=project.id,
        items=check_items,
        allowed_doc_types=[t.key for t in ctx.taxonomy.doc_types],
        existing_documents=[
            ExistingDocument(document_id=d.id, doc_type=d.doc_type, title=d.title) for d in existing
        ],
    )


def _valid_hint(verdict: ItemVerdict | None, known: set[uuid.UUID]) -> uuid.UUID | None:
    if verdict is None or verdict.version_of_document_id not in known:
        return None
    return verdict.version_of_document_id


def _valid_suggestion(taxonomy: Taxonomy, key: str | None) -> str | None:
    if key is None:
        return None
    try:
        return taxonomy.resolve(key).key
    except UnknownDocType:
        return None


async def check_items(
    ctx: PipelineContext,
    maker: async_sessionmaker[AsyncSession],
    upload_id: uuid.UUID,
    item_ids: Sequence[uuid.UUID],
) -> list[uuid.UUID]:
    """Run the analyzer once for the batch; return the ids that may be published now."""
    if not item_ids:
        return []
    ready: list[uuid.UUID] = []
    async with maker() as db:
        upload = await db.get_one(Upload, upload_id)
        project = await db.get_one(Project, upload.project_id)
        items = list(
            (
                await db.scalars(
                    select(UploadItem).where(
                        UploadItem.id.in_(list(item_ids)), UploadItem.status == "checking"
                    )
                )
            ).all()
        )
        to_check: list[UploadItem] = []
        for item in items:
            if LOW_TEXT in item.conversion_meta.get("warnings", []):
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "publishing",
                    type_check="skipped",
                    check_explanation=LOW_TEXT_EXPLANATION,
                )
                ready.append(item.id)
            else:
                to_check.append(item)
        await db.commit()
        if not to_check:
            return ready
        batch = await _build_batch(ctx, db, project, to_check)
        verdicts: dict[uuid.UUID, ItemVerdict] = {}
        try:
            result = await ctx.analyzer.check(batch)
            verdicts = {v.item_id: v for v in result.verdicts}
        except Exception:
            logger.exception("Type check failed for upload %s", upload_id)
        known = {d.document_id for d in batch.existing_documents}
        for item in to_check:
            verdict = verdicts.get(item.id)
            hint = _valid_hint(verdict, known)
            if verdict is None or verdict.verdict == "skipped":
                explanation = verdict.explanation if verdict else CHECK_FAILED_EXPLANATION
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "publishing",
                    type_check="skipped",
                    check_explanation=explanation,
                    version_hint_document_id=hint,
                )
                ready.append(item.id)
            elif verdict.verdict == "match":
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "publishing",
                    type_check="match",
                    check_explanation=verdict.explanation,
                    version_hint_document_id=hint,
                )
                ready.append(item.id)
            else:
                await transition(
                    db,
                    item.id,
                    ("checking",),
                    "needs_confirmation",
                    check_explanation=verdict.explanation,
                    suggested_doc_type=_valid_suggestion(ctx.taxonomy, verdict.suggested_doc_type),
                    version_hint_document_id=hint,
                )
        await db.commit()
    return ready


async def publish_item_by_id(
    ctx: PipelineContext, maker: async_sessionmaker[AsyncSession], item_id: uuid.UUID
) -> None:
    async with maker() as db:
        item = await db.get_one(UploadItem, item_id)
        if item.status != "publishing":
            return
        upload = await db.get_one(Upload, item.upload_id)
        project = await db.get_one(Project, upload.project_id)
        uploader = await db.get_one(User, upload.uploaded_by)
        project_id, uploader_id = project.id, uploader.id
        try:
            backend = backend_for(project.storage, ctx.settings)
            version = await publish_item(
                db,
                item=item,
                upload=upload,
                project=project,
                uploader=uploader,
                backend=backend,
                taxonomy=ctx.taxonomy,
                staging_root=ctx.staging_root,
            )
        except NoChange:
            await db.rollback()
            await _fail(db, item_id, project_id, "publishing", NO_CHANGE_ERROR)
            return
        except (PublishError, StorageError) as exc:
            await db.rollback()
            await _fail(db, item_id, project_id, "publishing", str(exc))
            return
        except Exception:
            logger.exception("Publishing crashed for upload item %s", item_id)
            await db.rollback()
            await _fail(db, item_id, project_id, "publishing", "Publishing failed unexpectedly.")
            return
        await transition(db, item_id, ("publishing",), "published", error=None)
        await audit.record(
            db,
            "upload_item.published",
            user_id=uploader_id,
            project_id=project_id,
            target_type="document",
            target_id=str(version.document_id),
            details={"upload_item_id": str(item_id), "version": version.version},
        )
        await db.commit()


async def run_upload(
    ctx: PipelineContext, upload_id: uuid.UUID, item_ids: Sequence[uuid.UUID] | None = None
) -> None:
    """Convert, check and publish the ``uploaded`` items of one upload (or a subset)."""
    maker = get_sessionmaker()
    async with maker() as db:
        stmt = select(UploadItem.id).where(
            UploadItem.upload_id == upload_id, UploadItem.status == "uploaded"
        )
        if item_ids is not None:
            stmt = stmt.where(UploadItem.id.in_(list(item_ids)))
        pending = list((await db.scalars(stmt.order_by(UploadItem.created_at))).all())
    converted = [item_id for item_id in pending if await convert_item(ctx, maker, item_id)]
    for item_id in await check_items(ctx, maker, upload_id, converted):
        await publish_item_by_id(ctx, maker, item_id)


async def publish_confirmed_item(ctx: PipelineContext, item_id: uuid.UUID) -> None:
    await publish_item_by_id(ctx, get_sessionmaker(), item_id)


async def requeue_stale_items(ctx: PipelineContext) -> int:
    """Reset items left mid-flight by a previous process to ``uploaded`` and run them again."""
    maker = get_sessionmaker()
    async with maker() as db:
        rows = (
            await db.execute(
                update(UploadItem)
                .where(UploadItem.status.in_(list(ACTIVE_STATUSES)))
                .values(status="uploaded", updated_at=datetime.now(UTC))
                .returning(UploadItem.upload_id)
                .execution_options(synchronize_session=False)
            )
        ).all()
        await db.commit()
    upload_ids = {upload_id for (upload_id,) in rows}
    for upload_id in upload_ids:
        task = asyncio.create_task(run_upload(ctx, upload_id))
        _background.add(task)
        task.add_done_callback(_background.discard)
    return len(rows)
```

Why ids after `rollback()`: a rollback expires every loaded attribute; touching `item.id` afterwards would issue a lazy load outside an `await` and fail with `MissingGreenlet` under asyncpg. `_fail` therefore takes plain ids captured before the `try`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ingestion/test_publish.py tests/ingestion/test_pipeline.py -v`
Expected: `12 passed`.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app/services/publish.py backend/app/services/pipeline.py backend/tests/helpers/ingest.py backend/tests/ingestion/test_publish.py backend/tests/ingestion/test_pipeline.py
git commit -m "feat(backend): add publish and per-item pipeline"
```

---

### Task 12: Upload API with background pipeline and startup re-queue

**Files:**
- Create: `backend/app/api/routes/uploads.py`
- Modify: `backend/pyproject.toml` (`uv add python-multipart`), `backend/app/api/deps.py` (append `pipeline_dep`; replace the project-role block), `backend/app/main.py` (replace)
- Test: `backend/tests/api/test_uploads.py`

**Interfaces:**
- Consumes: uploads service and schemas (Task 10), pipeline (Task 11), `has_consent` (Task 6), `FakeAnalyzer` (Task 9).
- Produces:
  - `app.api.deps`: `pipeline_dep(request) -> PipelineContext`, alias `PipelineDep`; `async resolve_role(db, project, user) -> str | None` (None for archived projects and non-members, `owner` for admins); `require_project_role` now built on it; alias `Uploader = require_project_role("owner", "editor", "client")`.
  - Routes (`/api/v1`): `POST /projects/{project_id}/uploads` (multipart: `files` list + `items` JSON string with one `UploadItemSpec` per file in order; 201 `UploadOut`; 409 without consent; 422 when the items part is invalid or no file was accepted), `GET /uploads/{upload_id}` (members; clients only their own), `GET /me/tasks` (items in `needs_confirmation` uploaded by the caller), `POST /upload-items/{item_id}/confirm-type` and `POST /upload-items/{item_id}/retry` (uploader or project owner; 409 on wrong state).
  - `create_app` builds `app.state.pipeline = PipelineContext(settings, taxonomy, analyzer)`; the lifespan re-queues items left in `uploaded/converting/checking/publishing` (`requeue_stale_items`) after the engine is initialised. `app.state.analyzer` stays for tests.

- [ ] **Step 1: Dependency**

```bash
uv add python-multipart
```

Expected: `python-multipart>=0.0.32` in dependencies (FastAPI needs it for `File`/`Form`).

- [ ] **Step 2: Write the failing tests**

`backend/tests/api/test_uploads.py`:

```python
"""Upload API: multipart intake, per-file rejections, consent gate, role rules, polling,
My tasks, type confirmation and retry. Background tasks complete before ASGITransport returns
the response, so the pipeline has run by the time the test polls."""

import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import AuditLog, Document, Project, User
from app.ingestion.taxonomy import Taxonomy
from tests.factories import add_member, make_project, make_session_token, make_user
from tests.helpers.files import docx_bytes, make_zip

MakeClient = Callable[..., Awaitable[AsyncClient]]
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])


async def _members(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, *, consent: bool = True
) -> tuple[Project, dict[str, User]]:
    owner = await make_user(db, settings, email="owner@example.com", display_name="Owner")
    editor = await make_user(db, settings, email="editor@example.com", display_name="Editor")
    viewer = await make_user(db, settings, email="viewer@example.com", display_name="Viewer")
    client_user = await make_user(
        db, settings, email="c@client.com", display_name="Client", account_type="customer"
    )
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo", consent=consent)
    await add_member(db, project, editor, "editor")
    await add_member(db, project, viewer, "viewer")
    await add_member(db, project, client_user, "client")
    return project, {"owner": owner, "editor": editor, "viewer": viewer, "client": client_user}


async def _client(
    make_client: MakeClient,
    db: AsyncSession,
    settings: Settings,
    user: User,
    app: FastAPI | None = None,
) -> AsyncClient:
    return await make_client(await make_session_token(db, settings, user), app_=app)


def _multipart(files: list[tuple[str, bytes]], specs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "files": [("files", (name, data, "application/octet-stream")) for name, data in files],
        "data": {"items": json.dumps(specs)},
    }


async def test_upload_publishes_and_can_be_polled(
    make_client: MakeClient,
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    storage_root: Path,
) -> None:
    project, users = await _members(db, settings, taxonomy)
    editor = await _client(make_client, db, settings, users["editor"])
    archive = make_zip(
        Path(settings.staging_root) / "fixture.zip",
        {"docs/Glossary.md": b"# Glossary\n\nTerm: meaning\n", "docs/.DS_Store": b"x"},
    )
    payload = _multipart(
        [
            ("Customer Portal SRS.docx", SRS),
            ("export.zip", archive.read_bytes()),
            ("virus.exe", b"x"),
        ],
        [{"doc_type": "srs"}, {"doc_type": "glossary"}, {"doc_type": "srs"}],
    )
    response = await editor.post(f"/api/v1/projects/{project.id}/uploads", **payload)  # type: ignore[arg-type]
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rejected"] == [
        {
            "name": "virus.exe",
            "reason": (
                "File type is not supported. "
                "Allowed: csv, docx, html, md, pdf, pptx, txt, xlsx, zip."
            ),
        }
    ]
    names = sorted(i["original_name"] for i in body["items"])
    assert names == ["Customer Portal SRS.docx", "Glossary.md"]
    polled = await editor.get(f"/api/v1/uploads/{body['id']}")
    assert polled.status_code == 200
    items = {i["original_name"]: i for i in polled.json()["items"]}
    assert items["Customer Portal SRS.docx"]["status"] == "published"
    assert items["Customer Portal SRS.docx"]["document_id"] is not None
    assert items["Glossary.md"]["status"] == "published"
    assert items["Glossary.md"]["selected_doc_type"] == "glossary"
    assert items["Glossary.md"]["title"] == "Glossary"
    assert (storage_root / "demo/01-overview/glossary--glossary.md").exists()
    assert "upload.created" in (await db.scalars(select(AuditLog.action))).all()


async def test_upload_blocked_without_consent_and_for_viewers(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _members(db, settings, taxonomy, consent=False)
    editor = await _client(make_client, db, settings, users["editor"])
    payload = _multipart([("srs.docx", SRS)], [{"doc_type": "srs"}])
    blocked = await editor.post(f"/api/v1/projects/{project.id}/uploads", **payload)  # type: ignore[arg-type]
    assert blocked.status_code == 409
    assert blocked.json()["detail"].startswith("The project owner must confirm LLM data processing")
    viewer = await _client(make_client, db, settings, users["viewer"])
    assert (
        await viewer.post(f"/api/v1/projects/{project.id}/uploads", **payload)
    ).status_code == 403  # type: ignore[arg-type]


async def test_validation_of_items_part(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _members(db, settings, taxonomy)
    editor = await _client(make_client, db, settings, users["editor"])
    url = f"/api/v1/projects/{project.id}/uploads"
    files = [("files", ("srs.docx", SRS, "application/octet-stream"))]
    assert (await editor.post(url, files=files, data={"items": "not json"})).status_code == 422
    assert (await editor.post(url, files=files, data={"items": "[]"})).status_code == 422
    unknown = await editor.post(
        url, files=files, data={"items": json.dumps([{"doc_type": "poem"}])}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["rejected"][0]["reason"] == "Unknown document type 'poem'."


async def test_client_uploads_are_forced_shared_and_private_to_the_client(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _members(db, settings, taxonomy)
    client_c = await _client(make_client, db, settings, users["client"])
    payload = _multipart([("brd.docx", SRS)], [{"doc_type": "brd", "visibility": "internal"}])
    response = await client_c.post(f"/api/v1/projects/{project.id}/uploads", **payload)  # type: ignore[arg-type]
    assert response.status_code == 201
    item = response.json()["items"][0]
    assert item["visibility"] == "shared"
    document = (
        await db.scalars(
            select(Document).where(Document.doc_type == "brd", Document.is_stub.is_(False))
        )
    ).one()
    assert document.visibility == "shared"
    # another client cannot read this upload; the owner can
    other_client = await make_user(db, settings, email="d@client.com", account_type="customer")
    await add_member(db, project, other_client, "client")
    other = await _client(make_client, db, settings, other_client)
    assert (await other.get(f"/api/v1/uploads/{response.json()['id']}")).status_code == 404
    owner = await _client(make_client, db, settings, users["owner"])
    assert (await owner.get(f"/api/v1/uploads/{response.json()['id']}")).status_code == 200


async def test_mismatch_flow_through_my_tasks_and_confirm_type(
    make_app: Callable[..., FastAPI],
    make_client: MakeClient,
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
) -> None:
    project, users = await _members(db, settings, taxonomy)
    fake = FakeAnalyzer(
        {"plan.docx": ScriptedVerdict("mismatch", "Reads like a test plan.", "test-plan")}
    )
    app = make_app(analyzer=fake)
    editor = await _client(make_client, db, settings, users["editor"], app=app)
    other_editor_user = await make_user(db, settings, email="e2@example.com", display_name="E2")
    await add_member(db, project, other_editor_user, "editor")
    other_editor = await _client(make_client, db, settings, other_editor_user, app=app)
    payload = _multipart([("plan.docx", SRS)], [{"doc_type": "srs", "title": "Plan"}])
    created = await editor.post(f"/api/v1/projects/{project.id}/uploads", **payload)  # type: ignore[arg-type]
    item = created.json()["items"][0]
    polled = (await editor.get(f"/api/v1/uploads/{created.json()['id']}")).json()["items"][0]
    assert polled["status"] == "needs_confirmation" and polled["suggested_doc_type"] == "test-plan"
    tasks = (await editor.get("/api/v1/me/tasks")).json()
    assert [t["item"]["id"] for t in tasks] == [item["id"]] and tasks[0]["project_name"] == "Demo"
    assert (await other_editor.get("/api/v1/me/tasks")).json() == []
    confirm_url = f"/api/v1/upload-items/{item['id']}/confirm-type"
    assert (await other_editor.post(confirm_url, json={"doc_type": "test-plan"})).status_code == 403
    assert (await editor.post(confirm_url, json={"doc_type": "poem"})).status_code == 409
    confirmed = await editor.post(confirm_url, json={"doc_type": "test-plan"})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "publishing"
    final = (await editor.get(f"/api/v1/uploads/{created.json()['id']}")).json()["items"][0]
    assert final["status"] == "published" and final["type_check"] == "mismatch_changed"
    assert (await editor.post(confirm_url, json={"doc_type": "test-plan"})).status_code == 409
    assert (await editor.get("/api/v1/me/tasks")).json() == []
    assert "upload_item.type_confirmed" in (await db.scalars(select(AuditLog.action))).all()


async def test_retry_failed_item(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _members(db, settings, taxonomy)
    editor = await _client(make_client, db, settings, users["editor"])
    payload = _multipart([("broken.docx", b"not a docx")], [{"doc_type": "srs"}])
    created = await editor.post(f"/api/v1/projects/{project.id}/uploads", **payload)  # type: ignore[arg-type]
    item = (await editor.get(f"/api/v1/uploads/{created.json()['id']}")).json()["items"][0]
    assert (
        item["status"] == "failed" and item["error"] == "File content does not match its extension."
    )
    retried = await editor.post(f"/api/v1/upload-items/{item['id']}/retry")
    assert retried.status_code == 200
    again = (await editor.get(f"/api/v1/uploads/{created.json()['id']}")).json()["items"][0]
    assert again["status"] == "failed"  # same file, same reason; the retry path itself works
    assert (await editor.post(f"/api/v1/upload-items/{item['id']}/retry")).status_code == 200
    viewer = await _client(make_client, db, settings, users["viewer"])
    assert (await viewer.post(f"/api/v1/upload-items/{item['id']}/retry")).status_code == 403
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_uploads.py -v`
Expected: FAIL — `assert 404 == 201` (no upload routes yet).

- [ ] **Step 4: Dependencies in `deps.py`**

In `backend/app/api/deps.py` add `from app.services.pipeline import PipelineContext` to the imports, then append after `TaxonomyDep = …`:

```python
def pipeline_dep(request: Request) -> PipelineContext:
    pipeline: PipelineContext = request.app.state.pipeline
    return pipeline


PipelineDep = Annotated[PipelineContext, Depends(pipeline_dep)]
```

Replace everything from `def require_project_role(` through `ProjectOwner = Annotated[...]` with:

```python
async def resolve_role(db: AsyncSession, project: Project, user: User) -> str | None:
    """The user's role on a live project, ``owner`` for admins, None for non-members."""
    if project.archived_at is not None:
        return None
    if user.is_admin:
        return "owner"
    return await db.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
        )
    )


def require_project_role(*allowed: str) -> Callable[..., Awaitable[ProjectContext]]:
    async def dependency(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectContext:
        project = await db.get(Project, project_id)
        role = None if project is None else await resolve_role(db, project, user)
        if project is None or role is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this action.")
        return ProjectContext(project=project, user=user, role=role)

    return dependency


AnyMember = Annotated[ProjectContext, Depends(require_project_role(*ALL_ROLES))]
InternalMember = Annotated[ProjectContext, Depends(require_project_role(*INTERNAL_ROLES))]
ProjectOwner = Annotated[ProjectContext, Depends(require_project_role("owner"))]
Uploader = Annotated[ProjectContext, Depends(require_project_role("owner", "editor", "client"))]
```

- [ ] **Step 5: Routes and app wiring**

`backend/app/api/routes/uploads.py`:

```python
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AppSettings,
    CurrentUser,
    DbSession,
    PipelineDep,
    TaxonomyDep,
    Uploader,
    resolve_role,
)
from app.db.models import Project, Upload, UploadItem, User
from app.ingestion.intake import IntakeLimits, Rejection
from app.schemas.uploads import (
    ConfirmTypeRequest,
    RejectionOut,
    TaskOut,
    UploadItemOut,
    UploadItemSpec,
    UploadOut,
)
from app.services import uploads as uploads_service
from app.services.consent import has_consent
from app.services.pipeline import publish_confirmed_item, run_upload

router = APIRouter(tags=["uploads"])
_SPECS = TypeAdapter(list[UploadItemSpec])
CONSENT_REQUIRED = (
    "The project owner must confirm LLM data processing before documents can be uploaded."
)


def item_out(item: UploadItem, document_id: uuid.UUID | None) -> UploadItemOut:
    return UploadItemOut(
        id=item.id,
        upload_id=item.upload_id,
        original_name=item.original_name,
        ext=item.ext,
        size=item.size,
        sha256=item.sha256,
        selected_doc_type=item.selected_doc_type,
        final_doc_type=item.final_doc_type,
        title=item.title,
        intent=item.intent,
        target_document_id=item.target_document_id,
        visibility=item.visibility,
        status=item.status,
        type_check=item.type_check,
        check_explanation=item.check_explanation,
        suggested_doc_type=item.suggested_doc_type,
        version_hint_document_id=item.version_hint_document_id,
        warnings=list(item.conversion_meta.get("warnings", [])),
        conversion_meta={k: v for k, v in item.conversion_meta.items() if k != "warnings"},
        error=item.error,
        document_id=document_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _upload_out(db: AsyncSession, upload: Upload, rejected: list[Rejection]) -> UploadOut:
    items = await uploads_service.list_items(db, upload.id)
    documents = await uploads_service.published_document_ids(db, [i.id for i in items])
    return UploadOut(
        id=upload.id,
        project_id=upload.project_id,
        uploaded_by=upload.uploaded_by,
        created_at=upload.created_at,
        items=[item_out(item, documents.get(item.id)) for item in items],
        rejected=[RejectionOut(name=r.name, reason=r.reason) for r in rejected],
    )


def _parse_specs(items: str, count: int) -> list[UploadItemSpec]:
    try:
        specs = _SPECS.validate_python(json.loads(items))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="The items part is not valid.") from exc
    if len(specs) != count:
        raise HTTPException(
            status_code=422, detail="The items part must have one entry per uploaded file."
        )
    return specs


@router.post("/projects/{project_id}/uploads", response_model=UploadOut, status_code=201)
async def create_upload(
    ctx: Uploader,
    db: DbSession,
    settings: AppSettings,
    taxonomy: TaxonomyDep,
    pipeline: PipelineDep,
    background: BackgroundTasks,
    files: Annotated[list[UploadFile], File()],
    items: Annotated[str, Form()],
) -> UploadOut:
    if not has_consent(ctx.project):
        raise HTTPException(status_code=409, detail=CONSENT_REQUIRED)
    specs = _parse_specs(items, len(files))
    upload_id = uuid.uuid4()
    limits = IntakeLimits.from_megabytes(settings.max_upload_file_mb, settings.max_upload_batch_mb)
    staged, rejections = await uploads_service.stage_files(
        [uploads_service.IncomingFile(name=f.filename or "file", read=f.read) for f in files],
        specs,
        staging_dir=uploads_service.staging_dir_for(pipeline.staging_root, upload_id),
        limits=limits,
    )
    try:
        upload, rejected = await uploads_service.create_upload(
            db,
            project=ctx.project,
            uploader=ctx.user,
            role=ctx.role,
            upload_id=upload_id,
            staged=staged,
            rejections=rejections,
            taxonomy=taxonomy,
            staging_root=pipeline.staging_root,
        )
    except uploads_service.UploadError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": exc.message,
                "rejected": [{"name": r.name, "reason": r.reason} for r in exc.rejections],
            },
        ) from exc
    background.add_task(run_upload, pipeline, upload.id)
    return await _upload_out(db, upload, rejected)


async def _upload_for(db: AsyncSession, upload_id: uuid.UUID, user: User) -> tuple[Upload, str]:
    upload = await db.get(Upload, upload_id)
    project = None if upload is None else await db.get(Project, upload.project_id)
    role = None if project is None else await resolve_role(db, project, user)
    if upload is None or role is None or (role == "client" and upload.uploaded_by != user.id):
        raise HTTPException(status_code=404, detail="Upload not found.")
    return upload, role


@router.get("/uploads/{upload_id}", response_model=UploadOut)
async def get_upload(upload_id: uuid.UUID, user: CurrentUser, db: DbSession) -> UploadOut:
    upload, _ = await _upload_for(db, upload_id, user)
    return await _upload_out(db, upload, [])


@router.get("/me/tasks", response_model=list[TaskOut])
async def my_tasks(user: CurrentUser, db: DbSession) -> list[TaskOut]:
    return [
        TaskOut(item=item_out(item, None), project_id=project.id, project_name=project.name)
        for item, project in await uploads_service.my_tasks(db, user)
    ]


async def _actionable_item(
    db: AsyncSession, item_id: uuid.UUID, user: User
) -> tuple[UploadItem, Upload]:
    item = await db.get(UploadItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Upload item not found.")
    upload, role = await _upload_for(db, item.upload_id, user)
    if not uploads_service.may_act_on_item(upload, role, user):
        raise HTTPException(status_code=403, detail="You do not have access to this action.")
    return item, upload


@router.post("/upload-items/{item_id}/confirm-type", response_model=UploadItemOut)
async def confirm_type(
    item_id: uuid.UUID,
    body: ConfirmTypeRequest,
    user: CurrentUser,
    db: DbSession,
    taxonomy: TaxonomyDep,
    pipeline: PipelineDep,
    background: BackgroundTasks,
) -> UploadItemOut:
    item, upload = await _actionable_item(db, item_id, user)
    try:
        await uploads_service.confirm_type(
            db,
            item,
            doc_type_key=body.doc_type,
            taxonomy=taxonomy,
            actor=user,
            project_id=upload.project_id,
        )
    except uploads_service.ItemStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    background.add_task(publish_confirmed_item, pipeline, item.id)
    return item_out(item, None)


@router.post("/upload-items/{item_id}/retry", response_model=UploadItemOut)
async def retry_item(
    item_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    pipeline: PipelineDep,
    background: BackgroundTasks,
) -> UploadItemOut:
    item, upload = await _actionable_item(db, item_id, user)
    try:
        await uploads_service.retry_item(db, item, actor=user, project_id=upload.project_id)
    except uploads_service.ItemStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    background.add_task(run_upload, pipeline, upload.id, [item.id])
    return item_out(item, None)
```

Replace `backend/app/main.py`:

```python
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.agent.analyzer import Analyzer, SkipAnalyzer
from app.api.routes import auth, health, projects, uploads, users
from app.api.routes import taxonomy as taxonomy_routes
from app.core.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.db.session import dispose_engine, init_engine, is_initialised
from app.ingestion.taxonomy import load_taxonomy
from app.services.pipeline import PipelineContext, requeue_stale_items

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-qc-agent"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, analyzer: Analyzer | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    templates_dir = Path(app_settings.templates_dir) if app_settings.templates_dir else None
    taxonomy = load_taxonomy(templates_dir)  # validates the taxonomy at startup
    pipeline = PipelineContext(
        settings=app_settings, taxonomy=taxonomy, analyzer=analyzer or SkipAnalyzer()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not is_initialised():
            init_engine(app_settings.database_url)
        requeued = await requeue_stale_items(pipeline)
        if requeued:
            logger.info("Re-queued %d upload items left in progress", requeued)
        yield
        await dispose_engine()

    app = FastAPI(
        title="QC-Agent",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs" if app_settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if app_settings.expose_docs else None,
    )
    app.state.settings = app_settings
    app.state.taxonomy = taxonomy
    app.state.analyzer = pipeline.analyzer
    app.state.pipeline = pipeline
    app.state.auth_limiter = SlidingWindowLimiter(
        limit=app_settings.rate_limit_auth_per_5min, window_seconds=300
    )

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "Missing CSRF header."}, status_code=403)
        return await call_next(request)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(users.router, prefix=API_PREFIX)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(taxonomy_routes.router, prefix=API_PREFIX)
    app.include_router(uploads.router, prefix=API_PREFIX)
    return app
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api -v`
Expected: all passed (`6` in `test_uploads.py`; Plan 1 API tests unchanged).

- [ ] **Step 7: Smoke-test the running app against the dev database**

```bash
uv run alembic upgrade head
uv run uvicorn --factory app.main:create_app --reload
```

Expected: the process starts, logs nothing about re-queued items on an empty database, and `GET http://localhost:8000/api/v1/taxonomy` answers 401 without a session. Stop the server.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/pyproject.toml backend/uv.lock backend/app backend/tests/api/test_uploads.py
git commit -m "feat(backend): add upload API with background pipeline and startup re-queue"
```

---

### Task 13: Documents API with role and visibility rules, gap report and version suggestions

**Files:**
- Create: `backend/app/schemas/documents.py`, `backend/app/services/documents.py`, `backend/app/api/routes/documents.py`
- Modify: `backend/app/api/deps.py` (import `Document`; append `DocumentContext`), `backend/app/main.py` (register the router)
- Test: `backend/tests/api/test_documents.py`

**Interfaces:**
- Consumes: models (Task 5), `backend_for` (Task 3), `build_gap_report`, `document_facts` (Tasks 4, 6), `suggest_versions` (Task 4), `content_type_for` (Task 11), `resolve_role`, `Uploader` (Task 12).
- Produces:
  - `app.api.deps`: `DocumentContext(document, project, user, role)`, `document_context(document_id, user, db)` dependency (404 for unknown document, archived project, non-member, or a client on an internal document), alias `DocumentAccess`.
  - `app.services.documents`: `list_documents(db, project_id, role, taxonomy, *, folder, doc_type, visibility, q)` (clients restricted to `shared`; `q` is an escaped case-insensitive title match; sorted in taxonomy folder order), `list_versions(db, document_id) -> list[(DocumentVersion, uploader display name)]`, `get_version(db, document_id, version)`, `update_document(db, document, *, actor, role, title, visibility)` (owner any change; editor rename and internal→shared only; others `DocumentPermissionError`; stubs not editable; audit `document.visibility_changed` or `document.updated`), `version_suggestions(db, project_id, role, *, doc_type, title)`, `visible_to_role(role)`.
  - Schemas: `DocumentOut` (from attributes), `DocumentVersionOut(version, sha256, original_path, markdown_path, uploaded_by, upload_item_id, created_at)`, `DocumentUpdate(title?, visibility?)`, `VersionSuggestionOut`.
  - Routes: `GET /projects/{project_id}/documents?folder=&doc_type=&visibility=&q=`, `GET /projects/{project_id}/gap-report` (internal roles; JSON as in `_reports/gap-report.json`, computed live), `GET /projects/{project_id}/version-suggestions?doc_type=&title=` (upload roles), `GET /documents/{document_id}`, `GET /documents/{document_id}/versions`, `GET /documents/{document_id}/versions/{version}/original` (bytes from storage version history, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`; 404 for stubs), `GET /documents/{document_id}/versions/{version}/markdown` (from `markdown_text`), `PATCH /documents/{document_id}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_documents.py`:

```python
"""Document endpoints: listing and filters, role × visibility matrix, downloads, versions,
PATCH rules, gap report and version suggestions."""

import json
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, Document, Project, User
from app.ingestion.taxonomy import Taxonomy
from tests.factories import add_member, make_project, make_session_token, make_user
from tests.helpers.files import docx_bytes

MakeClient = Callable[..., Awaitable[AsyncClient]]
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
SRS_V2 = docx_bytes(["The system shall allow users to log in with a password and MFA."])


async def _world(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> tuple[Project, dict[str, AsyncClient], dict[str, User], dict[str, str]]:
    owner = await make_user(db, settings, email="owner@example.com", display_name="Owner")
    editor = await make_user(db, settings, email="editor@example.com", display_name="Editor")
    viewer = await make_user(db, settings, email="viewer@example.com", display_name="Viewer")
    client_user = await make_user(
        db, settings, email="c@client.com", display_name="Client", account_type="customer"
    )
    outsider = await make_user(db, settings, email="out@example.com", display_name="Out")
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    for user, role in ((editor, "editor"), (viewer, "viewer"), (client_user, "client")):
        await add_member(db, project, user, role)
    clients = {}
    for name, user in (
        ("owner", owner),
        ("editor", editor),
        ("viewer", viewer),
        ("client", client_user),
        ("outsider", outsider),
    ):
        clients[name] = await make_client(await make_session_token(db, settings, user))
    url = f"/api/v1/projects/{project.id}/uploads"
    files = [
        ("files", ("srs.docx", SRS, "application/octet-stream")),
        ("files", ("runbook.md", b"# Runbook\n\nRestart.\n", "text/markdown")),
    ]
    specs = [
        {"doc_type": "srs", "title": "Portal SRS"},
        {"doc_type": "runbook", "title": "Ops Runbook", "visibility": "shared"},
    ]
    created = await clients["editor"].post(url, files=files, data={"items": json.dumps(specs)})
    assert created.status_code == 201, created.text
    documents = (await db.scalars(select(Document).where(Document.is_stub.is_(False)))).all()
    ids = {d.doc_type: str(d.id) for d in documents}
    users = {"owner": owner, "editor": editor, "viewer": viewer, "client": client_user}
    return project, clients, users, ids


async def test_listing_and_filters(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    url = f"/api/v1/projects/{project.id}/documents"
    everything = (await clients["viewer"].get(url)).json()
    assert len(everything) == 10  # 8 remaining stubs + 2 real documents
    assert [d["folder_id"] for d in everything][:3] == ["overview", "overview", "requirements"]
    real = [d for d in everything if not d["is_stub"]]
    assert {d["id"] for d in real} == set(ids.values())
    assert (
        await clients["viewer"].get(url, params={"folder": "deployment", "doc_type": "runbook"})
    ).json()[-1]["title"] == "Ops Runbook"
    assert [
        d["title"] for d in (await clients["viewer"].get(url, params={"q": "portal"})).json()
    ] == ["Portal SRS"]
    assert (await clients["viewer"].get(url, params={"q": "%"})).json() == []
    shared_only = (await clients["client"].get(url)).json()
    assert [d["title"] for d in shared_only] == ["Ops Runbook"]
    assert (await clients["client"].get(url, params={"visibility": "internal"})).json() == []
    assert (await clients["outsider"].get(url)).status_code == 404


async def test_role_visibility_matrix(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    expected = {
        ("owner", "srs"): 200,
        ("editor", "srs"): 200,
        ("viewer", "srs"): 200,
        ("client", "srs"): 404,
        ("owner", "runbook"): 200,
        ("editor", "runbook"): 200,
        ("viewer", "runbook"): 200,
        ("client", "runbook"): 200,
        ("outsider", "srs"): 404,
        ("outsider", "runbook"): 404,
    }
    for (role, doc_type), status in expected.items():
        for suffix in ("", "/versions", "/versions/1/original", "/versions/1/markdown"):
            response = await clients[role].get(f"/api/v1/documents/{ids[doc_type]}{suffix}")
            assert response.status_code == status, (role, doc_type, suffix, response.status_code)


async def test_downloads_have_attachment_headers_and_content(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    original = await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/1/original")
    assert original.status_code == 200
    assert original.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert original.headers["content-disposition"].startswith(
        'attachment; filename="srs--portal-srs.docx"'
    )
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.content == SRS
    markdown = await clients["client"].get(
        f"/api/v1/documents/{ids['runbook']}/versions/1/markdown"
    )
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text.startswith("---\nqc_agent: 2\n") and "Restart." in markdown.text
    assert (
        await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/9/original")
    ).status_code == 404
    stub = (await db.scalars(select(Document).where(Document.is_stub.is_(True)))).first()
    assert stub is not None
    stub_original = await clients["viewer"].get(f"/api/v1/documents/{stub.id}/versions/1/original")
    assert (
        stub_original.status_code == 404
        and stub_original.json()["detail"] == "Stub documents have no original file."
    )
    assert (
        await clients["viewer"].get(f"/api/v1/documents/{stub.id}/versions/1/markdown")
    ).status_code == 200


async def test_versions_list_after_new_version(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    files = [("files", ("srs-v2.docx", SRS_V2, "application/octet-stream"))]
    specs = [{"doc_type": "srs", "intent": "version", "target_document_id": ids["srs"]}]
    created = await clients["owner"].post(
        f"/api/v1/projects/{project.id}/uploads", files=files, data={"items": json.dumps(specs)}
    )
    assert created.status_code == 201
    versions = (await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions")).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["uploaded_by"] for v in versions] == ["Editor", "Owner"]
    assert (await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}")).json()[
        "current_version"
    ] == 2
    old = await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/1/original")
    assert old.content == SRS


async def test_patch_rules(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    srs = f"/api/v1/documents/{ids['srs']}"
    runbook = f"/api/v1/documents/{ids['runbook']}"
    assert (await clients["viewer"].patch(srs, json={"title": "X"})).status_code == 403
    assert (
        await clients["client"].patch(runbook, json={"visibility": "internal"})
    ).status_code == 403
    assert (await clients["client"].patch(srs, json={"title": "X"})).status_code == 404
    shared = await clients["editor"].patch(
        srs, json={"visibility": "shared", "title": "Portal SRS v2"}
    )
    assert shared.status_code == 200 and shared.json()["visibility"] == "shared"
    assert shared.json()["title"] == "Portal SRS v2" and shared.json()["slug"] == "portal-srs"
    assert (await clients["client"].get(srs)).status_code == 200  # now visible to the client
    assert (await clients["editor"].patch(srs, json={"visibility": "internal"})).status_code == 403
    assert (await clients["owner"].patch(srs, json={"visibility": "internal"})).status_code == 200
    assert (await clients["client"].get(srs)).status_code == 404
    assert (await clients["owner"].patch(srs, json={"title": "   "})).status_code == 422
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "document.visibility_changed" in actions


async def test_gap_report_and_version_suggestions(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    report = await clients["viewer"].get(f"/api/v1/projects/{project.id}/gap-report")
    assert report.status_code == 200
    assert report.json()["required_present"] == 2 and report.json()["required_total"] == 10
    statuses = {
        t["doc_type"]: t["status"] for f in report.json()["folders"] for t in f["doc_types"]
    }
    assert (
        statuses["srs"] == "present"
        and statuses["brd"] == "stub"
        and statuses["glossary"] == "missing"
    )
    assert (
        await clients["client"].get(f"/api/v1/projects/{project.id}/gap-report")
    ).status_code == 403
    suggest = f"/api/v1/projects/{project.id}/version-suggestions"
    found = await clients["editor"].get(
        suggest, params={"doc_type": "srs", "title": "Portal SRS v1"}
    )
    assert found.status_code == 200
    assert [s["document_id"] for s in found.json()] == [ids["srs"]]
    assert found.json()[0]["current_version"] == 1 and found.json()[0]["similarity"] >= 0.8
    assert (
        await clients["editor"].get(
            suggest, params={"doc_type": "srs", "title": "Payments gateway"}
        )
    ).json() == []
    # clients only get suggestions among shared documents
    assert (
        await clients["client"].get(suggest, params={"doc_type": "srs", "title": "Portal SRS"})
    ).json() == []
    assert (
        await clients["viewer"].get(suggest, params={"doc_type": "srs", "title": "Portal SRS"})
    ).status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_documents.py -v`
Expected: FAIL — `assert 404 == 200` on the documents listing.

- [ ] **Step 3: Implement schemas, service, dependency and routes**

`backend/app/schemas/documents.py`:

```python
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    folder_id: str
    doc_type: str
    title: str
    slug: str
    visibility: str
    current_version: int
    is_stub: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DocumentVersionOut(BaseModel):
    version: int
    sha256: str
    original_path: str | None
    markdown_path: str
    uploaded_by: str  # display name
    upload_item_id: uuid.UUID | None
    created_at: datetime


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    visibility: Literal["internal", "shared"] | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Title is required.")
        return cleaned


class VersionSuggestionOut(BaseModel):
    document_id: uuid.UUID
    title: str
    current_version: int
    similarity: float
```

`backend/app/services/documents.py`:

```python
"""Document queries and edits with the role and visibility rules of spec 9."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentVersion, User
from app.ingestion.taxonomy import Taxonomy
from app.ingestion.versioning import VersionCandidate, VersionSuggestion, suggest_versions
from app.services import audit


class DocumentPermissionError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def visible_to_role(role: str) -> str | None:
    """The visibility a role is restricted to (clients see shared documents only)."""
    return "shared" if role == "client" else None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_documents(
    db: AsyncSession,
    project_id: uuid.UUID,
    role: str,
    taxonomy: Taxonomy,
    *,
    folder: str | None = None,
    doc_type: str | None = None,
    visibility: str | None = None,
    q: str | None = None,
) -> list[Document]:
    stmt = select(Document).where(Document.project_id == project_id)
    restricted = visible_to_role(role)
    if restricted is not None:
        stmt = stmt.where(Document.visibility == restricted)
    if folder is not None:
        stmt = stmt.where(Document.folder_id == folder)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)
    if visibility is not None:
        stmt = stmt.where(Document.visibility == visibility)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{_escape_like(q)}%", escape="\\"))
    documents = list((await db.scalars(stmt)).all())
    order = {folder.id: index for index, folder in enumerate(taxonomy.folders)}
    documents.sort(
        key=lambda d: (order.get(d.folder_id, 99), d.doc_type, d.is_stub, d.title.lower())
    )
    return documents


async def list_versions(
    db: AsyncSession, document_id: uuid.UUID
) -> list[tuple[DocumentVersion, str]]:
    rows = (
        await db.execute(
            select(DocumentVersion, User.display_name)
            .join(User, User.id == DocumentVersion.uploaded_by)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version)
        )
    ).all()
    return [(version, name) for version, name in rows]


async def get_version(
    db: AsyncSession, document_id: uuid.UUID, version: int
) -> DocumentVersion | None:
    return await db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id, DocumentVersion.version == version
        )
    )


async def update_document(
    db: AsyncSession,
    document: Document,
    *,
    actor: User,
    role: str,
    title: str | None,
    visibility: str | None,
) -> None:
    """Owners change anything; editors rename and may share internal documents; viewers and
    clients cannot edit. Renaming never moves files in storage (paths follow the slug)."""
    if role not in ("owner", "editor"):
        raise DocumentPermissionError("You do not have access to this action.")
    if document.is_stub:
        raise DocumentPermissionError("Stub documents cannot be edited.")
    changes: dict[str, str] = {}
    if visibility is not None and visibility != document.visibility:
        if role == "editor" and visibility == "internal":
            raise DocumentPermissionError(
                "Only a project owner can make a shared document internal."
            )
        changes["visibility"] = visibility
        document.visibility = visibility
    if title is not None and title != document.title:
        changes["title"] = title
        document.title = title
    if not changes:
        return
    document.updated_at = datetime.now(UTC)
    action = "document.visibility_changed" if "visibility" in changes else "document.updated"
    await audit.record(
        db,
        action,
        user_id=actor.id,
        project_id=document.project_id,
        target_type="document",
        target_id=str(document.id),
        details=changes,
    )
    await db.commit()


async def version_suggestions(
    db: AsyncSession, project_id: uuid.UUID, role: str, *, doc_type: str, title: str
) -> list[VersionSuggestion]:
    stmt = select(Document).where(
        Document.project_id == project_id,
        Document.doc_type == doc_type,
        Document.is_stub.is_(False),
    )
    restricted = visible_to_role(role)
    if restricted is not None:
        stmt = stmt.where(Document.visibility == restricted)
    documents: Sequence[Document] = (await db.scalars(stmt)).all()
    return suggest_versions(
        title,
        [
            VersionCandidate(
                document_id=d.id, title=d.title, slug=d.slug, current_version=d.current_version
            )
            for d in documents
        ],
    )
```

In `backend/app/api/deps.py` add `Document` to the `app.db.models` import and append at the end:

```python
@dataclass
class DocumentContext:
    document: Document
    project: Project
    user: User
    role: str


async def document_context(
    document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> DocumentContext:
    """Role and visibility check shared by every document route: non-members and clients
    looking at internal documents get 404 so nothing leaks."""
    document = await db.get(Document, document_id)
    project = None if document is None else await db.get(Project, document.project_id)
    role = None if project is None else await resolve_role(db, project, user)
    if document is None or project is None or role is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if role == "client" and document.visibility != "shared":
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentContext(document=document, project=project, user=user, role=role)


DocumentAccess = Annotated[DocumentContext, Depends(document_context)]
```

For reference, `backend/app/api/deps.py` now reads in full:

```python
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import SESSION_COOKIE
from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.tokens import hash_token
from app.db.models import AuthSession, Document, Project, ProjectMember, User
from app.db.session import get_session
from app.ingestion.taxonomy import Taxonomy
from app.services.context import SessionContext
from app.services.pipeline import PipelineContext


def settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(settings_dep)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


def taxonomy_dep(request: Request) -> Taxonomy:
    taxonomy: Taxonomy = request.app.state.taxonomy
    return taxonomy


TaxonomyDep = Annotated[Taxonomy, Depends(taxonomy_dep)]


def pipeline_dep(request: Request) -> PipelineContext:
    pipeline: PipelineContext = request.app.state.pipeline
    return pipeline


PipelineDep = Annotated[PipelineContext, Depends(pipeline_dep)]


async def session_context(request: Request, db: DbSession, settings: AppSettings) -> SessionContext:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    auth_session = await db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(token, settings.session_secret)
        )
    )
    now = datetime.now(UTC)
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
    ):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user = await db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return SessionContext(auth_session=auth_session, user=user)


SessionCtx = Annotated[SessionContext, Depends(session_context)]


def auth_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    if not request.app.state.auth_limiter.hit(key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")


def secret_box_dep(settings: AppSettings) -> SecretBox:
    return SecretBox(settings.secret_encryption_key)


Box = Annotated[SecretBox, Depends(secret_box_dep)]


async def mfa_context(ctx: SessionCtx) -> SessionContext:
    if not ctx.auth_session.mfa_verified:
        raise HTTPException(status_code=401, detail="MFA verification required.")
    return ctx


MfaCtx = Annotated[SessionContext, Depends(mfa_context)]


async def current_user(ctx: MfaCtx) -> User:
    if ctx.user.must_change_password:
        raise HTTPException(status_code=403, detail="Password change required.")
    return ctx.user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]

ALL_ROLES = ("owner", "editor", "viewer", "client")
INTERNAL_ROLES = ("owner", "editor", "viewer")


@dataclass
class ProjectContext:
    project: Project
    user: User
    role: str


async def resolve_role(db: AsyncSession, project: Project, user: User) -> str | None:
    """The user's role on a live project, ``owner`` for admins, None for non-members."""
    if project.archived_at is not None:
        return None
    if user.is_admin:
        return "owner"
    return await db.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
        )
    )


def require_project_role(*allowed: str) -> Callable[..., Awaitable[ProjectContext]]:
    async def dependency(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectContext:
        project = await db.get(Project, project_id)
        role = None if project is None else await resolve_role(db, project, user)
        if project is None or role is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this action.")
        return ProjectContext(project=project, user=user, role=role)

    return dependency


AnyMember = Annotated[ProjectContext, Depends(require_project_role(*ALL_ROLES))]
InternalMember = Annotated[ProjectContext, Depends(require_project_role(*INTERNAL_ROLES))]
ProjectOwner = Annotated[ProjectContext, Depends(require_project_role("owner"))]
Uploader = Annotated[ProjectContext, Depends(require_project_role("owner", "editor", "client"))]


@dataclass
class DocumentContext:
    document: Document
    project: Project
    user: User
    role: str


async def document_context(
    document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> DocumentContext:
    """Role and visibility check shared by every document route: non-members and clients
    looking at internal documents get 404 so nothing leaks."""
    document = await db.get(Document, document_id)
    project = None if document is None else await db.get(Project, document.project_id)
    role = None if project is None else await resolve_role(db, project, user)
    if document is None or project is None or role is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if role == "client" and document.visibility != "shared":
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentContext(document=document, project=project, user=user, role=role)


DocumentAccess = Annotated[DocumentContext, Depends(document_context)]
```

`backend/app/api/routes/documents.py`:

```python
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import (
    AnyMember,
    AppSettings,
    DbSession,
    DocumentAccess,
    InternalMember,
    TaxonomyDep,
    Uploader,
)
from app.ingestion.gaps import build_gap_report
from app.schemas.documents import (
    DocumentOut,
    DocumentUpdate,
    DocumentVersionOut,
    VersionSuggestionOut,
)
from app.services import documents as documents_service
from app.services.publish import content_type_for
from app.services.workspace import document_facts
from app.storage.base import StorageError, StorageNotFound
from app.storage.select import backend_for

router = APIRouter(tags=["documents"])


def _attachment(filename: str) -> dict[str, str]:
    fallback = filename.encode("ascii", "replace").decode().replace('"', "")
    encoded = quote(filename)
    return {
        "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}",
        "X-Content-Type-Options": "nosniff",
    }


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    ctx: AnyMember,
    db: DbSession,
    taxonomy: TaxonomyDep,
    folder: str | None = Query(default=None, max_length=40),
    doc_type: str | None = Query(default=None, max_length=80),
    visibility: str | None = Query(default=None, pattern="^(internal|shared)$"),
    q: str | None = Query(default=None, max_length=200),
) -> list[DocumentOut]:
    documents = await documents_service.list_documents(
        db,
        ctx.project.id,
        ctx.role,
        taxonomy,
        folder=folder,
        doc_type=doc_type,
        visibility=visibility,
        q=q,
    )
    return [DocumentOut.model_validate(d) for d in documents]


@router.get("/projects/{project_id}/gap-report")
async def gap_report(ctx: InternalMember, db: DbSession, taxonomy: TaxonomyDep) -> dict[str, Any]:
    report = build_gap_report(
        taxonomy,
        await document_facts(db, ctx.project.id),
        project_slug=ctx.project.slug,
        project_name=ctx.project.name,
        generated_at=datetime.now(UTC),
    )
    return report.to_dict()


@router.get("/projects/{project_id}/version-suggestions", response_model=list[VersionSuggestionOut])
async def version_suggestions(
    ctx: Uploader,
    db: DbSession,
    doc_type: str = Query(max_length=80),
    title: str = Query(min_length=1, max_length=200),
) -> list[VersionSuggestionOut]:
    suggestions = await documents_service.version_suggestions(
        db, ctx.project.id, ctx.role, doc_type=doc_type, title=title
    )
    return [
        VersionSuggestionOut(
            document_id=s.document_id,
            title=s.title,
            current_version=s.current_version,
            similarity=s.similarity,
        )
        for s in suggestions
    ]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(ctx: DocumentAccess) -> DocumentOut:
    return DocumentOut.model_validate(ctx.document)


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_versions(ctx: DocumentAccess, db: DbSession) -> list[DocumentVersionOut]:
    return [
        DocumentVersionOut(
            version=v.version,
            sha256=v.sha256,
            original_path=v.original_path,
            markdown_path=v.markdown_path,
            uploaded_by=name,
            upload_item_id=v.upload_item_id,
            created_at=v.created_at,
        )
        for v, name in await documents_service.list_versions(db, ctx.document.id)
    ]


@router.get("/documents/{document_id}/versions/{version}/original")
async def download_original(
    version: int, ctx: DocumentAccess, db: DbSession, settings: AppSettings
) -> Response:
    row = await documents_service.get_version(db, ctx.document.id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    if row.original_path is None or row.original_storage_version is None:
        raise HTTPException(status_code=404, detail="Stub documents have no original file.")
    try:
        backend = backend_for(ctx.project.storage, settings)
        data = await backend.get_version(row.original_path, row.original_storage_version)
    except StorageNotFound as exc:
        raise HTTPException(status_code=404, detail="File is not available in storage.") from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Storage is unavailable.") from exc
    filename = PurePosixPath(row.original_path).name
    ext = filename.rsplit(".", 1)[-1].lower()
    return Response(content=data, media_type=content_type_for(ext), headers=_attachment(filename))


@router.get("/documents/{document_id}/versions/{version}/markdown")
async def download_markdown(version: int, ctx: DocumentAccess, db: DbSession) -> Response:
    row = await documents_service.get_version(db, ctx.document.id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    filename = PurePosixPath(row.markdown_path).name
    return Response(
        content=row.markdown_text,
        media_type="text/markdown; charset=utf-8",
        headers=_attachment(filename),
    )


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(body: DocumentUpdate, ctx: DocumentAccess, db: DbSession) -> DocumentOut:
    try:
        await documents_service.update_document(
            db,
            ctx.document,
            actor=ctx.user,
            role=ctx.role,
            title=body.title,
            visibility=body.visibility,
        )
    except documents_service.DocumentPermissionError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    return DocumentOut.model_validate(ctx.document)
```

In `backend/app/main.py` change the routes import to `from app.api.routes import auth, documents, health, projects, uploads, users` and add `app.include_router(documents.router, prefix=API_PREFIX)` after the uploads router. The final `main.py`:

```python
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.agent.analyzer import Analyzer, SkipAnalyzer
from app.api.routes import auth, documents, health, projects, uploads, users
from app.api.routes import taxonomy as taxonomy_routes
from app.core.config import Settings, get_settings
from app.core.ratelimit import SlidingWindowLimiter
from app.db.session import dispose_engine, init_engine, is_initialised
from app.ingestion.taxonomy import load_taxonomy
from app.services.pipeline import PipelineContext, requeue_stale_items

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-qc-agent"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, analyzer: Analyzer | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    templates_dir = Path(app_settings.templates_dir) if app_settings.templates_dir else None
    taxonomy = load_taxonomy(templates_dir)  # validates the taxonomy at startup
    pipeline = PipelineContext(
        settings=app_settings, taxonomy=taxonomy, analyzer=analyzer or SkipAnalyzer()
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not is_initialised():
            init_engine(app_settings.database_url)
        requeued = await requeue_stale_items(pipeline)
        if requeued:
            logger.info("Re-queued %d upload items left in progress", requeued)
        yield
        await dispose_engine()

    app = FastAPI(
        title="QC-Agent",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs" if app_settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if app_settings.expose_docs else None,
    )
    app.state.settings = app_settings
    app.state.taxonomy = taxonomy
    app.state.analyzer = pipeline.analyzer
    app.state.pipeline = pipeline
    app.state.auth_limiter = SlidingWindowLimiter(
        limit=app_settings.rate_limit_auth_per_5min, window_seconds=300
    )

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "Missing CSRF header."}, status_code=403)
        return await call_next(request)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(users.router, prefix=API_PREFIX)
    app.include_router(projects.router, prefix=API_PREFIX)
    app.include_router(taxonomy_routes.router, prefix=API_PREFIX)
    app.include_router(uploads.router, prefix=API_PREFIX)
    app.include_router(documents.router, prefix=API_PREFIX)
    return app
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -v`
Expected: all passed (`6` in `test_documents.py`).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
git add backend/app backend/tests/api/test_documents.py
git commit -m "feat(backend): add document API with role and visibility rules"
```

---

### Task 14: Documentation — README, `.env.example`, roadmap re-sequencing, pending items

**Files:**
- Modify: `backend/README.md` (replace), `backend/.env.example` (replace), `docs/superpowers/plans/2026-10-01-phase1-roadmap.md` (replace), `docs/PENDING.md` (three lines)

**Interfaces:**
- Consumes: everything above.
- Produces: documentation that matches the shipped behaviour; the roadmap re-sequenced as decided on 2026-10-01.

- [ ] **Step 1: Backend README**

`backend/README.md`:

```markdown
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
```

- [ ] **Step 2: Environment example**

`backend/.env.example`:

```dotenv
# Copy to .env. Generate secrets with:
#   uv run python -c "import secrets; print(secrets.token_urlsafe(48))"            -> SESSION_SECRET
#   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" -> SECRET_ENCRYPTION_KEY
DATABASE_URL=postgresql+asyncpg://qc:qc@localhost:5434/qc_agent
# The app refuses to start until both are set: SESSION_SECRET needs at least 32 characters,
# SECRET_ENCRYPTION_KEY must be a valid Fernet key.
SESSION_SECRET=
SECRET_ENCRYPTION_KEY=
PUBLIC_BASE_URL=http://localhost:3000
COOKIE_SECURE=false
# Serves /docs and /openapi.json. Local development only; leave unset (false) elsewhere.
EXPOSE_DOCS=true
# Local storage backend: one folder per project slug under this root (git-ignored).
LOCAL_STORAGE_ROOT=./workspace
# Staging area for uploaded and converted files (git-ignored).
STAGING_ROOT=./staging
# Upload limits in megabytes: per file and per request.
MAX_UPLOAD_FILE_MB=50
MAX_UPLOAD_BATCH_MB=500
# Optional: folder holding taxonomy.yaml and doc-templates/ (default: <repository>/templates).
# TEMPLATES_DIR=
```

- [ ] **Step 3: Roadmap**

Replace `docs/superpowers/plans/2026-10-01-phase1-roadmap.md`:

```markdown
# QC-Agent Phase 1 — Implementation Roadmap

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` (v2, approved 2026-10-01)

Phase 1 spans six subsystems. Each plan below produces working, tested software on its own and is executed and reviewed before the next one is written, so later plans can use real results (spike measurements, actual interfaces).

Re-sequenced on 2026-10-01 after the stakeholder chose to go straight to upload on local storage first and add cloud storage later: the former "Storage layer" and "Ingestion pipeline" rows became Plan 2 (local ingestion) and Plan 3 (cloud storage adapters).

| # | Plan | Delivers | Spec sections | Entry criteria | Status |
|---|---|---|---|---|---|
| 0 | Spikes | Measured answers: Agent SDK isolation, tool restriction, concurrency, cost; SharePoint and Google Drive upload + version behaviour | 7.3, 8.2, 8.3, 15 | Anthropic API key; a test SharePoint site with `Sites.Selected` grant; a test Shared Drive with service account | Written: `2026-10-01-plan-0-spikes.md` |
| 1 | Backend foundation | FastAPI app, PostgreSQL schema + Alembic, local accounts, mandatory TOTP MFA, sessions, lockout, rate limit, CSRF, admin user management, CLI, projects, members, roles | 9, 10 (identity + projects tables), 11 (auth, admin, projects), 13 | Docker (or local PostgreSQL 16), uv | Written: `2026-10-01-plan-1-backend-foundation.md`; implemented on `feat/plan2-local-ingestion` (review carry-overs in `docs/PENDING.md` §5) |
| 2 | Local ingestion | Taxonomy + templates as data, `StorageBackend` interface + local FS adapter + shared contract suite, project storage binding + workspace provisioning, per-project LLM consent, upload API with per-file type selection, zip safety, deterministic converters, `Analyzer` interface with `SkipAnalyzer`/`FakeAnalyzer`, per-item state machine with startup re-queue, deterministic publish under an advisory lock, versions, stubs, gap report, version suggestions, documents API with role/visibility rules | 5, 6 (steps 1–5, 6.4), 7.1 (check), 8.1, 8.4, 9, 10 (`uploads`, `upload_items`, `documents`, `document_versions`, `projects.storage`), 11 (taxonomy, uploads, items, documents, suggest), 13, 14 | Plan 1 merged; Docker/PostgreSQL | Written: `2026-10-01-plan-2-local-ingestion.md` |
| 3 | Cloud storage adapters | SharePoint adapter (Graph, `Sites.Selected`, upload sessions, `driveItem/versions`), Google Drive adapter (service account, resumable uploads, revisions), encrypted `storage_connections`, admin connection endpoints with "Test connection", project binding to a connection + root at creation, contract suite on live storage behind `QC_AGENT_LIVE_STORAGE=1`, storage retry/backoff and health | 8.2, 8.3, 8.5, 8.6, 10 (`storage_connections`), 11 (admin connections), 14 (storage errors), 16 (`/health` connections) | Plan 2 merged; Plan 0 storage spike results | To write after Plan 2 |
| 4 | Agent layer | Claude Agent SDK runner, check and normalise sessions, custom tools, prompts, budgets, timeouts, telemetry, normalising item states, `normalized_drafts`, `agent_runs`, draft endpoints, `*.normalized.md` publish, repository-structure document from a git reference, opt-in live tests | 5.4 (normalised drafts), 5.6, 6.2 (normalise states), 6.3 (steps 3, 6, 7), 7, 10 (`normalized_drafts`, `agent_runs`), 11 (draft endpoints), 15 (agent tests) | Plan 2 merged; Plan 0 agent spike results (independent of Plan 3) | To write after Plan 2 |
| 5 | Frontend | Next.js app: login + MFA enrolment, projects, document browser, upload wizard, My tasks, type confirmation, draft review, gap report, settings, admin; Server-Sent Events endpoint + `events` table with `Last-Event-ID` replay (backend part of this plan) | 12, 11 (SSE), 10 (`events`), 17 (SSE latency) | Plans 1–2 merged (3–4 optional: local storage and the fake/skip analyzer work) | To write after Plan 4 |
| 6 | Deployment & operations | Docker Compose for cloud VM, Caddy with public TLS, proxy headers, backups, runbook, `/health` extensions, staging cleanup job (`STAGING_RETENTION_DAYS`), expired-session cleanup, end-to-end Playwright suite, CI once the platform is chosen | 16, 15 (e2e), 19 | Plans 1–5 merged; cloud VM and DNS | To write last |

Plan 0 has no dependency on Plans 1–2; its storage spike feeds Plan 3 and its agent spike feeds Plan 4. Plans 3 and 4 are independent of each other and can be written in either order once Plan 2 is merged.
```

- [ ] **Step 4: Pending items**

In `docs/PENDING.md`, section 5, tick the two carry-over lines that start with `- [ ] Plan 2, việc đầu tiên:` (the EXPOSE_DOCS line and the failed_logins line become `- [x]`), and in section 4 add after the Plan 1 line:

```markdown
- [x] Lập kế hoạch Plan 2 (local ingestion): `docs/superpowers/plans/2026-10-01-plan-2-local-ingestion.md`; roadmap đổi thứ tự (Plan 3 = cloud storage).
- [ ] Thực thi Plan 2 (owner: Claude; review: Connor).
```

- [ ] **Step 5: Verify the whole branch**

```bash
cd backend
uv run alembic upgrade head && uv run alembic check
uv run pytest -v
uv run ruff check . && uv run ruff format --check . && uv run mypy app
cd .. && pre-commit run --all-files
```

Expected: `No new upgrade operations detected.`; all tests pass; no lint or type errors; pre-commit hooks pass.

- [ ] **Step 6: Commit**

```bash
git add backend/README.md backend/.env.example docs/superpowers/plans/2026-10-01-phase1-roadmap.md docs/PENDING.md
git commit -m "docs: update README, env example, roadmap and pending items for Plan 2"
```
