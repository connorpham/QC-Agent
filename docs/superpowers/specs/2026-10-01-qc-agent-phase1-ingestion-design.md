# QC-Agent — Phase 1 Design: Document Ingestion & SDLC Knowledge Base Structure

| Field | Value |
|---|---|
| Status | Draft for stakeholder review |
| Date | 2026-10-01 |
| Author | Connor Pham (TECHVIFY) with Claude |
| Phase | 1 of 5 — Ingestion & Structure |
| Supersedes | none |

---

## 1. Purpose and Context

### 1.1 Product vision

QC-Agent is an internal TECHVIFY **Tester Agent**: a web application that helps QA/test engineers work on customer projects by reading the project's documentation and, in later phases, answering questions, generating test plans and test cases, reviewing document quality, analysing test results, and running automation tests.

Every capability depends on one foundation: the project's documents must be organised in a predictable, machine-readable structure. Phase 1 builds that foundation.

### 1.2 Roadmap (agreed 2026-10-01)

| Phase | Name | Outcome | Status |
|---|---|---|---|
| 1 | Ingestion & Structure | Upload project data; convert; classify into the 6-folder SDLC structure; stubs + gap report | **This spec** |
| 2 | Knowledge Base & Q&A | Index the structured workspace; answer questions with citations. Decide RAG vs long-context here, based on real data size | Not started |
| 3 | Test Artefact Generation & Review | Test plan / test cases from requirements and design; requirement-to-test traceability; detect gaps and contradictions | Not started |
| 4 | Test Result Analysis | Read test reports, logs, bug exports; summarise and classify | Not started |
| 5 | Automation Test Execution | Generate and run automation scripts in a sandbox with human approval | Not started |

Live connectors to Jira / Confluence / Google Docs APIs are a separate work item; Phase 1 accepts exported files only.

### 1.3 Phase 1 goal

When a user provides project data (files, pasted notes, a source-repository reference), the system produces a per-project workspace that follows the standard 6-folder structure below, with every document placed in the right folder under a canonical name, stub templates for missing document types, and a gap report. A human approves the classification before any file is placed.

| # | Folder | Stage | Document types |
|---|---|---|---|
| 1 | `01-overview` | Why | README, Project Charter, Glossary |
| 2 | `02-requirements` | What | BRD, SRS, Use Cases, User Stories |
| 3 | `03-design` | How | Architecture (C4), ERD, Workflows, API Spec |
| 4 | `04-source` | Build | Repo Structure, Coding Conventions, ADRs |
| 5 | `05-testing` | Verify | Test Plan, Test Cases, Test Reports |
| 6 | `06-deployment` | Run | Deploy Guide, Runbook, Release Notes |

This structure is an SDLC documentation set ordered Why → What → How → Build → Verify → Run. It has no single official name; the closest standards are ISO/IEC/IEEE 15289 (life-cycle information items), ISO/IEC/IEEE 29148 (requirements/SRS), IEEE 1016 (design descriptions) and ISO/IEC/IEEE 29119-3 (test documentation).

---

## 2. Scope

### 2.1 In scope (Phase 1)

- Multi-user web application with local accounts and per-project roles.
- Project creation; configurable workspace root (default inside the repo, git-ignored).
- Upload of `docx`, `pdf`, `xlsx`, `pptx`, `md`, `txt`, `html`, `csv`, and `zip` (Confluence / Jira exports); pasted text notes; source-repository reference (server path or git URL).
- Deterministic conversion to Markdown; duplicate detection by SHA-256.
- Classification proposals produced by a Claude Agent SDK session that can only read converted documents and submit proposals through custom tools; filename heuristics as fallback.
- Human review and approval UI; deterministic, idempotent apply step.
- Stub templates for missing document types; gap report (Markdown + JSON); `project.yaml`; `04-source/repo-structure.md` generated from the repository reference (tree + language statistics, no code analysis).
- Job progress over Server-Sent Events; cost and token telemetry per agent run; audit log.
- Docker Compose deployment with HTTPS reverse proxy; runbook.

### 2.2 Out of scope (Phase 1)

RAG indexing and Q&A; test plan / test case generation; document content review; live Jira / Confluence / Google Docs connectors; OCR for scanned PDFs; AI-drafted document content (stubs are templates only); SSO; e-mail notifications; mobile layout; automated test execution; multi-tenant isolation beyond project membership.

---

## 3. Decision Log

Decisions taken with the stakeholder on 2026-10-01, separated as required by TECHVIFY practice.

### 3.1 Stakeholder decisions (confirmed)

| Topic | Decision |
|---|---|
| First deliverable | Phase 1 only; later phases designed not to be blocked |
| Form factor | Python backend with web UI from the start |
| Agent runtime | Claude Agent SDK (Python) |
| Backend / frontend | FastAPI + Next.js (TypeScript) |
| Database | PostgreSQL 16 in Docker |
| Users | Internal TECHVIFY team; login required; local accounts (e-mail + password) |
| Document language | English for folder names, file names, generated documents and UI |
| Missing documents | Create stub templates + gap report; no AI-written content in Phase 1 |
| Workspace location | Configurable path; default `./workspace/<project-slug>/`, git-ignored |
| Source code input | Store reference and generate directory tree only |
| External LLM API | Claude API (Anthropic) is permitted; customer confirmation required per project before real data is ingested |
| Core approach | **Option A**: deterministic pipeline; agent used only for judgment (classification) via custom tools; human approval before apply |
| CI platform | Not decided; recorded as an item requiring confirmation |

