# QC-Agent — Phase 1 Design: Guided Document Upload & SDLC Knowledge Base

| Field | Value |
|---|---|
| Status | Draft v2 for stakeholder review |
| Date | 2026-10-01 |
| Author | Connor Pham (TECHVIFY) with Claude |
| Phase | 1 of 5 — Ingestion & Structure |
| Revision | v2 replaces v1 (same day): user selects document type at upload; AI verifies, versions and normalises; SharePoint and Google Drive storage; customers as users; internet hosting with MFA |

---

## 1. Purpose and Context

### 1.1 Problem

Project documents at TECHVIFY are scattered across e-mail, chat, personal drives and customer portals. Team members and customers cannot find the current version, and future AI features cannot read them reliably.

### 1.2 Product vision

QC-Agent is a web application where end users (TECHVIFY team members and customer users) upload project documents, state what each document is, and the system converts, verifies, versions, normalises and stores it in one standard structure. Everyone with access to the project reads documents in one place; AI features in later phases read the same structure.

### 1.3 Roadmap

| Phase | Name | Outcome | Status |
|---|---|---|---|
| 1 | Ingestion & Structure | Guided upload; AI verification; versioning; template normalisation; storage in SharePoint or Google Drive; team and customer access | **This spec** |
| 2 | Knowledge Base & Q&A | Index the structured documents; answer questions with citations (decide RAG vs long-context from real data size) | Not started |
| 3 | Test Artefact Generation & Review | Test plan / test cases; traceability; gaps and contradictions | Not started |
| 4 | Test Result Analysis | Reports, logs, bug exports | Not started |
| 5 | Automation Test Execution | Generate and run automation scripts in a sandbox | Not started |

Live Jira / Confluence / Google Docs import connectors remain a separate work item.

### 1.4 The standard structure

| # | Folder | Stage | Document types |
|---|---|---|---|
| 1 | `01-overview` | Why | README, Project Charter, Glossary |
| 2 | `02-requirements` | What | BRD, SRS, Use Cases, User Stories |
| 3 | `03-design` | How | Architecture (C4), ERD, Workflows, API Spec |
| 4 | `04-source` | Build | Repo Structure, Coding Conventions, ADRs |
| 5 | `05-testing` | Verify | Test Plan, Test Cases, Test Reports |
| 6 | `06-deployment` | Run | Deploy Guide, Runbook, Release Notes |

This is an SDLC documentation set ordered Why → What → How → Build → Verify → Run. It has no single official name; related standards are ISO/IEC/IEEE 15289 (life-cycle information items), 29148 (requirements), IEEE 1016 (design descriptions) and ISO/IEC/IEEE 29119-3 (test documentation).

---

## 2. Scope

### 2.1 In scope

- Web application for internal users and customer users; local accounts with mandatory TOTP MFA; internet-facing behind HTTPS.
- Projects bound to one storage connection: **SharePoint / OneDrive** (Microsoft Graph) or **Google Drive** (Drive API); local filesystem backend for development and tests.
- Upload of `docx`, `pdf`, `xlsx`, `pptx`, `md`, `txt`, `html`, `csv`, `zip` (Confluence / Jira exports) and pasted notes; the uploader **selects the document type** for every file.
- Deterministic conversion to Markdown with metadata.
- AI verification of the selected type; mismatch explained to the uploader, who keeps or changes it.
- Version detection and version history ("new version of X").
- AI normalisation into the document type's template as a draft; the uploader approves, edits or discards it.
- Per-document visibility: internal or shared with customer.
- Stubs for missing required types, gap report (internal users only), repository-structure document from a repository reference.
- Progress over Server-Sent Events, cost telemetry, audit log, Docker Compose deployment on a cloud VM.

### 2.2 Out of scope

RAG / Q&A; test artefact generation; content quality review; live import connectors; OCR; SSO; synchronising permissions to SharePoint / Drive; customers opening SharePoint / Drive directly; e-mail notifications; mobile layout; automation test execution.

---

## 3. Decision Log

### 3.1 Stakeholder decisions (confirmed 2026-10-01)

