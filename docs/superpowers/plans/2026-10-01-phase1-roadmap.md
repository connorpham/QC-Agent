# QC-Agent Phase 1 — Implementation Roadmap

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` (v2, approved 2026-10-01)

Phase 1 spans six subsystems. Each plan below produces working, tested software on its own and is executed and reviewed before the next one is written, so later plans can use real results (spike measurements, actual interfaces).

| # | Plan | Delivers | Spec sections | Entry criteria | Status |
|---|---|---|---|---|---|
| 0 | Spikes | Measured answers: Agent SDK isolation, tool restriction, concurrency, cost; SharePoint and Google Drive upload + version behaviour | 7.3, 8.2, 8.3, 15 | Anthropic API key; a test SharePoint site with `Sites.Selected` grant; a test Shared Drive with service account | Written: `2026-10-01-plan-0-spikes.md` |
| 1 | Backend foundation | FastAPI app, PostgreSQL schema + Alembic, local accounts, mandatory TOTP MFA, sessions, lockout, rate limit, CSRF, admin user management, CLI, projects, members, roles | 9, 10 (identity + projects tables), 11 (auth, admin, projects), 13 | Docker (or local PostgreSQL 16), uv | Written: `2026-10-01-plan-1-backend-foundation.md` |
| 2 | Storage layer | `StorageBackend` interface, local FS adapter, SharePoint adapter, Google Drive adapter, shared contract test suite, encrypted storage connections, admin endpoints, project storage binding | 8, 10 (`storage_connections`), 11 (admin connections) | Plan 1 merged; Plan 0 storage spike results | To write after Plan 1 |
| 3 | Ingestion pipeline | Taxonomy + templates, upload API with per-file type selection, zip safety, converters, version matching, deterministic publish, stubs, gap report, repo structure, per-project LLM consent, per-item state machine, SSE, `FakeAnalyzer` | 5, 6, 10 (ingestion tables), 11 (uploads, items, documents), 14 | Plan 2 merged | To write after Plan 2 |
| 4 | Agent layer | Claude Agent SDK runner, check and normalise sessions, custom tools, prompts, budgets, timeouts, telemetry, opt-in live tests | 7 | Plan 3 merged; Plan 0 agent spike results | To write after Plan 3 |
| 5 | Frontend | Next.js app: login + MFA enrolment, projects, document browser, upload wizard, My tasks, type confirmation, draft review, gap report, settings, admin | 12 | Plans 1–3 merged (Plan 4 optional; fake analyzer works) | To write after Plan 3 |
| 6 | Deployment & operations | Docker Compose for cloud VM, Caddy with public TLS, proxy headers, backups, runbook, health extensions, end-to-end Playwright suite, CI once platform is chosen | 16, 15 (e2e), 19 | Plans 1–5 merged; cloud VM and DNS | To write last |

Plan 0 and Plan 1 have no dependency on each other; Plan 1 can start while IT prepares Plan 0's prerequisites.