### 3.2 TECHVIFY assumptions (to be corrected if wrong)

- One deployment serves the whole team; projects are isolated by membership, not by tenant.
- Document sets per project are small to medium (tens to low hundreds of files).
- The server has outbound HTTPS access to `api.anthropic.com`.
- Vietnamese-language documents are common; conversion and classification must be language-agnostic.
- The team is comfortable operating Docker Compose on an internal Linux VM.

### 3.3 TECHVIFY recommendations adopted

- Use AI only where judgment is needed (classification); keep every filesystem effect deterministic and testable.
- Define the folder standard as data (`taxonomy.yaml`) so the standard can change without code changes.
- Cap agent spend and turns per job; record cost per run.
- Pin the Agent SDK version and isolate it behind an interface; run a spike first because concurrency behaviour is not documented.

---

## 4. Architecture

### 4.1 Components

```
┌──────────────┐  HTTPS  ┌──────────┐   /api/*    ┌──────────────────────────────┐
│  Browser     │────────▶│  Caddy   │────────────▶│  Backend (FastAPI, Python)   │
│  Next.js app │         │  (TLS,   │   /*        │  ├─ api/        REST + SSE   │
└──────────────┘         │  proxy)  │──┐          │  ├─ ingestion/  deterministic│
                         └──────────┘  │          │  ├─ agent/      SDK runner   │
                                       ▼          │  └─ workers/    job queue    │
                                ┌────────────┐    └───────┬──────────────┬───────┘
                                │ Frontend   │            │              │
                                │ (Next.js)  │            ▼              ▼
                                └────────────┘    ┌────────────┐  ┌──────────────┐
                                                  │ PostgreSQL │  │ Workspace    │
                                                  │ 16         │  │ volume       │
                                                  └────────────┘  └──────────────┘
                                                                        │
                                            Claude Agent SDK subprocess │ reads job staging only
                                            ───────────────────────────▶│ (converted markdown)
                                            calls api.anthropic.com
```

| Component | Responsibility |
|---|---|
| **Frontend (Next.js, TypeScript)** | Login, project list, project detail (tree, gap report, history, members/settings), new ingestion, review, job result, user admin. Consumes REST + SSE. |
| **Backend (FastAPI, Python 3.12)** | Authentication, authorisation, projects, jobs, review, SSE; owns every filesystem write. |
| **Ingestion pipeline** (`backend/app/ingestion/`) | Converters, heuristics, scaffolding, stubs, gap report, apply, repo tree. Pure Python, no LLM. |
| **Agent runner** (`backend/app/agent/`) | One Claude Agent SDK session per job, custom tools only, strict limits. Behind an `Analyzer` interface. |
| **Workers** (`backend/app/workers/`) | In-process async job runner with a semaphore for agent sessions; job state persisted in PostgreSQL; designed to be moved to a separate process later without API changes. |
| **PostgreSQL 16** | Users, sessions, projects, members, jobs, source files, proposals, agent runs, documents index, audit log. |
| **Workspace volume** | Knowledge base root; one directory per project. |

### 4.2 Repository layout

```
QC-Agent/
├── backend/
│   ├── app/
│   │   ├── api/           # routers: auth, users, projects, documents, jobs, review, taxonomy, health
│   │   ├── core/          # settings (pydantic-settings), security, logging, errors
│   │   ├── db/            # SQLAlchemy 2.x models, session, Alembic migrations
│   │   ├── ingestion/     # converters/, heuristics.py, scaffold.py, stubs.py, gaps.py, apply.py, repo_tree.py, paths.py
│   │   ├── agent/         # analyzer.py (interface), sdk_analyzer.py, tools.py, prompts.py, fake_analyzer.py
│   │   ├── workers/       # queue.py, job_runner.py, events.py (SSE bus)
│   │   └── schemas/       # Pydantic request/response models
│   ├── tests/             # unit, api, integration (opt-in)
│   ├── alembic.ini
│   └── pyproject.toml     # managed with uv; Python 3.12 pinned
├── frontend/              # Next.js app router, TypeScript, generated API client
├── templates/
│   ├── taxonomy.yaml      # the 6-folder standard (data, not code)
│   ├── heuristics.yaml    # filename/heading rules for fallback classification
│   └── stubs/             # one Markdown template per doc type
├── workspace/             # default knowledge-base root (git-ignored)
├── docs/
│   └── superpowers/specs/ # this document and future specs/plans
├── deploy/
│   ├── Caddyfile
│   └── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

### 4.3 Runtime topology

- **Development**: backend via `uv run`, frontend via `pnpm dev`, PostgreSQL via `docker compose up db`.
- **Team server**: `docker compose up` brings up `db`, `backend`, `frontend`, `caddy`. Secrets in `.env` on the server only.

---

## 5. Knowledge Base Standard

### 5.1 Per-project workspace layout

```
<WORKSPACE_ROOT>/<project-slug>/
├── project.yaml
├── 01-overview/
├── 02-requirements/
├── 03-design/
├── 04-source/
│   └── adr/
├── 05-testing/
│   └── test-reports/
├── 06-deployment/
├── _sources/            # original uploaded files, named <sha256>.<ext>, never modified
├── _reports/            # gap-report.md, gap-report.json, ingestion-log.md
└── _jobs/               # staging per job (deleted after STAGING_RETENTION_DAYS)
    └── <job-id>/
        ├── raw/         # uploaded files as received
        ├── converted/   # <source-file-id>.md
        ├── manifest.json
        └── .claude/     # Agent SDK config/session dir for this job (CLAUDE_CONFIG_DIR)