| Topic | Decision |
|---|---|
| First deliverable | Phase 1 only |
| Form factor | Python backend + web UI from the start |
| Agent runtime | Claude Agent SDK (Python) |
| Backend / frontend | FastAPI + Next.js (TypeScript) |
| Database | PostgreSQL 16 in Docker |
| Users | TECHVIFY team **and** customer users |
| Accounts | Local accounts (e-mail + password) |
| Document language | English for folder/file names, generated content and UI |
| Document type at upload | **Selected by the uploader**; AI uses it as the primary signal |
| Type mismatch | AI warns and explains; the **uploader** confirms (keep or change) |
| AI processing | Markdown + metadata; version management; normalisation into the type's template |
| Normalised draft approval | **The uploader** approves, edits or discards |
| Customer visibility | Per document; default internal; documents uploaded by a customer are shared automatically |
| Storage | **Both SharePoint/OneDrive and Google Drive**, selectable by setting per project |
| Direct storage access | Team only; customers use the web app |
| Hosting | Internet-facing cloud server with HTTPS |
| Missing documents | Stubs + gap report; no AI-written content beyond normalisation of uploaded documents |
| Source code input | Store reference and generate directory tree only |
| External LLM API | Claude API permitted; customer confirmation recorded per project |
| Core approach | Deterministic pipeline; agent used only for judgment and drafting via custom tools; no agent file writes |
| MFA | Mandatory TOTP for every account (proposed by TECHVIFY, accepted) |
| CI platform | Not decided |

### 3.2 TECHVIFY assumptions

- One deployment serves all projects; isolation by project membership.
- Tens to low hundreds of documents per project; individual documents up to ~200 pages.
- IT can register an Entra ID application and create a Google Cloud service account.
- Team members already have, or IT grants manually, access to each project's SharePoint site / Shared Drive.
- Vietnamese documents are common; processing must be language-agnostic while output is English.

### 3.3 TECHVIFY recommendations adopted

- AI only for judgment and drafting; every storage write is deterministic backend code.
- The original file is always the source of truth; normalised versions are labelled as AI-generated and approved.
- Taxonomy and templates are data, not code.
- A storage interface with contract tests shared by all adapters.
- Pin the Agent SDK; spike concurrency and isolation first.

---

## 4. Architecture

### 4.1 Components

```
 Internet
    │ HTTPS
 ┌──▼─────┐  /api/*  ┌───────────────────────────────────────────┐
 │ Caddy  │─────────▶│ Backend (FastAPI, Python 3.12)            │
 │ TLS    │  /*      │  api/        REST + SSE                   │
 └──┬─────┘          │  ingestion/  convert, version, publish    │
    ▼                │  agent/      Agent SDK runner + tools     │
 ┌────────┐          │  storage/    StorageBackend adapters ─────┼──▶ SharePoint (Graph API)
 │Frontend│          │  workers/    per-item job runner          │──▶ Google Drive (Drive API)
 │Next.js │          └───────┬────────────────────┬──────────────┘──▶ Local FS (dev/test)
 └────────┘                  ▼                    ▼
                      ┌────────────┐      ┌────────────────┐
                      │ PostgreSQL │      │ Staging volume │  (uploads, converted md,
                      └────────────┘      └────────────────┘   agent session dirs)
                                                  ▲
                         Claude Agent SDK ────────┘ reads staging only; calls api.anthropic.com
```

| Component | Responsibility |
|---|---|
| Frontend (Next.js) | Login + MFA, projects, document browser, upload wizard, confirmation and draft review, gap report, settings, admin |
| Backend (FastAPI) | Auth, authorisation, projects, uploads, SSE; the only component that writes to storage |
| Ingestion | Converters, version matching, stub and gap report generation, publish |
| Agent runner | Claude Agent SDK sessions with custom tools only (verification and normalisation) |
| Storage | `StorageBackend` interface; SharePoint, Google Drive and local adapters |
| Workers | In-process async runner, per-item state in PostgreSQL, semaphore for agent sessions |
| PostgreSQL | Users, MFA, sessions, connections, projects, members, uploads, items, documents, versions, drafts, agent runs, audit |
| Staging volume | Temporary files per upload; cleaned after retention period |

### 4.2 Repository layout

```
QC-Agent/
├── backend/
│   ├── app/
│   │   ├── api/         # auth, mfa, users, connections, projects, documents, uploads, review, taxonomy, health
│   │   ├── core/        # settings, security, crypto (secret encryption), logging
│   │   ├── db/          # SQLAlchemy models, Alembic
│   │   ├── ingestion/   # converters/, versioning.py, publish.py, stubs.py, gaps.py, repo_tree.py, naming.py
│   │   ├── agent/       # analyzer.py, sdk_runner.py, tools.py, prompts.py, fake.py
│   │   ├── storage/     # base.py, sharepoint.py, gdrive.py, localfs.py
│   │   ├── workers/     # runner.py, events.py
│   │   └── schemas/
│   ├── tests/           # unit, storage contract, api, opt-in live tests
│   └── pyproject.toml   # uv, Python 3.12
├── frontend/
├── templates/
│   ├── taxonomy.yaml
│   └── doc-templates/   # one Markdown template per doc type (stubs + normalisation)
├── deploy/              # docker-compose.yml, Caddyfile
├── docs/
├── .env.example
└── README.md
```

---

## 5. Knowledge Base Standard

### 5.1 Layout in the storage backend

Each project has a root location chosen at project creation (a SharePoint document library folder, or a Google Shared Drive folder):

```
<project root>/
├── project.yaml
├── 01-overview/
├── 02-requirements/
│   ├── srs--customer-portal.docx            # original (latest version; older versions in native history)
│   ├── srs--customer-portal.md              # converted Markdown
│   └── srs--customer-portal.normalized.md   # approved AI-normalised version (optional)
├── 03-design/
├── 04-source/
│   └── adr/
├── 05-testing/
│   └── test-reports/
├── 06-deployment/
└── _reports/
    ├── gap-report.md
    └── gap-report.json
```

### 5.2 Taxonomy (`templates/taxonomy.yaml`)

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

Rules: every folder accepts `other`; `multi` types live in `subdir`; `normalize: false` types (machine formats such as OpenAPI files, large test-case spreadsheets, generated repo structure) skip normalisation; `required` drives stubs and completeness.

### 5.3 Naming and metadata

| Item | Name |
|---|---|
| Original | `<doc-type>--<title-slug>.<ext>` |
| Converted | `<doc-type>--<title-slug>.md` |
| Normalised | `<doc-type>--<title-slug>.normalized.md` |
| Stub (missing required type) | `<doc-type>.md` |

Slug: lowercase ASCII, digits, hyphens; Vietnamese diacritics transliterated; ≤ 80 chars; collisions get a numeric suffix. The title defaults to the file name and is editable in the upload wizard.

Converted and normalised Markdown start with frontmatter:

```yaml
---
qc_agent: 2
document_id: "01J9…"
version: 3
doc_type: srs
folder: 02-requirements
title: "Customer Portal SRS"
kind: converted              # converted | normalized | stub
source_file: "srs--customer-portal-srs.docx"
source_sha256: "3f1c…"
uploaded_by: "Nguyen Van A"   # display name only
uploaded_at: "2026-10-01T09:30:00+07:00"
type_selected_by_user: srs
type_check: match             # match | mismatch_kept | mismatch_changed | skipped
language: vi
visibility: internal          # internal | shared
normalized_approved_by: null  # set on normalized files
---
```

Normalised files additionally carry a banner line after the frontmatter: `> AI-normalised from <source file> v<version>, approved by <name> on <date>. The original file is authoritative.`

### 5.4 Versioning

- A **document** is a logical item (doc type + title) within a project; it has one or more **versions**.
- At upload, the uploader chooses *new document* or *new version of an existing document*. The system pre-selects a suggestion when an existing document has the same doc type and a similar title (normalised slug similarity ≥ 0.8) or the agent reports a strong content match.
- A new version overwrites the same paths in storage, so SharePoint and Google Drive keep native version history; the backend records the storage version id for each file in `document_versions`.
- An identical SHA-256 to the current version is rejected as "no change".
- The normalised draft belongs to a specific version; a new version invalidates the previous normalised file only after its own draft is approved (until then the previous normalised file stays, marked "based on v(n-1)").

### 5.5 Stubs and gap report

Stubs are created in storage for missing **required** types only, from `templates/doc-templates/`, with `kind: stub`. A stub is removed when a real document of that type is published, provided the stub's content hash is unchanged. The gap report (Markdown + JSON in `_reports/`, and in the web app) lists, per folder, each type as `present`, `stub` or `missing` with completeness of required types. Visible to internal roles only.

### 5.6 Repository structure

Uploaders may add a repository reference (git URL or server path). The backend shallow-clones into staging, writes `04-source/repo-structure.md` (tree to depth 4 honouring standard ignores, language statistics), and deletes the clone.