```

### 5.2 `templates/taxonomy.yaml`

The standard is data. The loader validates the file at startup and exposes it through `GET /api/v1/taxonomy`.

```yaml
version: 1
folders:
  - id: overview
    dir: 01-overview
    stage: Why
    description: Why the project exists, who is involved, shared vocabulary.
    doc_types:
      - { id: readme,          title: Project README,     required: true,  template: readme.md }
      - { id: project-charter, title: Project Charter,    required: true,  template: project-charter.md }
      - { id: glossary,        title: Glossary,           required: false, template: glossary.md }
  - id: requirements
    dir: 02-requirements
    stage: What
    description: What the system must do, from business and system perspectives.
    doc_types:
      - { id: brd,          title: Business Requirements Document, required: true,  template: brd.md }
      - { id: srs,          title: Software Requirements Specification, required: true, template: srs.md }
      - { id: use-cases,    title: Use Cases,    required: false, template: use-cases.md }
      - { id: user-stories, title: User Stories, required: false, template: user-stories.md }
  - id: design
    dir: 03-design
    stage: How
    description: How the system is built: architecture, data, flows, interfaces.
    doc_types:
      - { id: architecture-c4, title: Architecture (C4), required: true,  template: architecture-c4.md }
      - { id: erd,             title: Entity Relationship Diagram, required: false, template: erd.md }
      - { id: workflows,       title: Workflows, required: false, template: workflows.md }
      - { id: api-spec,        title: API Specification, required: false, template: api-spec.md, keep_original: true }
  - id: source
    dir: 04-source
    stage: Build
    description: Source code organisation, conventions, architecture decisions.
    doc_types:
      - { id: repo-structure,     title: Repository Structure, required: true,  template: repo-structure.md }
      - { id: coding-conventions, title: Coding Conventions,   required: false, template: coding-conventions.md }
      - { id: adr,                title: Architecture Decision Record, required: false, template: adr.md, multi: true, subdir: adr }
  - id: testing
    dir: 05-testing
    stage: Verify
    description: How the system is verified.
    doc_types:
      - { id: test-plan,   title: Test Plan,   required: true,  template: test-plan.md }
      - { id: test-cases,  title: Test Cases,  required: true,  template: test-cases.md }
      - { id: test-report, title: Test Report, required: false, template: test-report.md, multi: true, subdir: test-reports }
  - id: deployment
    dir: 06-deployment
    stage: Run
    description: How the system is deployed and operated.
    doc_types:
      - { id: deploy-guide,  title: Deployment Guide, required: true,  template: deploy-guide.md }
      - { id: runbook,       title: Runbook,          required: true,  template: runbook.md }
      - { id: release-notes, title: Release Notes,    required: false, template: release-notes.md }
```

Rules:

- Every folder implicitly accepts the doc type `other` for documents that belong to the stage but match no standard type.
- `multi: true` types live in `subdir` and never get a single stub; the gap report counts them as present when at least one file exists.
- `keep_original: true` types also copy the original file (for example `openapi.yaml`) next to the Markdown description.
- `required` drives the completeness percentage; optional types are listed separately in the gap report.

### 5.3 File naming and frontmatter

| Case | Path |
|---|---|
| Stub for a missing type | `<dir>/<doc-type>.md` |
| Ingested document | `<dir>/<doc-type>--<original-name-slug>.md` |
| Ingested `multi` type | `<dir>/<subdir>/<doc-type>--<original-name-slug>.md` |
| Ingested `other` | `<dir>/other--<original-name-slug>.md` |
| Original file | `_sources/<sha256>.<ext>` |

Slug rules: lowercase ASCII letters, digits and hyphens; Vietnamese diacritics transliterated; maximum 80 characters; collision resolved with a numeric suffix.

Every Markdown file written by the system starts with YAML frontmatter:

```yaml
---
qc_agent: 1
doc_type: srs
folder: 02-requirements
title: "Software Requirements Specification v2.1"
stub: false
source_name: "SRS_v2.1_final.docx"
source_sha256: "3f1c…"
source_path: "_sources/3f1c….docx"
converter: "markitdown/docx"
language: "vi"
classified_by: "agent"          # agent | heuristic | user
confidence: 0.92
reviewed_by: "Connor Pham"       # display name, never e-mail
reviewed_at: "2026-10-01T09:30:00+07:00"
job_id: "01J9…"
---
```

Stubs carry `stub: true`, `classified_by: "system"`, and a body made of the template's section headings with `> To be completed.` markers. The SHA-256 of a stub at creation time is stored in the `documents` table; a stub is only auto-removed if its current hash still equals that value (the user has not edited it).

### 5.4 `project.yaml`

```yaml
name: "Customer Portal"
slug: customer-portal
client: "ACME Corp"            # optional
created_at: "2026-10-01T09:00:00+07:00"
taxonomy_version: 1
language: "en"
summary: ""                    # optional, agent-proposed, user-confirmed
source_repos:
  - ref: "https://git.example.com/acme/portal.git"
    recorded_at: "2026-10-01T09:40:00+07:00"