---

## 6. Upload Flow

### 6.1 Upload wizard (end-user view)

1. Choose project (only projects where the user may upload).
2. Drop files. For each file choose **document type** from a dropdown grouped by the six folders (search supported), edit the title, choose *new document* or *new version of …* (suggestion pre-selected), and for internal users choose visibility (default internal; customer uploads are forced to shared).
3. "Apply to all" sets type / visibility for a selection.
4. Submit. The user sees per-file progress live and can leave the page; pending actions appear in a "My tasks" list.

### 6.2 Per-item states

```
uploaded → converting → checking ─┬─ match ─────────────────────┐
                                  └─ mismatch → needs_confirmation → (keep | change)
                                                                   ▼
                                                              publishing → published
                                                                   │
                                     normalize enabled for type? ──┤ no → done
                                                                   ▼ yes
                                                    normalizing → draft_ready → (approve | edit+approve | discard)
                                                                                    ▼
                                                                      normalized_published → done
   any step ──▶ failed (with reason, retry button)
```

### 6.3 Steps

1. **Upload**: validation (extensions, `MAX_UPLOAD_FILE_MB` default 50, `MAX_UPLOAD_BATCH_MB` default 500, zip safety: path-traversal rejection, entry and size limits, no nested zips). Zip entries become individual items; the selected type applies to all entries and can be changed per entry. SHA-256 computed.
2. **Convert** (deterministic): `markitdown` for docx/pptx/xlsx/html/pdf, `pymupdf` fallback for pdf, built-in for csv/md/txt. Record pages, characters, heading outline, language. Low text per page → `low_text` warning (likely scanned; no OCR).
3. **Check** (agent): verify the selected type against content; return `match` or `mismatch` with explanation and suggested type; return version-match hints. Low-text items skip the check (`type_check: skipped`).
4. **Confirm** (uploader, only on mismatch): the uploader sees the explanation and chooses keep or change. Nothing else blocks.
5. **Publish** (deterministic): write original and converted Markdown to storage under the target folder, record storage item and version ids, update `documents` / `document_versions`, remove stub if applicable, regenerate gap report, update `project.yaml`. Team members can read the document from this moment.
6. **Normalise** (agent, only for types with `normalize` true): draft the document in the type's template structure, section by section, using only source content. Missing sections are written as `> Not found in source.` Each section lists the source headings / line ranges it was drawn from.
7. **Approve** (uploader): side-by-side view of converted source and draft; the uploader approves, edits the draft in a Markdown editor then approves, or discards. On approval the normalised file is written to storage.

### 6.4 Concurrency and idempotency

Publishing for a project runs under a PostgreSQL advisory lock per project. Each storage write is keyed by (document id, version, kind); retries detect the existing version by SHA-256 and do not create duplicate versions.

---

## 7. Agent Design

### 7.1 Interface

```python
class Analyzer(Protocol):
    async def check(self, batch: CheckBatch, emit: EventSink) -> CheckResult
    async def normalize(self, item: NormalizeInput, emit: EventSink) -> NormalizeResult
```

Production implementation uses the Claude Agent SDK; tests use a scripted fake.

### 7.2 Sessions

- **Check session**: one per upload batch (many items), short.
- **Normalise session**: one per item, longer; runs only after publish so it never delays team access.

### 7.3 SDK configuration (common)

```python
options = ClaudeAgentOptions(
    cwd=str(staging_dir),
    system_prompt=prompt,
    model=project.settings.model,                 # default "claude-opus-5"
    mcp_servers={"qc": create_sdk_mcp_server(name="qc", version="1.0.0", tools=tools)},
    allowed_tools=[f"mcp__qc__{t}" for t in tool_names],
    disallowed_tools=["Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
                      "Glob", "Grep", "WebSearch", "WebFetch", "Task", "TodoWrite"],
    permission_mode="dontAsk",
    max_turns=turn_cap,
    max_budget_usd=budget,
    setting_sources=[],
    env={"ANTHROPIC_API_KEY": settings.anthropic_api_key,
         "CLAUDE_CONFIG_DIR": str(staging_dir / ".claude")},
)
```

Wrapped in `asyncio.timeout(...)`. To verify in the spike: `setting_sources=[]` isolation, `CLAUDE_CONFIG_DIR` relocation, concurrent sessions in one process.