```

### 5.5 Gap report

`_reports/gap-report.md` (human) and `_reports/gap-report.json` (machine) are regenerated on every apply.

```json
{
  "generated_at": "2026-10-01T09:45:00+07:00",
  "job_id": "01J9…",
  "completeness_required": 0.6,
  "folders": [
    {
      "id": "requirements", "dir": "02-requirements",
      "required_total": 2, "required_present": 1,
      "doc_types": [
        { "id": "brd", "required": true,  "status": "present", "files": ["brd--acme-brd-v1.md"] },
        { "id": "srs", "required": true,  "status": "stub",    "files": ["srs.md"] },
        { "id": "use-cases", "required": false, "status": "missing", "files": [] }
      ]
    }
  ]
}
```

Status values: `present` (≥1 non-stub file), `stub` (only the stub exists), `missing` (nothing). Optional types are never `stub` unless a user asked for one; Phase 1 creates stubs for **required** types only, to keep the workspace uncluttered.

### 5.6 `04-source/repo-structure.md`

Generated when a repository reference is given: the reference, generation time, a directory tree to a configurable depth (default 4) honouring `.gitignore`-style ignore rules (`node_modules`, `.git`, `dist`, `build`, `venv`, binaries), file counts and percentage by language inferred from extensions, and the top-level files list. For a git URL the system does a shallow clone into the job staging area, generates the document, and deletes the clone. No file contents are copied into the workspace.

---

## 6. Ingestion Job Lifecycle

### 6.1 States

```
created ─▶ converting ─▶ analyzing ─▶ awaiting_review ─▶ applying ─▶ completed
   │            │            │               │               │
   └────────────┴────────────┴───────────────┴───────────────┴──▶ failed
                                             └──▶ cancelled (user action before apply)
```

Transitions are persisted in `ingestion_jobs.status`; every transition appends an `audit_log` row and emits an SSE event.

### 6.2 Step 1 — Create

- Input: project (existing or new), 1..N files, optional pasted notes (saved as `notes-<n>.md`), optional repository reference.
- Validation: allowed extensions; per-file size ≤ `MAX_UPLOAD_FILE_MB` (default 50); per-job total ≤ `MAX_UPLOAD_JOB_MB` (default 500); file names sanitised; symlinks rejected.
- Zip handling: extract into `raw/` with path-traversal protection (reject entries resolving outside the target), entry-count and total-size limits, nested zips not extracted. Confluence HTML exports and Jira CSV exports are the intended use.
- Each file receives a `source_files` row with SHA-256. A hash already present in the project's `documents` table marks the file `duplicate_of` and skips conversion; the user sees it in review and may force re-import.

### 6.3 Step 2 — Convert

| Input | Converter | Notes |
|---|---|---|
| `docx`, `pptx`, `xlsx`, `html` | `markitdown` | Primary converter; tables become Markdown tables; sheets are capped at 500 rows each with a truncation note |
| `pdf` | `markitdown`, fallback `pymupdf` | If extracted text < 200 characters per page on average, mark `low_text` (likely scanned; OCR out of scope) |
| `csv` | built-in | Markdown table, 500-row cap with note |
| `md`, `txt` | pass-through | UTF-8 normalisation, LF line endings |
| images inside documents | dropped from Markdown | originals retained in `_sources`; recorded as a known limitation |

Each conversion records: page count (if available), character count, heading outline (first 30 headings), detected language (`langdetect`), converter id and version. Failures set `conversion_status = failed` with the error message; the job continues.

All converters implement one interface:

```python
class Converter(Protocol):
    extensions: frozenset[str]
    def convert(self, src: Path) -> ConversionResult  # markdown, meta, warnings