### 7.4 Custom tools

| Session | Tool | Purpose |
|---|---|---|
| Check | `list_items` | id, file name, selected type, title, outline, preview, existing documents of the same project (type + title) for version hints |
| Check | `read_item` | numbered slice, ≤ 400 lines |
| Check | `submit_check` | `{item_id, verdict: match|mismatch, suggested_doc_type?, explanation ≤ 400, version_of_document_id?, confidence}`; validated against taxonomy |
| Normalise | `get_template` | section list of the type's template with guidance per section |
| Normalise | `read_source` | numbered slice of the converted Markdown |
| Normalise | `submit_section` | `{section_id, markdown, source_refs[], not_found: bool}`; validated (known section, size limit) |
| Normalise | `finish_draft` | `{notes ≤ 600}`; fails if any template section is unsubmitted |

No built-in file, shell, web or subagent tools. The backend assembles the draft from submitted sections.

### 7.5 Prompt rules (normalise)

Use only content present in the source; do not invent requirements, numbers, names or decisions; translate to English while preserving identifiers, codes and quoted UI text; keep requirement ids; mark missing sections explicitly; list source references for every section.

### 7.6 Limits

Per-project settings: `model`, `check_budget_usd` (default 1.0 per batch), `normalize_budget_usd` (default 2.0 per item). Global: `AGENT_TIMEOUT_SECONDS` (check 600, normalise 1200), `AGENT_CONCURRENCY` (default 1 until the spike). Agent failures leave the item usable: check failure → `type_check: skipped`, item publishes with the user's type; normalise failure → item stays published without a normalised file, with retry.

---

## 8. Storage Backends

### 8.1 Interface

```python
class StorageBackend(Protocol):
    async def ensure_folder(self, path: str) -> None
    async def put_file(self, path: str, data: bytes, content_type: str) -> StoredFile   # returns item_id, version_id, web_url
    async def get_file(self, path: str) -> bytes
    async def list_versions(self, path: str) -> list[StoredVersion]
    async def get_version(self, path: str, version_id: str) -> bytes
    async def move_to_trash(self, path: str) -> None
    async def health(self) -> HealthStatus
```

All adapters pass one shared contract test suite (run against local FS always; against real SharePoint / Drive in opt-in live tests).

### 8.2 SharePoint / OneDrive adapter

- Microsoft Graph, app-only (client credentials) via `msal`.
- Permission: `Sites.Selected`, granted by IT per SharePoint site (least privilege) rather than tenant-wide `Sites.ReadWrite.All`.
- Project root = site + document library (drive) + folder path. Upload sessions for files > 4 MB. Versions via `driveItem/versions`.

### 8.3 Google Drive adapter

- Drive API v3 with a service account (`google-api-python-client`); the service account is added as Content manager on each Shared Drive.
- Project root = Shared Drive id + folder path; folder paths resolved to ids and cached. `supportsAllDrives=true` on every call. Resumable uploads; new versions via `files.update` on the existing file id; versions via `revisions` (with `keepForever` on published versions).

### 8.4 Local FS adapter

For development and CI; stores under `LOCAL_STORAGE_ROOT`; versions as `.versions/<path>/<n>`.

### 8.5 Connections

Admins create **storage connections** (type, display name, credentials). Secrets (client secret, service-account JSON) are encrypted at rest with a key from `SECRET_ENCRYPTION_KEY` (Fernet). A project is bound to one connection and one root location at creation; changing it later is out of scope for Phase 1.

### 8.6 Access to storage

Team members open the SharePoint site / Shared Drive directly using permissions IT grants. The system does not change storage permissions. Customers never receive storage access; they read through the web app, which streams files from storage after checking visibility.

---

## 9. Users, Roles and Visibility

| Role | Scope | Can |
|---|---|---|
| `admin` | global | manage users, storage connections, all projects |
| `owner` | project | members, settings, visibility of any document, archive project |
| `editor` | project | upload, confirm/approve own items, change visibility of internal documents |
| `viewer` | project | read all documents, gap report |
| `client` | project | upload (always shared), confirm/approve own items, read **shared** documents only; no gap report, no settings |

Users have `account_type` `internal` or `customer`; customer accounts can only hold the `client` role. Visibility per document: `internal` (default) or `shared`; documents uploaded by a client are `shared` and cannot be made internal by the client.