```

### 6.4 Step 3 — Analyse

Two sources of proposals are produced for every successfully converted file:

1. **Heuristic proposals** (always): rules from `templates/heuristics.yaml` matched against the file name and the first headings. Confidence 0.5 when a rule matches, otherwise `folder = null`, `doc_type = unclassified`, confidence 0.
2. **Agent proposals** (normal path): one Claude Agent SDK session per job (section 7). The agent's `propose_classification` tool upserts rows in `classification_proposals` with `proposed_by = agent`.

If the agent run ends without a proposal for some files, those files keep their heuristic proposal and the job is flagged `agent_incomplete` with the reason (budget, turns, timeout, API error). The job still moves to `awaiting_review`.

### 6.5 Step 4 — Review (human gate)

The review screen lists one row per source file with the agent proposal (or heuristic fallback), confidence, summary and reasoning. The reviewer may:

- change folder and/or doc type (dropdowns from the taxonomy, including `other`);
- edit the title;
- reject the file (not imported; original is still kept in `_jobs/<job>/raw` until cleanup);
- force import of a detected duplicate;
- accept all proposals with confidence ≥ project threshold (default 0.8) in one click;
- confirm or edit the agent's proposed project summary.

A file whose current proposal is `unclassified` (heuristic fallback with no match) cannot be accepted until the reviewer selects a folder and doc type; Apply is disabled while any accepted row is incomplete.

Nothing is written to the workspace until the reviewer clicks **Apply** and confirms a dialog listing the exact changes (files to create, stubs to add/remove, originals to copy).

### 6.6 Step 5 — Apply (deterministic, idempotent)

Executed under a per-project advisory lock (PostgreSQL `pg_advisory_xact_lock(project_id)`):

1. Ensure the 6 folders and sub-directories exist; create `project.yaml` if missing.
2. For each accepted file: copy original to `_sources/<sha256>.<ext>` (skip if present); write Markdown with frontmatter to the target path (write to a temp file, then atomic rename); for `keep_original` types also copy the original next to it.
3. For each required doc type that now has a non-stub file: delete the stub if its hash is unchanged since creation.
4. For each required doc type with no file: render the stub from `templates/stubs/`, record its hash.
5. If a repository reference exists: generate `04-source/repo-structure.md`.
6. Regenerate `_reports/gap-report.md` and `.json`; append to `_reports/ingestion-log.md`; update `project.yaml`.
7. Rebuild the `documents` index rows for the project from the filesystem.

Idempotency: target paths derive only from (doc type, original name slug); writes are skipped when the target exists with identical content hash; stub creation/removal is hash-guarded. Re-running apply for the same approved job produces no changes.

### 6.7 Step 6 — Complete and clean up

The job result shows counts (imported, rejected, failed, duplicates), agent cost, and links to the tree and gap report. A nightly task deletes `_jobs/<job-id>/` directories older than `STAGING_RETENTION_DAYS` (default 7), including the SDK session directory.

---

## 7. Agent Runner Design

### 7.1 Interface

```python
class Analyzer(Protocol):
    async def analyze(self, ctx: JobContext, emit: Callable[[AgentEvent], Awaitable[None]]) -> AnalysisResult

class ClaudeAgentSdkAnalyzer(Analyzer): ...   # production
class FakeAnalyzer(Analyzer): ...             # tests: scripted proposals
```

`AnalysisResult` carries `session_id`, `status` (`success | budget_exceeded | max_turns | timeout | error`), `total_cost_usd`, `input_tokens`, `output_tokens`, `num_turns`, `error`.

### 7.2 SDK configuration (verified field names, Agent SDK Python 0.2.x)

```python
options = ClaudeAgentOptions(
    cwd=str(job_dir),                               # staging dir: converted markdown + manifest only
    system_prompt=build_system_prompt(taxonomy),
    model=project.settings.model,                   # default "claude-opus-5"
    mcp_servers={"qc": create_sdk_mcp_server(name="qc", version="1.0.0", tools=[...])},
    allowed_tools=[
        "mcp__qc__list_documents",
        "mcp__qc__read_document",
        "mcp__qc__propose_classification",
        "mcp__qc__set_project_summary",
    ],
    disallowed_tools=["Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
                      "Glob", "Grep", "WebSearch", "WebFetch", "Task", "TodoWrite"],
    permission_mode="dontAsk",                      # anything not allow-listed is denied, no prompt
    max_turns=min(10 + 3 * n_docs, 80),
    max_budget_usd=project.settings.max_budget_usd, # default 3.0
    setting_sources=[],                             # never load user/project Claude settings
    env={
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
        "CLAUDE_CONFIG_DIR": str(job_dir / ".claude"),  # keep session transcripts inside staging
    },
)
```

The whole `query()` iteration is wrapped in `asyncio.timeout(AGENT_TIMEOUT_SECONDS)` (default 900). Messages are relayed as SSE events: `AssistantMessage` tool-use blocks become "agent is reading X" / "agent proposed N"; the final `ResultMessage` provides `session_id`, `total_cost_usd`, `usage`, `subtype`.

Items marked **verify in spike**: that `setting_sources=[]` prevents loading `~/.claude` settings; that `CLAUDE_CONFIG_DIR` relocates session storage for the SDK subprocess; concurrent sessions in one process.

### 7.3 Custom tools (in-process MCP server `qc`)

| Tool | Input | Output | Side effects |
|---|---|---|---|
| `list_documents` | `{}` | JSON list: `doc_id`, `original_name`, `ext`, `pages`, `chars`, `language`, `outline[]`, `preview` (first 600 chars), `heuristic_hint {folder, doc_type, confidence}` | none |
| `read_document` | `{doc_id, start_line, max_lines ≤ 400}` | numbered text slice + `total_lines` | none |
| `propose_classification` | `{proposals: [{doc_id, folder_id, doc_type, title, summary ≤ 300, confidence 0..1, reasoning ≤ 500, duplicate_of?, split_note?}]}` | `{accepted, errors[], missing_doc_ids[]}` | upserts `classification_proposals` (last write per `doc_id` wins) |
| `set_project_summary` | `{summary ≤ 600, detected_language, project_name?, client_name?}` | `{ok}` | stores on the job for the reviewer to confirm |

Validation inside `propose_classification`: unknown `doc_id`, unknown folder, doc type not in that folder (and not `other`), confidence out of range → returned as `errors` so the agent corrects itself; nothing invalid is stored. Tool handlers are plain async functions, unit-tested without the SDK.

### 7.4 System prompt (outline)

Role: documentation analyst for software projects. Provide the taxonomy (folder ids, stage, description, doc types with one-line definitions). Instructions: call `list_documents` first; read as much of each document as needed to decide, using the outline to jump; submit a proposal for **every** document; prefer `other` in the right folder over a wrong doc type; mark duplicates and multi-part documents; summaries and reasoning in English regardless of document language; finish with `set_project_summary`. State explicitly that the agent has no file-writing capability and must not attempt it.

### 7.5 Limits and telemetry

Per project settings (editable by owner): `model`, `max_budget_usd`, `confidence_threshold`. Global: `AGENT_TIMEOUT_SECONDS`, `AGENT_CONCURRENCY` (semaphore, default 1 until the spike proves otherwise). Every run writes an `agent_runs` row with session id, model, status, tokens, cost, turns, start/end.

### 7.6 Hooks for later phases

Phases 2–5 reuse the same `Analyzer` interface pattern with different tool sets (search tools for Q&A, writer tools for test artefacts, a sandboxed runner for automation). Session ids are stored so later phases can resume or fork sessions if useful.

---

## 8. Data Model (PostgreSQL 16)

| Table | Key columns |
|---|---|
| `users` | `id`, `email` (unique, lowercase), `password_hash` (Argon2id), `display_name`, `role` (`admin`/`member`), `must_change_password`, `is_active`, `failed_logins`, `locked_until`, `created_at` |
| `auth_sessions` | `id`, `user_id`, `token_hash`, `expires_at`, `revoked_at`, `ip`, `user_agent` |
| `projects` | `id`, `slug` (unique), `name`, `client_name`, `workspace_path`, `settings` jsonb (`model`, `max_budget_usd`, `confidence_threshold`), `created_by`, `created_at`, `archived_at` |
| `project_members` | `project_id`, `user_id`, `role` (`owner`/`editor`/`viewer`) |
| `ingestion_jobs` | `id`, `project_id`, `created_by`, `status`, `flags` jsonb (`agent_incomplete`…), `counts` jsonb, `repo_ref`, `proposed_summary`, `error`, `created_at`, `updated_at` |
| `source_files` | `id`, `job_id`, `project_id`, `original_name`, `ext`, `size_bytes`, `sha256`, `raw_path`, `conversion_status`, `converted_path`, `meta` jsonb (pages, chars, outline, language, warnings), `duplicate_of` |
| `classification_proposals` | `id`, `job_id`, `source_file_id`, `proposed_by` (`agent`/`heuristic`), `folder_id`, `doc_type`, `title`, `summary`, `confidence`, `reasoning`, `duplicate_of`, `split_note`, `review_status` (`pending`/`accepted`/`modified`/`rejected`), `final_folder_id`, `final_doc_type`, `final_title`, `reviewed_by`, `reviewed_at` |
| `agent_runs` | `id`, `job_id`, `session_id`, `model`, `status`, `started_at`, `ended_at`, `total_cost_usd`, `input_tokens`, `output_tokens`, `num_turns`, `error` |
| `documents` | `id`, `project_id`, `folder_id`, `doc_type`, `rel_path`, `title`, `is_stub`, `content_sha256`, `stub_sha256_at_creation`, `source_file_id`, `source_sha256`, `created_at`, `updated_at` — rebuildable by scanning the workspace |
| `audit_log` | `id`, `at`, `user_id`, `project_id`, `action`, `target_type`, `target_id`, `details` jsonb |

Migrations via Alembic; `documents` and `audit_log` are indexed on `project_id`.

---

## 9. REST API (`/api/v1`)

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/change-password` |
| Users (admin) | `GET /users`, `POST /users`, `PATCH /users/{id}`, `POST /users/{id}/reset-password` |
| Projects | `GET /projects`, `POST /projects`, `GET /projects/{id}`, `PATCH /projects/{id}`, `DELETE /projects/{id}` (archive), `GET/PUT /projects/{id}/members` |
| Workspace | `GET /projects/{id}/tree`, `GET /projects/{id}/gap-report`, `GET /projects/{id}/documents/{docId}` (Markdown), `GET /projects/{id}/documents/{docId}/download` (original) |
| Jobs | `POST /projects/{id}/jobs` (multipart), `GET /projects/{id}/jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/events` (SSE), `POST /jobs/{id}/reanalyze`, `POST /jobs/{id}/cancel` |
| Review | `GET /jobs/{id}/proposals`, `PATCH /jobs/{id}/proposals/{pid}`, `POST /jobs/{id}/proposals/bulk-accept`, `PATCH /jobs/{id}/summary`, `POST /jobs/{id}/apply` |
| Meta | `GET /taxonomy`, `GET /health` |

SSE event types: `job.status`, `file.converted`, `file.failed`, `agent.started`, `agent.tool_call`, `agent.proposed`, `agent.finished`, `apply.progress`, `job.completed`, `job.failed`. Events are also persisted so a reconnecting client can replay from the last event id.

OpenAPI is generated by FastAPI; the frontend uses a TypeScript client generated from it in CI/dev scripts.

---

## 10. Frontend (Next.js)