---

## 10. Data Model (PostgreSQL 16)

| Table | Key columns |
|---|---|
| `users` | id, email, password_hash (Argon2id), display_name, account_type, is_admin, must_change_password, mfa_secret_enc, mfa_enabled, recovery_codes_hash[], failed_logins, locked_until, is_active |
| `auth_sessions` | id, user_id, token_hash, mfa_verified, expires_at, revoked_at, ip, user_agent |
| `storage_connections` | id, type (`sharepoint`/`gdrive`/`localfs`), name, config jsonb, secret_enc, created_by |
| `projects` | id, slug, name, client_name, storage_connection_id, storage_root jsonb, settings jsonb, created_by, archived_at |
| `project_members` | project_id, user_id, role |
| `uploads` | id, project_id, uploaded_by, repo_ref, created_at |
| `upload_items` | id, upload_id, original_name, ext, size, sha256, staging_path, selected_doc_type, final_doc_type, title, intent (`new`/`version`), target_document_id, visibility, status, type_check, check_explanation, suggested_doc_type, conversion_meta jsonb, error |
| `documents` | id, project_id, folder_id, doc_type, title, slug, visibility, current_version, is_stub, created_by, created_at |
| `document_versions` | id, document_id, version, sha256, original_path, original_storage_version, markdown_path, markdown_storage_version, markdown_text, uploaded_by, upload_item_id, created_at |
| `normalized_drafts` | id, document_version_id, status (`generating`/`ready`/`approved`/`discarded`/`failed`), sections jsonb, markdown, edited_by, approved_by, approved_at, storage_path, storage_version |
| `agent_runs` | id, kind (`check`/`normalize`), upload_id, upload_item_id, session_id, model, status, cost_usd, input_tokens, output_tokens, turns, error, started_at, ended_at |
| `events` | id, upload_id, type, payload jsonb, created_at (SSE replay) |
| `audit_log` | id, at, user_id, project_id, action, target_type, target_id, details jsonb |

`document_versions.markdown_text` keeps converted text in PostgreSQL so later phases can index without re-downloading from storage.

---

## 11. REST API (`/api/v1`)

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/mfa/verify`, `POST /auth/mfa/enroll`, `POST /auth/mfa/confirm`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/change-password` |
| Admin | `GET/POST/PATCH /users`, `POST /users/{id}/reset-password`, `POST /users/{id}/reset-mfa`, `GET/POST/PATCH /storage-connections`, `POST /storage-connections/{id}/test` |
| Projects | `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}`, `GET/PUT /projects/{id}/members`, `GET /projects/{id}/gap-report` |
| Documents | `GET /projects/{id}/documents` (filter by folder, type, visibility, text), `GET /documents/{id}`, `GET /documents/{id}/versions`, `GET /documents/{id}/versions/{v}/original`, `GET /documents/{id}/versions/{v}/markdown`, `GET /documents/{id}/normalized`, `PATCH /documents/{id}` (title, visibility) |
| Uploads | `POST /projects/{id}/uploads` (multipart + per-file metadata), `GET /uploads/{id}`, `GET /uploads/{id}/events` (SSE), `GET /me/tasks` |
| Items | `POST /upload-items/{id}/confirm-type`, `POST /upload-items/{id}/retry`, `GET /upload-items/{id}/draft`, `PUT /upload-items/{id}/draft`, `POST /upload-items/{id}/draft/approve`, `POST /upload-items/{id}/draft/discard` |
| Suggest | `GET /projects/{id}/version-suggestions?doc_type=&title=` |
| Meta | `GET /taxonomy`, `GET /health` |

Every document endpoint enforces role and visibility; client users receive 404 for internal documents.

---

## 12. Frontend Screens

1. Login → MFA (enrolment with QR + recovery codes on first login).
2. Projects list.
3. Project home: **Documents** browser grouped by the six folders (type, title, version, uploader, date, visibility badge, "normalised" badge; search and filters); document page with tabs Original preview / Markdown / Normalised / Versions.
4. **Upload wizard** (section 6.1) with live per-file progress.
5. **My tasks**: type confirmations and drafts awaiting approval.
6. **Type confirmation** dialog: selected type, AI explanation, suggested type, keep / change.
7. **Draft review**: side-by-side source and draft, section source references, Markdown editor, approve / discard.
8. Gap report (internal only).
9. Project settings (owner): members, model, budgets, storage root (read-only after creation).
10. Admin: users, storage connections (with "Test connection").

English UI; strings in one messages file.

---

## 13. Security

- **Internet exposure**: Caddy with automatic public TLS certificates; HSTS; security headers; only ports 80/443 open; database not exposed.
- **Authentication**: Argon2id; admin-created accounts; forced password change; **mandatory TOTP MFA** with one-time recovery codes; admin MFA reset; lockout after 5 failures for 15 minutes; per-IP rate limiting on login and MFA endpoints.
- **Sessions**: opaque token in `HttpOnly; Secure; SameSite=Lax` cookie; server-side session (8 h, revocable); CSRF header check on state-changing requests.
- **Authorisation**: role + visibility checks in one dependency used by every document route; tests cover client access to internal documents.
- **Secrets**: `.env` on the server; storage secrets encrypted in DB; least-privilege Graph permission (`Sites.Selected`); service account limited to designated Shared Drives; gitleaks pre-commit.
- **Uploads**: type and size limits, zip safety, file names sanitised; no execution of uploaded content; files streamed to clients with `Content-Disposition: attachment` and correct content type.
- **Agent**: no built-in tools; staging-only `cwd`; transcripts in staging, deleted on cleanup.
- **Logging**: no document content, prompts or secrets in logs.
- **Data processing**: per-project confirmation that converted document text may be sent to the Claude API, recorded in `audit_log` with the confirming person, required before the first upload.
- **Archive**: archiving a project hides it in the web app; storage content is left untouched for IT to manage.

---

## 14. Error Handling

| Failure | Behaviour |
|---|---|
| Invalid file / limits | Rejected at upload per file |
| Conversion failure | Item `failed` with reason; retry or re-upload |
| Low-text PDF | Published with warning; check and normalise skipped |
| Check agent failure | `type_check: skipped`; item publishes with user's type; logged |
| Storage error (auth, throttling 429, 5xx) | Retry with exponential backoff honouring `Retry-After`; after limit item `failed` with retry button; connection health shown in admin |
| Storage auth expired / revoked | `/health` and admin page show failing connection; uploads to affected projects blocked with a clear message |
| Normalise failure / budget | Draft `failed`; document stays published; retry |
| Draft never approved | Stays in My tasks; no effect on published document |
| Concurrent publishes in one project | Serialised by advisory lock |
| SSE disconnect | Replay from `Last-Event-ID` |

---

## 15. Testing Strategy

- **Spike first** (throwaway): Agent SDK isolation and concurrency (section 7.3); Graph and Drive upload + version behaviour on a test site / Shared Drive.
- **Unit**: converters, naming and slugs, zip safety, taxonomy, version suggestion, stubs, gap report, tool validation, draft assembly, visibility rules.
- **Storage contract suite** run on local FS in every test run; on SharePoint and Google Drive when `QC_AGENT_LIVE_STORAGE=1`.
- **Agent**: scripted fake for pipeline tests; opt-in live test with a tiny fixture set and a 0.50 USD cap.
- **API**: httpx + PostgreSQL container; role/visibility matrix tests (every role × internal/shared document).
- **Frontend**: Vitest + Testing Library; Playwright end-to-end on Docker Compose with local FS storage: login + MFA → upload with type → mismatch confirm → publish → draft approve → client sees shared document only.
- **Quality gates**: ruff, mypy, ESLint, tsc, gitleaks; CI platform to be confirmed.
- Fixtures are synthetic; no customer data in the repository.

---

## 16. Deployment and Operations

- Cloud VM (2 vCPU / 4 GB RAM to start) with a public DNS name. Docker Compose services: `db`, `backend`, `frontend`, `caddy`. Volumes: `pgdata`, `staging`, `caddy_data`.
- Backups: nightly `pg_dump` to off-host storage; documents themselves are in SharePoint / Drive, covered by their own retention.
- Runbook (written in Phase 1): first admin creation, storage connection setup per platform, rotating Anthropic key / client secret / service account key, restore, stuck items.
- `/health`: DB, staging writability, Anthropic key presence, Agent SDK import, each storage connection.

### 16.1 Configuration (`.env`)