| # | Screen | Key elements |
|---|---|---|
| 1 | Login | e-mail + password, forced password change flow |
| 2 | Projects | search, create, my role badge |
| 3 | Project detail | tabs: **Structure** (6-folder tree, stubs dimmed, Markdown viewer, download original), **Gap report** (per folder status table, completeness %), **History** (jobs, cost), **Members & settings** (owner only: members, model, budget, threshold, archive) |
| 4 | New ingestion | drag-and-drop files, notes textarea, repo reference, start; live progress (conversion per file, agent activity, running cost) |
| 5 | Review | proposals table: folder/doc-type dropdowns, colour-coded confidence, expandable summary/reasoning, filters, multi-select, "Accept all ≥ threshold", editable project summary, **Apply** with confirmation dialog listing changes |
| 6 | Job result | counts, cost, links to tree and gap report |
| 7 | User admin | list, create, deactivate, reset password |

UI copy in English; strings kept in a single messages file so Vietnamese can be added later. State: server state via generated client + SWR/React Query; SSE via `EventSource` with reconnection.

---

## 11. Authentication, Authorisation and Security

- **Accounts**: local; Argon2id hashes; admin-created only; temporary password with forced change; first admin created by `uv run qc-agent create-admin`.
- **Sessions**: opaque token in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie; server-side `auth_sessions` row (8 h expiry, revocable); CSRF protection by `SameSite` plus a custom header check on state-changing requests.
- **Brute force**: per-account lockout after 5 failures for 15 minutes; per-IP rate limit on `/auth/login`.
- **Roles**: global `admin` (users, all projects) and `member`; per project `owner` (members, settings, archive), `editor` (jobs, review, apply), `viewer` (read, download).
- **Secrets**: `.env` on the server; `.env.example` in repo; pre-commit secret scan (gitleaks).
- **Files**: all paths resolved and asserted to be under `WORKSPACE_ROOT/<slug>`; downloads served through the backend with permission checks and `Content-Disposition: attachment`; workspace never mounted as static.
- **Agent isolation**: no built-in file or shell tools; `cwd` is the job staging directory; session transcripts in the job's `.claude` directory, deleted with the job.
- **Transport**: Caddy terminates TLS (internal CA or company certificate); HTTP only on localhost.
- **Logging**: structured JSON; never logs document content, prompts, or secrets; agent tool inputs logged at debug level with document text redacted.
- **Data processing notice**: README and project creation screen state that converted document text is sent to the Claude API; per-project customer confirmation is recorded in `audit_log` before the first real ingestion (checkbox + name of the confirming person).
- **Deletion**: project archive moves the workspace to `<WORKSPACE_ROOT>/_trash/<slug>-<timestamp>/` (owner + confirm); permanent purge is an admin action with a second confirmation.

---

## 12. Error Handling Matrix

| Failure | Behaviour |
|---|---|
| Unsupported file / too large | Rejected at upload with a per-file message; other files proceed |
| Zip path traversal / limits exceeded | Entire zip rejected with reason |
| Conversion error | File marked `failed`; job continues; user may re-upload another format |
| Scanned PDF (low text) | Converted with `low_text` warning; shown in review |
| Agent budget / turns / timeout / API error | Run recorded with status; job → `awaiting_review` with heuristic fallbacks and `agent_incomplete` flag; "Re-analyse" button |
| Invalid agent proposal | Rejected inside the tool; agent receives errors and retries |
| Apply error mid-way | Job → `failed` with partial report; apply is re-runnable and idempotent |
| Concurrent apply on same project | Second waits on advisory lock |
| Missing API key / DB unreachable at startup | Process exits with a clear message; `/health` reports the failing check |
| SSE disconnect | Client reconnects with `Last-Event-ID`; events replayed |

---

## 13. Testing Strategy

### 13.1 Spike (before implementation of the agent layer)

Throwaway script, not kept in the product: Agent SDK on Python 3.12 with custom tools only, `permission_mode="dontAsk"`, `setting_sources=[]`, `CLAUDE_CONFIG_DIR` relocated; two sessions concurrently in one asyncio process; 10 sample documents. Record: whether built-in tools are really unavailable, where session files land, concurrency behaviour, cost and duration. Outputs decide `AGENT_CONCURRENCY` and the default budget.

### 13.2 Automated tests

| Layer | Tooling | Coverage |
|---|---|---|
| Unit (backend) | pytest | converters (fixtures generated in tests), zip safety, slugs and path safety, taxonomy loader, heuristics, stubs, gap report, apply idempotency, repo tree, tool handler validation |
| Agent | pytest + `FakeAnalyzer` | pipeline behaviour with scripted proposals, incomplete runs, timeouts; one opt-in integration test against the real API (`QC_AGENT_LIVE_TESTS=1`) with a tiny fixture set and a 0.50 USD budget |
| API | pytest + httpx + PostgreSQL in Docker | auth, roles (403 paths), job lifecycle, review, apply, SSE replay |
| Frontend | Vitest + React Testing Library | components and state |
| End-to-end | Playwright against Docker Compose | login → create project → upload → review → apply → tree and gap report |
| Quality gates | ruff, mypy, ESLint, tsc, gitleaks | run locally via pre-commit; CI platform to be confirmed |

Test data: synthetic sample project (10 files) committed under `backend/tests/fixtures/sample-project/`, containing no customer data.

---

## 14. Deployment and Operations