| Variable | Default |
|---|---|
| `DATABASE_URL`, `SESSION_SECRET`, `SECRET_ENCRYPTION_KEY`, `ANTHROPIC_API_KEY`, `PUBLIC_BASE_URL` | required |
| `STAGING_ROOT` | `./staging` |
| `LOCAL_STORAGE_ROOT` | `./workspace` (dev only) |
| `MAX_UPLOAD_FILE_MB` / `MAX_UPLOAD_BATCH_MB` | 50 / 500 |
| `STAGING_RETENTION_DAYS` | 7 |
| `AGENT_MODEL_DEFAULT` | `claude-opus-5` |
| `AGENT_CHECK_BUDGET_USD` / `AGENT_NORMALIZE_BUDGET_USD` | 1.0 / 2.0 |
| `AGENT_CONCURRENCY` | 1 |
| `COOKIE_SECURE` | `true` |

---

## 17. Non-Functional Targets

| Metric | Target |
|---|---|
| Upload → published (10 files, ≤ 50 pages each, no mismatch) | < 3 minutes |
| Normalised draft per document (≤ 50 pages) | < 10 minutes |
| Document list load | < 1 second for 500 documents |
| Concurrent users | 30 |
| SSE latency | < 2 seconds |

---

## 18. Risks, Dependencies, Items Requiring Confirmation

### 18.1 Risks

| Risk | Mitigation |
|---|---|
| Normalised content misrepresents the source | Source-only rule, section source references, explicit "Not found in source", uploader approval, banner stating the original is authoritative |
| Customer approves an incorrect normalised draft | Original always kept and linked; internal owners can discard a normalised version later |
| Two storage platforms double integration and test effort | One interface + shared contract suite; local adapter for most tests |
| Graph / Drive throttling | Backoff with `Retry-After`; batch uploads serialised per project |
| Internet exposure | MFA, rate limits, lockout, minimal open ports, security headers |
| Agent SDK 0.x | Pinned; behind interface; spike |
| Customer data to external LLM | Per-project confirmation |
| Scanned PDFs | Warning; OCR deferred |

### 18.2 Dependencies

- Entra ID app registration with `Sites.Selected` and per-site grants (IT).
- Google Cloud service account with Drive API enabled, added to Shared Drives (IT / Workspace admin).
- Cloud VM, public DNS name, outbound access to Graph, Drive and Anthropic APIs.
- Dedicated Anthropic API key with a spending limit.
- Docker on the dev machine (not installed today); Python 3.12 via uv (system Python is 3.9).

### 18.3 To confirm

- CI platform.
- Wording of the customer data-processing confirmation.
- Cloud provider, VM size and backup destination.
- Whether customers may see the version history of shared documents (assumed yes).

---

## 19. Acceptance Criteria

1. Admin creates an internal user and a customer user; both must change password and enrol MFA; login without MFA is impossible.
2. An admin configures one SharePoint and one Google Drive connection; "Test connection" succeeds for both; one project is created on each.
3. An editor uploads the 10-file sample set selecting a type per file; every file is converted or fails with a reason; files whose type matches are published without any further action.
4. A file uploaded with a deliberately wrong type is flagged with an explanation; the uploader changes the type; the file is published in the correct folder.
5. Published files appear in the correct folder in SharePoint / Drive with the naming convention and frontmatter; the gap report and stubs reflect the published set.
6. Uploading a changed SRS as "new version" creates version 2 in the web app and a new native version in storage; uploading an identical file is rejected as no change.
7. A normalised draft follows the SRS template, marks absent sections "Not found in source", lists source references; after the uploader edits and approves, `*.normalized.md` appears in storage with the banner.
8. The customer user sees only shared documents (including those they uploaded) and receives 404 for an internal document URL; they cannot see the gap report.
9. The agent configuration test proves no file-writing, shell or web tools are available.
10. The stack runs on a cloud VM via Docker Compose behind a valid public TLS certificate; `/health` is green; the secret scan reports no findings.

---

## 20. Glossary

| Term | Meaning |
|---|---|
| Document | Logical item (type + title) with versions |
| Version | One uploaded revision of a document: original + converted Markdown (+ normalised) |
| Type check | Agent verification of the uploader's selected document type |
| Normalised version | AI draft in the type's template, published after uploader approval |
| Storage connection | Configured SharePoint or Google Drive credentials |
| Visibility | `internal` or `shared` with customer users |
| Stub | Template placeholder for a missing required document type |