- `deploy/docker-compose.yml`: services `db` (postgres:16, volume `pgdata`), `backend` (uvicorn, volume `workspace`), `frontend` (`next start`), `caddy` (ports 80/443, volume `caddy_data`). Alembic migrations run on backend start-up.
- Sizing: 2 vCPU, 4 GB RAM, disk sized to the expected workspace plus PostgreSQL.
- Runbook (`06-deployment` of QC-Agent's own docs, written in Phase 1): start/stop, logs, nightly `pg_dump` and workspace rsync, restore drill, rotating `ANTHROPIC_API_KEY`, creating the first admin, upgrading, clearing stuck jobs.
- Health: `GET /health` checks DB, workspace writability, presence of API key, Agent SDK import.
- Monitoring in Phase 1: container logs + `agent_runs` cost table viewable in the History tab.

---

## 15. Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL DSN |
| `SESSION_SECRET` | — | Cookie/session signing |
| `ANTHROPIC_API_KEY` | — | Passed only to the SDK subprocess |
| `WORKSPACE_ROOT` | `./workspace` | Knowledge-base root |
| `PUBLIC_BASE_URL` | — | Used for cookies and links |
| `COOKIE_SECURE` | `true` | `false` only for localhost dev |
| `MAX_UPLOAD_FILE_MB` | `50` | Per file |
| `MAX_UPLOAD_JOB_MB` | `500` | Per job |
| `STAGING_RETENTION_DAYS` | `7` | `_jobs` cleanup |
| `AGENT_MODEL_DEFAULT` | `claude-opus-5` | Project default |
| `AGENT_MAX_BUDGET_USD_DEFAULT` | `3.0` | Project default |
| `AGENT_TIMEOUT_SECONDS` | `900` | Hard stop per run |
| `AGENT_CONCURRENCY` | `1` | Semaphore size |
| `CONFIDENCE_THRESHOLD_DEFAULT` | `0.8` | Bulk-accept threshold |
| `LOG_LEVEL` | `info` | |

---

## 16. Non-Functional Targets (Phase 1)

| Metric | Target |
|---|---|
| Conversion of 10 documents ≤ 50 pages each | < 2 minutes |
| Agent analysis of 10 documents | < 10 minutes, < default budget |
| SSE progress latency | < 2 seconds |
| Apply for 50 files | < 30 seconds |
| Concurrent users | 10 without degradation |
| Availability | Business hours; restart-safe (job state in DB) |

---

## 17. Risks, Dependencies and Items Requiring Confirmation

### 17.1 Risks

| Risk | Mitigation |
|---|---|
| Agent SDK is 0.x; API may change | Pin version; `Analyzer` interface; spike |
| Concurrency of SDK sessions in one process undocumented | Default concurrency 1; spike measures |
| Session transcripts may contain document text | Relocate via `CLAUDE_CONFIG_DIR` into job staging; delete on cleanup; verify in spike |
| Scanned PDFs yield no text | `low_text` warning; OCR deferred |
| Runaway cost | Per-job budget, turn cap, timeout; cost visible per run |
| Customer data sent to external API | Per-project confirmation recorded; documented in README |
| Classification quality on Vietnamese documents | Agent reads full text; heuristics as fallback; human review always |

### 17.2 Dependencies (stakeholder / IT)

- Docker Desktop or OrbStack on developer machines (not installed on the current dev machine); Docker on the server.
- A dedicated Anthropic API key with a spending limit.
- Internal Linux VM, internal DNS name, TLS certificate or acceptance of Caddy's internal CA.
- Python 3.12 via `uv` (system Python on the dev machine is 3.9, below the SDK minimum of 3.10).

### 17.3 Items requiring confirmation

- CI platform (GitHub Actions / GitLab CI / other) — pipeline files will be added once decided.
- Customer confirmation process wording for sending document text to the Claude API.
- Whether a Vietnamese UI translation is wanted in a later phase.
- Server specification and backup destination.

---

## 18. Acceptance Criteria (Phase 1)

1. An admin creates a user; the user logs in and is forced to change the temporary password; a `viewer` receives HTTP 403 when creating a job.
2. Uploading the 10-file sample set (docx, pdf, xlsx, md, Confluence zip) results in every file either converted or marked failed with a per-file reason.
3. The agent submits a proposal for every converted file with confidence and reasoning; the run cost is below the configured budget; a configuration test proves the agent has no file-writing or shell tools.
4. After changing one proposal, rejecting one file and applying, the workspace contains exactly the six numbered folders, each imported file at its canonical path with valid frontmatter, originals in `_sources`, stubs for missing required types, and a gap report that matches the filesystem.
5. Re-running apply for the same job produces no filesystem changes (verified by hashing the workspace before and after).
6. Providing a repository reference produces `04-source/repo-structure.md` with a directory tree and language statistics and leaves no cloned code in the workspace.
7. The full stack runs via Docker Compose on the server behind HTTPS; `/health` is green; a secret scan of the repository reports no findings.

---

## 19. Glossary

| Term | Meaning |
|---|---|
| Workspace | The per-project directory holding the 6-folder knowledge base |
| Taxonomy | The data file defining folders, doc types, required flags and templates |
| Stub | A template Markdown file standing in for a missing required document |
| Gap report | Generated report of present / stub / missing document types per folder |
| Job | One ingestion run: upload → convert → analyse → review → apply |
| Proposal | A suggested (folder, doc type, title) for one uploaded file |
| Agent run | One Claude Agent SDK session executed for a job |
| Apply | The deterministic step that writes approved files into the workspace |
