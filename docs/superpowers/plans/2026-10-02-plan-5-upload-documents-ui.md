# Plan 5 — Upload and Document UI: Server-Sent Events, Upload Wizard, Live Progress, My Tasks, Type Confirmation, Document Browser, Gap Report

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End users upload documents with a chosen type from a responsive web UI, watch each file being converted and published live over Server-Sent Events, confirm a document type when the check asks for it, and browse and read the knowledge base (documents by folder, Markdown rendered safely in the browser, versions, downloads, gap report) — with Vitest coverage, a Playwright flow against the real backend, and the backend half Plan 2 deferred: an `events` table written in the same transaction as every item state change and a replayable `GET /uploads/{id}/events` stream.

**Architecture:** The backend records one `item.status` event row per upload-item transition inside the transaction that performs the transition (`transition()` in `app/services/pipeline.py` is the single choke point; `confirm_type`, `retry_item` and `requeue_stale_items` record theirs explicitly). `GET /uploads/{upload_id}/events` is a plain `StreamingResponse` generator (no new dependency): it replays rows after `Last-Event-ID`, then polls the table every 0.5 s with a short-lived session per poll, sends a `: ping` comment every 15 s (the Next rewrite proxy drops a proxied response after 30 s without bytes), and ends with `upload.settled` once no item of the upload is still in progress. The frontend consumes it with the browser's `EventSource` (automatic reconnection with `Last-Event-ID`), falls back to polling `GET /uploads/{id}`, and refreshes the full upload once on `upload.settled`, so a missed intermediate event can never leave the screen wrong. Multipart uploads go through `XMLHttpRequest` (real upload progress, and the only multipart path testable under jsdom 30), everything else through the existing openapi-fetch client. Document Markdown is rendered with react-markdown + remark-gfm + rehype-sanitize (no `dangerouslySetInnerHTML` anywhere). Layout is mobile-first with Tailwind breakpoints: lists are card lists at every width, tables scroll horizontally, dialogs are full-screen below `sm`, the navigation collapses behind a menu button below `md`.

**Tech Stack:** Backend unchanged (Python 3.12, FastAPI 0.142.2, Starlette 1.7.0, SQLAlchemy 2.1.1 asyncio, Alembic 1.20.0, uvicorn 0.54.0; no new Python dependency). Frontend: Next.js 16.3.7, React 19.2.8, TypeScript 5.9 strict, Tailwind CSS 4.3, openapi-fetch 0.17; new: react-markdown 10.1.0, remark-gfm 4.0.1, rehype-sanitize 6.0.0. Tests: pytest + httpx (backend), Vitest 5 + jsdom 30 + Testing Library (frontend), Playwright 1.63 (end to end).

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` v2.2 — sections 6.1 (upload wizard), 6.2 (states), 9 (roles), 10 (`events`), 11 (`GET /uploads/{id}/events`, `GET /me/tasks`, documents), 12 (screens 3, 4, 5, 6, 8; responsive layout; sanitised Markdown rendering), 13 (uploads, authorisation), 14 (SSE disconnect → replay), 15 (frontend tests), 17 (SSE latency < 2 s). Scope decided with the stakeholder on 2026-10-02 (`plan5-scope.md`): Plan 5 runs before Plan 4 because the agent layer is blocked on an Anthropic API key (PENDING section 6); the spec stays the authority.

**Deferred from this plan (where it goes):** Normalised-draft review (screen 7), the "normalised" badge, the Normalised tab and the agent's real verdicts → Plan 4 (nothing is stubbed here: the type-confirmation screen handles "no verdict" because `SkipAnalyzer` is still the production analyzer). SharePoint and Google Drive → Plan 3b. Changing a project's storage → Plan 3c. OCR, e-mail notifications, bulk re-upload tooling → out of Phase 1 / later. `agent.*` and `apply.progress` event types named in Plan 2's text → Plan 4 adds them when something emits them. Caddy configuration for long-lived SSE responses → Plan 6 (recorded in PENDING by Task 9).

**Changes from the scope brief (and why):**

- **One event naming scheme:** the pipeline emits nothing today, so the names Plan 2's text listed (`job.status`, `file.converted`, `file.failed`, …) never existed in code. This plan defines two types and nothing else: `item.status` (one row per upload-item transition, payload = item id, new status and the fields that changed: `type_check`, `check_explanation`, `suggested_doc_type`, `final_doc_type`, `error`, `document_id`, `version`) and the synthetic terminal frame `upload.settled` (not a row; sent by the stream when no item is in `uploaded`/`converting`/`checking`/`publishing`). `needs_confirmation` is a waiting state, not work in progress, so an upload with an item waiting for the user is settled and its stream ends; confirming the type produces new rows and the client reopens the stream.
- **Delivery mechanism:** polling the `events` table every 0.5 s inside the generator (spec 17 asks for < 2 s latency), one short session per poll. Chosen over in-process pub/sub because the pipeline already commits every transition and a pub/sub would still need the table for replay; it also keeps working with several uvicorn workers in Plan 6.
- **Multipart upload uses `XMLHttpRequest`, not openapi-fetch.** openapi-fetch builds a `Request` object internally; under Vitest's jsdom 30 the `File` objects a file input produces are jsdom's while `Request` is undici's, and undici refuses them (verified below), so the wizard would be untestable. XHR also gives real upload progress (`xhr.upload.onprogress`) for 50 MB files, which fetch cannot. The helper lives next to the client (`src/lib/api/upload.ts`), sends the CSRF header, and types its response as `components["schemas"]["UploadOut"]`.
- **Three small backend additions the screens need:** `GET /documents/{id}/versions/{v}/content` returns the parsed frontmatter and the body without the frontmatter block (the details panel needs structured metadata and the Markdown tab must not render `---` lines; the backend already has `split_frontmatter`); `GET /upload-limits` exposes `MAX_UPLOAD_FILE_MB`, `MAX_UPLOAD_BATCH_MB` and the allowed extensions so the client-side guards match the server without duplicating constants; `GET /projects/{id}/gap-report` gets a typed response model (`GapReportOut`) so the generated client types it, and `DocumentOut` gains `uploaded_by_name` and `version_created_at` (spec screen 3 lists the uploader and date per document).
- **Live progress has its own route** `/uploads/[uploadId]` instead of living inside the wizard: the user can leave and come back (spec 6.1 step 4), and the page rebuilds its state from `GET /uploads/{id}` before it subscribes.
- **The project page lands on the Documents tab** (the knowledge base is what members come for); Overview, Gap report, Members and Settings are the other tabs, built on an accessible `Tabs` primitive (`tablist`/`tab`/`tabpanel`, arrow keys), which also closes the Plan 3a pending item about the tab markup.
- **Type search in the document-type dropdown** is the native `<select>` with one `<optgroup>` per folder (type-ahead comes from the browser). A custom searchable combobox is not justified for 26 options and would need its own accessibility work.

## Global Constraints

- Backend: Python `>=3.12,<3.13` with uv; run backend commands from `backend/`. `uv run ruff format .`, `uv run ruff check .` and `uv run mypy app` (strict) pass after every backend task. All Plan 1, 2 and 3a Global Constraints still apply: API prefix `/api/v1`, English copy, CSRF header `X-QC-Agent: 1` on every state-changing request, Annotated dependencies, services never import `app.api`, audit rows via `app.services.audit.record` (never commits), PostgreSQL 16 on `localhost:5434` with tests against `qc_agent_test` (never SQLite), no blocking I/O directly in `async def`, one route commits once.
- Events (spec 10): table `events` — `id` BIGINT identity (monotonic, the SSE `id:` and `Last-Event-ID`), `upload_id` (FK `uploads`, cascade), `item_id` (FK `upload_items`, set null), `type` (`item.status` is the only type this plan writes), `payload` JSONB, `created_at`; index `ix_events_upload_id_id` on `(upload_id, id)`. An event row is added to the **same session and transaction** as the state change it describes and is never committed separately. Payloads carry ids, statuses and the short fields listed above — never document content, file names, conversion metadata or outlines.
- SSE (spec 11, 14, 17): `GET /uploads/{upload_id}/events` — `text/event-stream; charset=utf-8`, headers `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`; authorised exactly like `GET /uploads/{upload_id}` (any live project role; clients only their own uploads; otherwise 404); first frame `retry: 2000`; replays rows with `id > Last-Event-ID` (header; non-numeric → 0); polls every 0.5 s with a session opened and closed per poll — the request-scoped session is closed before the response starts and no session stays open between polls; `: ping` comment after 15 s without a frame; ends with `event: upload.settled` when no item is in `uploaded`, `converting`, `checking` or `publishing`.
- Frontend: Node 24 and pnpm 11 (`packageManager` pinned). TypeScript `strict`. After every frontend task these pass from `frontend/`: `pnpm lint`, `pnpm format`, `pnpm typecheck`, `pnpm test`, `pnpm api:check`, `pnpm build`. Run `pnpm format:write` before committing. Only Task 4 edits `package.json`/`pnpm-lock.yaml`.
- Frontend talks to the backend only same-origin through the rewrite `/api/:path*` → `BACKEND_URL`; JSON calls only through the typed client `src/lib/api/client.ts`; the multipart upload only through `src/lib/api/upload.ts` (XHR, CSRF header, 401 → unauthorized handler); the event stream only through `EventSource` on `/api/v1/uploads/{id}/events` (same-origin, so the session cookie travels; GET, so no CSRF header is needed). The frontend never stores tokens or API payloads in `localStorage`, logs or fixtures. All UI copy is English and lives in `src/messages.ts` (Task 4 pre-defines every Plan 5 string; later tasks only append to the end of the section they own).
- Markdown rendering is a security boundary (spec 12, v2.2): document Markdown is rendered **only** through `src/components/ui/Markdown.tsx` (`MarkdownView`), which uses react-markdown with `remark-gfm` and `rehype-sanitize` (`defaultSchema`) and react-markdown's default `urlTransform`. No `dangerouslySetInnerHTML`, no `rehype-raw`, no custom schema that re-allows `style`, event handlers, `iframe`, `object`, `embed`, `script`, `svg` or `form`. The test file carries the hostile fixtures.
- Responsive layout (spec 12): mobile-first Tailwind v4; breakpoints `sm` (640 px) for forms and dialogs, `md` (768 px) for the navigation and multi-column toolbars, `lg` (1024 px) for the document page's two-column layout. Rules: no horizontal page scroll at 360 px; card lists instead of tables for documents, tasks and upload rows; data tables (gap report, versions) scroll inside their own container; `Dialog` is full-screen below `sm`; the app navigation collapses behind a button with `aria-expanded`/`aria-controls` below `md`; touch targets at least 40 px high in the navigation and on primary buttons.
- Accessibility: every input has a `<label>`; dialogs are native `<dialog>` opened with `showModal()` and carry `aria-labelledby`; errors `role="alert"`, loading and results `role="status"`; tabs are `role="tablist"`/`tab`/`tabpanel` with `aria-selected`, `aria-controls`, roving `tabIndex` and arrow-key navigation; status badges carry visible text (never colour alone); `<progress>` elements have an accessible name; no `aria-hidden` on meaningful content.
- Uploads (client side, mirroring spec 6.3 and the backend): extensions `docx pdf xlsx pptx md txt html htm csv zip`; per-file and per-batch limits come from `GET /upload-limits`; rows that fail a guard are marked and excluded before any byte is sent; zip archives cannot be a new version (backend rule); client users see visibility fixed to "Shared".
- Generated files `frontend/openapi.json` and `frontend/src/lib/api/schema.d.ts` are never edited by hand. Regenerate with `uv run python -m app.openapi_export ../frontend/openapi.json` (from `backend/`) and `pnpm api:generate` (from `frontend/`). On merge conflicts, regenerate instead of merging.
- Tests: no customer data; synthetic names and e-mails only (`example.com`); fixture files are generated at test time (Python: `tests/helpers/files.py`; Playwright: a `.docx` generated by python-docx from the backend environment in `global-setup.ts`). End-to-end tests keep using the disposable database `qc_agent_e2e`, temporary folders and per-run secrets.

## Verified third-party behaviour this plan depends on (checked on 2026-10-02 in a scratch environment, versions as pinned in `backend/uv.lock` and `frontend/pnpm-lock.yaml`)

- **FastAPI 0.142.2 / Starlette 1.7.0 `StreamingResponse` with an async generator** streams incrementally under uvicorn 0.54.0 (`transfer-encoding: chunked`, `content-type: text/event-stream; charset=utf-8`, custom `Cache-Control`/`X-Accel-Buffering` headers pass through). When the client disconnects, the generator receives `asyncio.CancelledError` at its next `await` (observed 0.3 s after the client closed, i.e. the next poll tick); `finally` blocks run; `request.is_disconnected()` is not needed. Several concurrent listeners each receive every frame. A `uvicorn.Server(uvicorn.Config(app, port=…))` started with `asyncio.create_task(server.serve())` inside a test's event loop serves and stops cleanly (`server.should_exit = True`).
- **A yield dependency exits only after the streaming response has finished** in FastAPI 0.142.2 (`dep enter → route returns → yield 0 … gen done → dep exit`), so a `DbSession` dependency on the SSE route would pin one pooled connection per listener for the whole stream. The route therefore calls `await db.close()` before returning the `StreamingResponse`; `AsyncSession.close()` is idempotent (closing inside the `async with` and again at its exit raises nothing — verified with SQLAlchemy 2.1.1 + asyncpg 0.31.0).
- **`httpx.ASGITransport` (0.28.1) buffers the whole response until the app finishes**, even with `client.stream()` (first chunk arrived only when the generator ended). Consequence for tests: HTTP-level SSE tests must use uploads whose stream terminates (settled uploads replay and close in < 0.2 s); live-delivery, heartbeat and disconnect behaviour are tested by iterating the generator function directly.
- **Next.js 16.3 rewrite proxy and SSE:** through `/api/:path*` → backend, frames arrive incrementally (first event 0.06 s after the request, each subsequent one within 0.03 s of the backend sending it); the response keeps `text/event-stream`, `cache-control`, `x-accel-buffering` and chunked encoding. **The proxy closes a proxied response after 30 s without any bytes** (`experimental.proxyTimeout`, default `30000` in `next/dist/server/lib/router-utils/proxy-request.js`); a 45 s stream with a `: ping` comment every 10 s stayed open to the end, a 40 s stream without heartbeats was cut at 30.1 s. A client abort propagates to the backend (generator cancelled 0.1 s after `curl` exited). Same-origin cookies set for the frontend origin are forwarded on `EventSource` requests (`cookie: qc_session=…` seen by the backend on every connection).
- **Browser `EventSource` (Chromium via Playwright 1.63):** receives named events (`addEventListener("item.status", …)`, `MessageEvent.lastEventId` carries the frame's `id:`); when the server ends the response without the page closing the source, the browser reconnects after the advertised `retry:` (500 ms in the spike → reconnects at +0.5 s) and sends `Last-Event-ID: <last id>` (backend saw `None, "2", "4"` across three connections); `es.close()` and navigating away both close the connection (backend generator cancelled within one tick). `EventSource` is **not** available in Node 24 nor jsdom 30 → the hook takes an injectable factory and tests use a fake.
- **react-markdown 10.1.0 + remark-gfm 4.0.1 + rehype-sanitize 6.0.0 (`defaultSchema`)** render hostile input inert in Node (`renderToStaticMarkup`), in Vitest 5 + jsdom 30.1 (`@testing-library/react` 16.3) and in a real `next build` + Chromium: `<script>` becomes text without the tag, `<img onerror>`/`<svg onload>`/`<div onclick>`/`<b onmouseover>` lose their elements or attributes, `javascript:`/`data:`/`vbscript:` (also mixed case and with embedded tab) link and image URLs are dropped (react-markdown's `defaultUrlTransform` returns `""` for them and rehype-sanitize removes the empty attribute), `<iframe>`, `<object>`, `<embed>`, `<style>`, `<form>` and `style="…"` disappear, while `https:`, relative, `mailto:` and `#fragment` links, `https:` images, GFM tables, task lists, strikethrough, autolinks, footnotes and fenced code blocks (content escaped) render. react-markdown alone already escapes raw HTML to text (it has no `rehype-raw`); rehype-sanitize is defence in depth. All three packages are ESM-only; Next 16 bundles them in a client component without configuration and TypeScript 5.9 type-checks them with `moduleResolution: bundler`. Static markup contains `<!-- -->` separators between text nodes (React), which is why text assertions use `textContent`.
- **Vitest 5 jsdom environment and files:** `globalThis.File`, `FormData`, `Blob`, `Request` and `fetch` are all jsdom's exports, but jsdom's `Request` is undici's implementation: `new Request(url, { body: formDataWithJsdomFiles })` throws (`webidl.is.File` assertion), and swapping `globalThis.File` for Node's `File` breaks jsdom's `FormData.append` ("parameter 2 is not of type 'Blob'"). `fireEvent.drop(el, { dataTransfer: { files: [file], types: ["Files"] } })` delivers the files to `onDrop`; `userEvent.upload(input, files)` fills a `multiple` file input; jsdom's `FormData` accepts jsdom `File`s and `getAll("files")` returns them with `.name` and `.text()`; `vi.stubGlobal("XMLHttpRequest", FakeXHR)` lets a component's `new XMLHttpRequest()` hand the `FormData` to the test intact (`send(body)` captured, `upload.addEventListener("progress", …)` and `setRequestHeader` observable). jsdom has no `DataTransfer` constructor and no `URL.createObjectURL`, so downloads are plain `<a href download>` links to the API.
- **PostgreSQL 16 / SQLAlchemy 2.1.1 / Alembic 1.20.0:** `mapped_column(BigInteger, Identity(), primary_key=True)` and `op.create_table(…, sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False), sa.PrimaryKeyConstraint("id", name=…))` produce the same schema (`compare_metadata` reports `[]` against both `metadata.create_all` and the Alembic table); inserts return 1, 2, 3; `WHERE upload_id = :u AND id > :last ORDER BY id` is the replay query.

## Review Focus

1. A stream cut by the proxy after 30 idle seconds, by a network blip or by a laptop lid must resume where it left off — every missed event replayed exactly once, no status shown twice, no status lost → `test_last_event_id_replays_only_later_events_once` (Task 3) and `reconnects with the browser's Last-Event-ID and applies each event once` (Task 5).
2. A 60 MB file, an `.exe`, or a batch over the limit dropped into the wizard must be refused in the row before any byte is sent, and the rest of the batch must still upload → `refuses files over the limit and unsupported extensions before upload` (Task 5).
3. A customer document whose text contains `<script>`, `onerror=` handlers, `javascript:` links or an `<iframe>` must render as harmless text in every viewer's browser → the hostile fixtures in `Markdown.test.tsx` (Task 4) and `renders the Markdown body through MarkdownView` (Task 6).
4. A client user who pastes the URL of an internal document, or of another client's upload progress page, must see "not found", never a partial page → `shows the not-found message for a document the user may not see` (Task 6) and `shows not found for an upload the user may not see` (Task 5).
5. Confirming a type for an item someone else already confirmed (or that was retried meanwhile) must show the backend's conflict message and refresh the list instead of pretending success → `shows the conflict message when the item is no longer waiting` (Task 7).

---

## File Structure

```
QC-Agent/
├── docs/PENDING.md, docs/superpowers/plans/2026-10-01-phase1-roadmap.md   # Plan 5 before Plan 4; new notes (T9)
├── README.md                                        # screens list (T9)
├── backend/
│   ├── app/
│   │   ├── db/models/ingestion.py                   # + ACTIVE_STATUSES, ITEM_STATUS_EVENT, UploadEvent (T1)
│   │   ├── db/models/__init__.py                    # exports (T1)
│   │   ├── services/events.py                       # record_item_status, events_after, is_settled (T1); SSE frames + stream_upload_events (T3)
│   │   ├── services/pipeline.py                     # transition() records events; requeue records events (T1)
│   │   ├── services/uploads.py                      # confirm_type / retry_item record events (T1)
│   │   ├── services/documents.py                    # current_version_meta, split_content (T2)
│   │   ├── schemas/documents.py                     # DocumentOut + uploader/date, DocumentContentOut, GapReportOut (T2)
│   │   ├── schemas/uploads.py                       # UploadLimitsOut (T2)
│   │   ├── api/routes/documents.py                  # content endpoint, enriched listing, typed gap report (T2)
│   │   ├── api/routes/taxonomy.py                   # GET /upload-limits (T2)
│   │   └── api/routes/uploads.py                    # GET /uploads/{id}/events (T3)
│   ├── migrations/versions/0004_events.py (T1)
│   └── tests/
│       ├── db/test_models.py                        # + events identity / cascade (T1)
│       ├── ingestion/test_events.py                 # every transition writes a row, same transaction (T1)
│       ├── api/test_documents.py                    # + content, listing meta, typed gap report (T2)
│       ├── api/test_uploads.py                      # + upload limits (T2)
│       └── api/test_upload_events.py                # SSE replay, auth, live, heartbeat, disconnect (T3)
└── frontend/
    ├── package.json, pnpm-lock.yaml                 # + react-markdown, remark-gfm, rehype-sanitize (T4)
    ├── openapi.json, src/lib/api/schema.d.ts        # regenerated by the controller after waves 1 and 2
    ├── e2e/global-setup.ts (sample .docx), e2e/first-run.spec.ts (saves TOTP secret; Overview tab) (T6: Overview click only; T8: the rest),
    │   e2e/helpers.ts, e2e/upload-flow.spec.ts (flow + phone smoke test)  # T8
    ├── README.md                                    # screens, SSE, Markdown boundary (T9)
    └── src/
        ├── messages.ts                              # + nav.tasks, common.*, uploads, tasks, documents, gaps (T4)
        ├── app/globals.css                          # .markdown styles (T4)
        ├── lib/api/client.ts                        # + notifyUnauthorized (T4)
        ├── lib/api/upload.ts, lib/api/upload.test.ts            # XHR multipart helper (T4)
        ├── lib/format.ts, lib/format.test.ts                    # formatBytes, formatDateTime, formatDate (T4)
        ├── lib/hooks/useDebouncedValue.ts                       # (T4)
        ├── test/fake-xhr.ts, test/fake-event-source.ts          # test doubles (T4)
        ├── components/ui/Tabs.tsx, Tabs.test.tsx                # accessible tabs (T4)
        ├── components/ui/TypeOptions.tsx                        # grouped document-type options (T4)
        ├── components/ui/Markdown.tsx, Markdown.test.tsx        # MarkdownView: the sanitising boundary (T4)
        ├── components/ui/Dialog.tsx                             # full-screen below sm (T4)
        ├── components/ui/StatusBadge.tsx                        # item status → label + tone (T4)
        ├── components/shell/AppShell.tsx, AppShell.test.tsx     # collapsible nav (T4); "My tasks" link (T7)
        ├── features/uploads/
        │   ├── types.ts, limits.ts, limits.test.ts              # guards (T5)
        │   ├── events.ts, events.test.ts                        # ItemStatusEvent, applyItemEvent (T5)
        │   ├── useUploadProgress.ts, useUploadProgress.test.tsx # EventSource hook with polling fallback (T5)
        │   ├── FileRow.tsx, UploadWizard.tsx, UploadWizard.test.tsx, UploadProgress.tsx, UploadProgress.test.tsx (T5)
        ├── features/tasks/TasksPage.tsx, TasksPage.test.tsx, ConfirmTypeDialog.tsx, ConfirmTypeDialog.test.tsx (T7)
        ├── features/documents/
        │   ├── types.ts, DocumentBrowser.tsx, DocumentBrowser.test.tsx, DocumentPage.tsx, DocumentPage.test.tsx,
        │   │   FrontmatterPanel.tsx, EditDocumentDialog.tsx, GapReport.tsx, GapReport.test.tsx (T6)
        ├── features/projects/ProjectPage.tsx, ProjectPage.test.tsx   # tabs: Documents, Overview, Gap report, Members, Settings (T6)
        └── app/(app)/
            ├── projects/[projectId]/upload/page.tsx (T5), uploads/[uploadId]/page.tsx (T5)
            ├── tasks/page.tsx (T7)
            └── documents/[documentId]/page.tsx (T6)
```

## Execution waves

Tasks are written so that a wave's tasks touch disjoint files; parallel implementers work in separate worktrees and the controller merges each wave before the next starts.

| Wave | Tasks (parallel) | Shared files to watch |
|---|---|---|
| 1 | **T1** events table + recording (backend), **T2** document content, listing metadata, upload limits, typed gap report (backend), **T4** frontend foundation: dependencies, messages, Tabs, MarkdownView, upload helper, test doubles, responsive shell and dialog | T1 and T2 both change `frontend/openapi.json` indirectly → regenerated on merge; T4 is the only task that edits `package.json`/`pnpm-lock.yaml`; T4 pre-defines every string later tasks use |
| 2 | **T3** SSE endpoint (backend; needs T1), **T5** upload wizard + live progress (frontend; needs T2's `schema.d.ts` and T4), **T6** document browser, document page, gap report, project tabs (frontend; needs T2 and T4), **T7** My tasks + type confirmation (frontend; needs T4) | `src/messages.ts` is read-only in wave 2 (additions only appended at the end of the owning section: T5 → `uploads`, T6 → `documents`/`gaps`, T7 → `tasks`); T7 is the only wave-2 task editing `AppShell.tsx`; T6 is the only one editing `ProjectPage*.tsx` and `e2e/first-run.spec.ts`; T3 is the only one editing `routes/uploads.py` and `services/events.py` |
| 3 | **T8** Playwright flow (upload → live progress → read → download → gap report; mobile smoke), **T9** documentation (frontend README, root README, roadmap, PENDING) | none (T8 owns `e2e/`; T9 owns the docs) |

**Controller merge step after every wave** (on the integration branch, from the repository root):

```bash
(cd backend && uv run python -m app.openapi_export ../frontend/openapi.json)
(cd frontend && pnpm install --frozen-lockfile && pnpm api:generate && pnpm format:write)
git add frontend/openapi.json frontend/src/lib/api/schema.d.ts && git commit -m "chore: refresh generated OpenAPI files" || true
(cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run pytest -q)
(cd frontend && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build)
```

Never hand-merge `frontend/openapi.json`, `frontend/src/lib/api/schema.d.ts` or `frontend/pnpm-lock.yaml`: take either side and regenerate (`pnpm install` rewrites the lockfile from `package.json`). After wave 1 the lockfile comes from T4's worktree; T5–T7 worktrees run `pnpm install --frozen-lockfile` once after branching from the merged wave 1. After wave 2 run the Playwright suite once (`cd frontend && pnpm e2e`) before starting wave 3, so T8 starts from a green suite. Wave-2 frontend tasks consume backend endpoints that exist on the integration branch after wave 1 (T5 also needs T3's stream, but it codes against the event contract in this plan and tests with a fake `EventSource`; the real stream is exercised by T8).

---

### Task 1: `events` table, migration 0004, and event rows for every upload-item transition

**Files:**
- Modify: `backend/app/db/models/ingestion.py` (constants after `TERMINAL_STATUSES`; new class at the end), `backend/app/db/models/__init__.py`, `backend/app/services/pipeline.py` (`transition`, `publish_item_by_id`, `requeue_stale_items`, imports), `backend/app/services/uploads.py` (`confirm_type`, `retry_item`, imports)
- Create: `backend/app/services/events.py`, `backend/migrations/versions/0004_events.py`, `backend/tests/ingestion/test_events.py`
- Test: `backend/tests/db/test_models.py` (append two tests), `backend/tests/ingestion/test_events.py`

**Interfaces:**
- Consumes: `UploadItem`, `Upload` (Plan 2), `transition()` and the pipeline flow in `app/services/pipeline.py`, `confirm_type`/`retry_item` in `app/services/uploads.py`, `tests/helpers/ingest.ingest`, `FakeAnalyzer`/`ScriptedVerdict`.
- Produces: `app.db.models.ingestion.ACTIVE_STATUSES = ("uploaded", "converting", "checking", "publishing")`, `ITEM_STATUS_EVENT = "item.status"`, `UploadEvent` (table `events`: `id: int`, `upload_id`, `item_id | None`, `type`, `payload: dict`, `created_at`); `app.services.events`: `PAYLOAD_FIELDS`, `item_status_payload(item_id, status, fields) -> dict`, `async record_item_status(db, *, upload_id, item_id, status, **fields) -> None` (never commits), `async events_after(db, upload_id, after_id, *, limit=500) -> list[UploadEvent]`, `async is_settled(db, upload_id) -> bool`; `pipeline.transition(db, item_id, from_statuses, to_status, *, extra=None, **values) -> bool` now records the event; `pipeline.ACTIVE_STATUSES` is re-exported from the model module (same name, same tuple). Task 3 builds the stream on `events_after` and `is_settled`.

- [ ] **Step 1: Write the failing model tests**

Append to `backend/tests/db/test_models.py` (add `UploadEvent` to the `from app.db.models import (...)` list):

```python
async def test_event_ids_are_monotonic_and_payload_round_trips(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.flush()
    project = Project(slug="demo", name="Demo", created_by=user.id)
    db.add(project)
    await db.flush()
    upload = Upload(project_id=project.id, uploaded_by=user.id)
    db.add(upload)
    await db.flush()
    first = UploadEvent(upload_id=upload.id, type="item.status", payload={"status": "converting"})
    second = UploadEvent(upload_id=upload.id, type="item.status", payload={"status": "checking"})
    db.add_all([first, second])
    await db.commit()
    assert isinstance(first.id, int) and second.id > first.id
    rows = (
        await db.scalars(
            select(UploadEvent).where(UploadEvent.upload_id == upload.id).order_by(UploadEvent.id)
        )
    ).all()
    assert [r.payload["status"] for r in rows] == ["converting", "checking"]
    assert rows[0].item_id is None and rows[0].created_at is not None


async def test_events_are_deleted_with_their_upload(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.flush()
    project = Project(slug="demo", name="Demo", created_by=user.id)
    db.add(project)
    await db.flush()
    upload = Upload(project_id=project.id, uploaded_by=user.id)
    db.add(upload)
    await db.flush()
    db.add(UploadEvent(upload_id=upload.id, type="item.status", payload={}))
    await db.commit()
    await db.delete(upload)
    await db.commit()
    assert (await db.scalar(select(func.count()).select_from(UploadEvent))) == 0
```

Add `func` to the `from sqlalchemy import select` line: `from sqlalchemy import func, select`.

- [ ] **Step 2: Run the model tests to verify they fail**

Run (from `backend/`): `uv run pytest tests/db/test_models.py -q -k "event"`
Expected: FAIL with `ImportError: cannot import name 'UploadEvent'`.

- [ ] **Step 3: Model, exports and migration**

In `backend/app/db/models/ingestion.py`, add `Identity` and `Index` to the `from sqlalchemy import (...)` list, and after `TERMINAL_STATUSES = ("published", "failed")` add:

```python
ACTIVE_STATUSES = ("uploaded", "converting", "checking", "publishing")  # work in progress
ITEM_STATUS_EVENT = "item.status"
```

Append at the end of the file:

```python
class UploadEvent(Base):
    """One row per upload-item state change (spec 10 ``events``), written in the same
    transaction as the change; ``id`` is the Server-Sent Events id and ``Last-Event-ID``."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_upload_id_id", "upload_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("upload_items.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

In `backend/app/db/models/__init__.py` import `ACTIVE_STATUSES`, `ITEM_STATUS_EVENT`, `UploadEvent` from `app.db.models.ingestion` and add `"ACTIVE_STATUSES"`, `"ITEM_STATUS_EVENT"`, `"UploadEvent"` to `__all__` (keep the list sorted the way it is: constants first, then classes).

Create `backend/migrations/versions/0004_events.py`:

```python
"""events: one row per upload-item state change, replayed over Server-Sent Events

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("upload_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=True),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["upload_items.id"],
            name=op.f("fk_events_item_id_upload_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"], ["uploads.id"], name=op.f("fk_events_upload_id_uploads"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_upload_id_id", "events", ["upload_id", "id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_events_upload_id_id", table_name="events")
    op.drop_table("events")
```

- [ ] **Step 4: Run the model and migration tests**

Run: `uv run pytest tests/db -q`
Expected: PASS (including `test_migrations_match_models`, which applies 0001–0004 to an empty database and diffs against the ORM; an empty diff proves the identity column and composite index match).

- [ ] **Step 5: Write the failing event-recording tests**

Create `backend/tests/ingestion/test_events.py`:

```python
"""Every upload-item transition writes one ``item.status`` event row in the same transaction
as the change, so a replay can never disagree with the item."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import DocumentVersion, UploadEvent, UploadItem
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services import events
from app.services.pipeline import publish_confirmed_item, requeue_stale_items, run_upload
from app.services.uploads import confirm_type, retry_item
from tests.factories import make_project, make_user
from tests.helpers.files import docx_bytes
from tests.helpers.ingest import ingest, pipeline_context

PLAN = docx_bytes(
    ["Scope of testing: login, upload and publish flows. Entry criteria: build green."]
)
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
ALLOWED_KEYS = {"item_id", "status", *events.PAYLOAD_FIELDS}


async def _rows(db: AsyncSession, upload_id: uuid.UUID) -> list[UploadEvent]:
    db.expire_all()
    return list(
        (
            await db.scalars(
                select(UploadEvent).where(UploadEvent.upload_id == upload_id).order_by(UploadEvent.id)
            )
        ).all()
    )


def _statuses(rows: list[UploadEvent], item_id: uuid.UUID) -> list[str]:
    return [r.payload["status"] for r in rows if r.item_id == item_id]


async def test_every_transition_writes_one_event_in_order(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Reads like a plan.", "test-plan")})
    upload, items, _ = await ingest(
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
    rows = await _rows(db, upload.id)
    assert all(r.type == "item.status" for r in rows)
    assert [r.id for r in rows] == sorted(r.id for r in rows)
    assert _statuses(rows, by_name["srs.docx"].id) == [
        "converting",
        "checking",
        "publishing",
        "published",
    ]
    assert _statuses(rows, by_name["plan.docx"].id) == [
        "converting",
        "checking",
        "needs_confirmation",
    ]
    published = [r for r in rows if r.payload["status"] == "published"][0]
    version = await db.scalar(
        select(DocumentVersion).where(DocumentVersion.upload_item_id == by_name["srs.docx"].id)
    )
    assert version is not None
    assert published.payload["document_id"] == str(version.document_id)
    assert published.payload["version"] == 1
    publishing = [
        r for r in rows if r.item_id == by_name["srs.docx"].id and r.payload["status"] == "publishing"
    ][0]
    assert publishing.payload["type_check"] == "match"  # the verdict travels with that transition
    waiting = [r for r in rows if r.payload["status"] == "needs_confirmation"][0]
    assert waiting.payload["suggested_doc_type"] == "test-plan"
    assert waiting.payload["check_explanation"] == "Reads like a plan."
    for row in rows:
        assert set(row.payload) <= ALLOWED_KEYS, row.payload  # never content or metadata
        assert row.payload["item_id"] == str(row.item_id)


async def test_confirm_publish_and_retry_record_events(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Looks wrong.", "test-plan")})
    upload, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("plan.docx", PLAN), ("broken.docx", b"not a docx")],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="srs")],
        analyzer=fake,
    )
    by_name = {i.original_name: i for i in items}
    waiting, broken = by_name["plan.docx"], by_name["broken.docx"]
    assert await events.is_settled(db, upload.id)  # waiting + failed: nothing in progress
    await confirm_type(
        db, waiting, doc_type_key="test-plan", taxonomy=taxonomy, actor=owner, project_id=project.id
    )
    assert not await events.is_settled(db, upload.id)
    waiting_id, broken_id = waiting.id, broken.id
    rows = await _rows(db, upload.id)
    confirmed = [r for r in rows if r.item_id == waiting_id][-1]
    assert confirmed.payload["status"] == "publishing"
    assert confirmed.payload["final_doc_type"] == "test-plan"
    assert confirmed.payload["type_check"] == "mismatch_changed"
    await publish_confirmed_item(pipeline_context(settings, taxonomy, fake), waiting_id)
    rows = await _rows(db, upload.id)
    assert _statuses(rows, waiting_id)[-2:] == ["publishing", "published"]
    assert await events.is_settled(db, upload.id)
    failed = [r for r in rows if r.item_id == broken_id][-1]
    assert failed.payload["status"] == "failed"
    assert failed.payload["error"] == "File content does not match its extension."
    broken = await db.get_one(UploadItem, broken_id)
    await retry_item(db, broken, actor=owner, project_id=project.id)
    rows = await _rows(db, upload.id)
    retried = [r for r in rows if r.item_id == broken_id][-1]
    assert retried.payload == {"item_id": str(broken_id), "status": "uploaded", "error": None}


async def test_events_after_returns_only_later_rows(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    rows = await _rows(db, upload.id)
    assert len(rows) == 4
    later = await events.events_after(db, upload.id, rows[1].id)
    assert [r.id for r in later] == [rows[2].id, rows[3].id]
    assert await events.events_after(db, upload.id, rows[-1].id) == []
    assert [r.id for r in await events.events_after(db, upload.id, 0, limit=2)] == [
        rows[0].id,
        rows[1].id,
    ]


async def test_failed_conversion_records_failed_in_the_same_commit(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, staging_root: Path
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    upload, items, _ = await ingest(
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
    staged = staging_root / items[0].staging_path
    staged.unlink()  # the staged file disappears before conversion
    await run_upload(pipeline_context(settings, taxonomy), upload.id)
    rows = await _rows(db, upload.id)
    assert _statuses(rows, items[0].id) == ["converting", "failed"]
    assert rows[-1].payload["error"].startswith("Staged file is no longer available")
    item = await db.get_one(UploadItem, items[0].id)
    assert item.status == "failed"  # the row and the status were committed together


async def test_requeue_records_the_restart(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, taxonomy: Taxonomy
) -> None:
    async with db_sessionmaker() as db:
        owner = await make_user(db, settings)
        project = await make_project(db, settings, taxonomy, owner=owner)
        upload, items, _ = await ingest(
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
        item_id, upload_id = items[0].id, upload.id
    assert await requeue_stale_items(pipeline_context(settings, taxonomy)) == 1
    for _ in range(100):
        async with db_sessionmaker() as db:
            item = await db.get_one(UploadItem, item_id)
            if item.status in ("published", "failed"):
                break
        await asyncio.sleep(0.05)
    async with db_sessionmaker() as db:
        rows = await _rows(db, upload_id)
    statuses: list[Any] = _statuses(rows, item_id)
    assert statuses[0] == "uploaded"  # the restart itself is an event
    assert statuses[-1] == "published"
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `uv run pytest tests/ingestion/test_events.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.events'`.

- [ ] **Step 7: The events service**

Create `backend/app/services/events.py`:

```python
"""Upload events (spec 10 ``events``, spec 11 SSE): one ``item.status`` row per upload-item
state change, added to the same session (and therefore the same transaction) as the change.
Like ``audit.record``, nothing here commits. Task 3 adds the Server-Sent Events stream."""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ACTIVE_STATUSES, ITEM_STATUS_EVENT, UploadEvent, UploadItem

# The only fields a payload may carry besides ``item_id`` and ``status``: ids, verdicts and
# short messages. Never conversion metadata, outlines, file names or document content.
PAYLOAD_FIELDS = frozenset(
    {
        "type_check",
        "check_explanation",
        "suggested_doc_type",
        "final_doc_type",
        "error",
        "document_id",
        "version",
    }
)
EVENT_PAGE = 500


def item_status_payload(
    item_id: uuid.UUID, status: str, fields: Mapping[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {"item_id": str(item_id), "status": status}
    for key, value in fields.items():
        if key in PAYLOAD_FIELDS:
            payload[key] = str(value) if isinstance(value, uuid.UUID) else value
    return payload


async def record_item_status(
    db: AsyncSession, *, upload_id: uuid.UUID, item_id: uuid.UUID, status: str, **fields: Any
) -> None:
    """Queue an ``item.status`` event on ``db``. The caller's commit writes it together with
    the state change it describes."""
    db.add(
        UploadEvent(
            upload_id=upload_id,
            item_id=item_id,
            type=ITEM_STATUS_EVENT,
            payload=item_status_payload(item_id, status, fields),
        )
    )


async def events_after(
    db: AsyncSession, upload_id: uuid.UUID, after_id: int, *, limit: int = EVENT_PAGE
) -> list[UploadEvent]:
    """Events of one upload with ``id > after_id``, oldest first (the SSE replay query)."""
    return list(
        (
            await db.scalars(
                select(UploadEvent)
                .where(UploadEvent.upload_id == upload_id, UploadEvent.id > after_id)
                .order_by(UploadEvent.id)
                .limit(limit)
            )
        ).all()
    )


async def is_settled(db: AsyncSession, upload_id: uuid.UUID) -> bool:
    """True when no item of the upload is still being worked on. Items waiting for the user
    (``needs_confirmation``) count as settled: nothing happens until the user acts."""
    active = await db.scalar(
        select(func.count())
        .select_from(UploadItem)
        .where(UploadItem.upload_id == upload_id, UploadItem.status.in_(list(ACTIVE_STATUSES)))
    )
    return not active
```

- [ ] **Step 8: Record events in the pipeline**

In `backend/app/services/pipeline.py`:

Replace the imports `from collections.abc import Coroutine, Sequence` with `from collections.abc import Coroutine, Mapping, Sequence`; replace `from app.db.models import Document, Project, Upload, UploadItem, User` with `from app.db.models import ACTIVE_STATUSES, Document, Project, Upload, UploadItem, User`; add `from app.services import audit, events` in place of `from app.services import audit`; delete the line `ACTIVE_STATUSES = ("uploaded", "converting", "checking", "publishing")` (the constant now lives in the model module and is imported above, so `pipeline.ACTIVE_STATUSES` keeps working).

Replace `transition`:

```python
async def transition(
    db: AsyncSession,
    item_id: uuid.UUID,
    from_statuses: Sequence[str],
    to_status: str,
    *,
    extra: Mapping[str, Any] | None = None,
    **values: Any,
) -> bool:
    """Atomically move an item between states and queue the matching ``item.status`` event on
    the same session; False when it was not in ``from_statuses`` (then nothing is queued).
    ``extra`` adds payload-only fields such as the published document id."""
    row = (
        await db.execute(
            update(UploadItem)
            .where(UploadItem.id == item_id, UploadItem.status.in_(list(from_statuses)))
            .values(status=to_status, updated_at=datetime.now(UTC), **values)
            .returning(UploadItem.id, UploadItem.upload_id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is None:
        return False
    await events.record_item_status(
        db,
        upload_id=row.upload_id,
        item_id=item_id,
        status=to_status,
        **values,
        **dict(extra or {}),
    )
    return True
```

In `publish_item_by_id`, replace `if await transition(db, item_id, ("publishing",), "published", error=None):` with:

```python
            if await transition(
                db,
                item_id,
                ("publishing",),
                "published",
                extra={"document_id": document_id, "version": version.version},
                error=None,
            ):
```

In `requeue_stale_items`, replace the block that computes `rows` and the final loops so the restart is recorded for each item before the commit:

```python
    async with maker() as db:
        rows = (
            await db.execute(
                update(UploadItem)
                .where(UploadItem.status.in_(restart))
                .values(status="uploaded", updated_at=datetime.now(UTC))
                .returning(UploadItem.id, UploadItem.upload_id)
                .execution_options(synchronize_session=False)
            )
        ).all()
        for item_id, upload_id in rows:
            await events.record_item_status(db, upload_id=upload_id, item_id=item_id, status="uploaded")
        publishing = list(
            (
                await db.scalars(
                    select(UploadItem.id)
                    .where(UploadItem.status == "publishing")
                    .order_by(UploadItem.created_at)
                )
            ).all()
        )
        await db.commit()
    for upload_id in {upload_id for (_item_id, upload_id) in rows}:
        _spawn(run_upload(ctx, upload_id), "upload", upload_id)
    for item_id in publishing:
        _spawn(publish_item_by_id(ctx, maker, item_id), "upload item", item_id)
    return len(rows) + len(publishing)
```

- [ ] **Step 9: Record events for the user's actions**

In `backend/app/services/uploads.py`, change `from app.services import audit` to `from app.services import audit, events`. In `confirm_type`, directly before `await audit.record(` add:

```python
    await events.record_item_status(
        db,
        upload_id=item.upload_id,
        item_id=item.id,
        status="publishing",
        final_doc_type=item.final_doc_type,
        type_check=item.type_check,
    )
```

In `retry_item`, directly before `await audit.record(` add:

```python
    await events.record_item_status(
        db, upload_id=item.upload_id, item_id=item.id, status="uploaded", error=None
    )
```

- [ ] **Step 10: Run the whole backend suite and the checks**

Run: `uv run pytest -q && uv run ruff format . && uv run ruff check . && uv run mypy app`
Expected: PASS; the existing pipeline, publish and upload tests are unchanged in behaviour (they do not count events). `test_committed_frontend_document_is_current` in `tests/api/test_openapi_export.py` still passes because this task adds no route.

- [ ] **Step 11: Commit**

```bash
git add backend/app/db/models/ingestion.py backend/app/db/models/__init__.py backend/app/services/events.py backend/app/services/pipeline.py backend/app/services/uploads.py backend/migrations/versions/0004_events.py backend/tests/db/test_models.py backend/tests/ingestion/test_events.py
git commit -m "feat(backend): record an item.status event for every upload-item transition"
```

### Task 2: Document content endpoint, uploader and date in the listing, upload limits, typed gap report

**Files:**
- Modify: `backend/app/schemas/documents.py`, `backend/app/schemas/uploads.py`, `backend/app/services/documents.py`, `backend/app/api/routes/documents.py`, `backend/app/api/routes/taxonomy.py`, `backend/tests/api/test_documents.py`, `backend/tests/api/test_uploads.py`
- Regenerate after the task (controller does it on merge too): `frontend/openapi.json`

**Interfaces:**
- Consumes: `DocumentAccess`, `AnyMember`, `InternalMember`, `CurrentUser`, `AppSettings` (deps), `documents_service.get_version`, `naming.split_frontmatter`, `build_gap_report(...).to_dict()`, `ALLOWED_EXTENSIONS` and `ZIP_MAX_ENTRIES` from `app.ingestion.intake`.
- Produces: `DocumentOut` + `uploaded_by_name: str | None`, `version_created_at: datetime | None`; `DocumentContentOut {version, frontmatter: dict, body, markdown_name, original_name | None}` at `GET /documents/{document_id}/versions/{version}/content`; `GapReportOut {qc_agent, project{slug,name}, generated_at, required_total, required_present, completeness, folders[{id,dir,stage,doc_types[{doc_type,title,required,status,documents}]}]}` as the response model of `GET /projects/{project_id}/gap-report`; `UploadLimitsOut {max_file_mb, max_batch_mb, allowed_extensions: list[str], zip_max_entries}` at `GET /upload-limits`; `documents_service.current_version_meta(db, document_ids) -> dict[uuid.UUID, VersionMeta]` and `documents_service.split_content(markdown_text) -> tuple[dict[str, Any], str]`. Tasks 5 and 6 consume these through the regenerated `schema.d.ts`.

- [ ] **Step 1: Write the failing API tests**

Append to `backend/tests/api/test_documents.py`:

```python
async def test_listing_carries_uploader_and_version_date(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    documents = (await clients["viewer"].get(f"/api/v1/projects/{project.id}/documents")).json()
    by_id = {d["id"]: d for d in documents}
    assert by_id[ids["srs"]]["uploaded_by_name"] == "Editor"
    assert by_id[ids["srs"]]["version_created_at"] is not None
    stub = next(d for d in documents if d["is_stub"])
    assert stub["uploaded_by_name"] == "Owner"  # stubs are created by the project creator
    single = (await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}")).json()
    assert single["uploaded_by_name"] == "Editor" and single["version_created_at"] is not None


async def test_version_content_returns_frontmatter_and_body(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    content = await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/1/content")
    assert content.status_code == 200
    body = content.json()
    assert body["version"] == 1
    assert body["markdown_name"] == "srs--portal-srs.md"
    assert body["original_name"] == "srs--portal-srs.docx"
    fm = body["frontmatter"]
    assert fm["doc_type"] == "srs" and fm["version"] == 1 and fm["kind"] == "converted"
    assert fm["uploaded_by"] == "Editor" and fm["type_check"] == "skipped"
    assert fm["visibility"] == "internal" and "uploaded_at" in fm
    assert not body["body"].startswith("---")
    assert "The system shall allow users" in body["body"]
    # clients: shared only; unknown version: 404
    assert (
        await clients["client"].get(f"/api/v1/documents/{ids['srs']}/versions/1/content")
    ).status_code == 404
    shared = await clients["client"].get(f"/api/v1/documents/{ids['runbook']}/versions/1/content")
    assert shared.status_code == 200 and "Restart." in shared.json()["body"]
    assert (
        await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/9/content")
    ).status_code == 404
    stub = (await db.scalars(select(Document).where(Document.is_stub.is_(True)))).first()
    assert stub is not None
    stub_content = (
        await clients["viewer"].get(f"/api/v1/documents/{stub.id}/versions/1/content")
    ).json()
    assert stub_content["frontmatter"]["kind"] == "stub" and stub_content["original_name"] is None


async def test_gap_report_is_typed(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, _ = await _world(make_client, db, settings, taxonomy)
    report = (await clients["owner"].get(f"/api/v1/projects/{project.id}/gap-report")).json()
    assert report["project"] == {"slug": project.slug, "name": "Demo"}
    assert set(report) == {
        "qc_agent",
        "project",
        "generated_at",
        "required_total",
        "required_present",
        "completeness",
        "folders",
    }
    assert [f["id"] for f in report["folders"]][:2] == ["overview", "requirements"]
    entry = report["folders"][1]["doc_types"][1]
    assert entry == {
        "doc_type": "srs",
        "title": "Software Requirements Specification",
        "required": True,
        "status": "present",
        "documents": 1,
    }
```

Append to `backend/tests/api/test_uploads.py`:

```python
async def test_upload_limits_endpoint(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, users = await _members(db, settings, taxonomy)
    viewer = await _client(make_client, db, settings, users["viewer"])
    response = await viewer.get("/api/v1/upload-limits")
    assert response.status_code == 200
    assert response.json() == {
        "max_file_mb": settings.max_upload_file_mb,
        "max_batch_mb": settings.max_upload_batch_mb,
        "allowed_extensions": ["csv", "docx", "html", "md", "pdf", "pptx", "txt", "xlsx", "zip"],
        "zip_max_entries": 200,
    }
    anonymous = await make_client()
    assert (await anonymous.get("/api/v1/upload-limits")).status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_documents.py tests/api/test_uploads.py -q -k "uploader or content or typed or limits"`
Expected: FAIL — `KeyError: 'uploaded_by_name'`, 404s on `/content`, `assert set(report) == {...}` passes but the entry assertion may already pass (the dict shape is the same; the type is what changes), 404 on `/upload-limits`.

- [ ] **Step 3: Schemas**

In `backend/app/schemas/documents.py`, change the imports to `from typing import Any, Literal` and extend `DocumentOut` (after `updated_at: datetime`):

```python
    uploaded_by_name: str | None = None  # display name of the current version's uploader
    version_created_at: datetime | None = None
```

Append to the same file:

```python
class DocumentContentOut(BaseModel):
    """One version's converted Markdown split into frontmatter and body (spec 5.3)."""

    version: int
    frontmatter: dict[str, Any]
    body: str
    markdown_name: str
    original_name: str | None


class GapEntryOut(BaseModel):
    doc_type: str
    title: str
    required: bool
    status: Literal["present", "stub", "missing"]
    documents: int


class GapFolderOut(BaseModel):
    id: str
    dir: str
    stage: str
    doc_types: list[GapEntryOut]


class GapProjectOut(BaseModel):
    slug: str
    name: str


class GapReportOut(BaseModel):
    qc_agent: int
    project: GapProjectOut
    generated_at: datetime
    required_total: int
    required_present: int
    completeness: float
    folders: list[GapFolderOut]
```

Append to `backend/app/schemas/uploads.py`:

```python
class UploadLimitsOut(BaseModel):
    """What the wizard checks before sending a byte; mirrors the server's intake limits."""

    max_file_mb: int
    max_batch_mb: int
    allowed_extensions: list[str]
    zip_max_entries: int
```

- [ ] **Step 4: Service helpers**

In `backend/app/services/documents.py`, change `from collections.abc import Sequence` to `from collections.abc import Iterable, Sequence`, add `from dataclasses import dataclass` and `from typing import Any`, and `from app.ingestion.naming import split_frontmatter`. Append:

```python
@dataclass(frozen=True)
class VersionMeta:
    uploaded_by_name: str
    created_at: datetime


async def current_version_meta(
    db: AsyncSession, document_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, VersionMeta]:
    """Uploader display name and date of each document's current version (one query)."""
    ids = list(document_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(DocumentVersion.document_id, User.display_name, DocumentVersion.created_at)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(User, User.id == DocumentVersion.uploaded_by)
            .where(
                DocumentVersion.document_id.in_(ids),
                DocumentVersion.version == Document.current_version,
            )
        )
    ).all()
    return {
        document_id: VersionMeta(uploaded_by_name=name, created_at=created_at)
        for document_id, name, created_at in rows
    }


def split_content(markdown_text: str) -> tuple[dict[str, Any], str]:
    """Frontmatter mapping and body; a file without valid frontmatter is all body."""
    try:
        return split_frontmatter(markdown_text)
    except ValueError:
        return {}, markdown_text
```

- [ ] **Step 5: Routes**

In `backend/app/api/routes/documents.py`:

Replace the `from app.schemas.documents import (...)` block with:

```python
from app.schemas.documents import (
    DocumentContentOut,
    DocumentOut,
    DocumentUpdate,
    DocumentVersionOut,
    GapReportOut,
    VersionSuggestionOut,
)
```

Remove `from typing import Any` (no longer used). Add after `_attachment`:

```python
def _document_out(
    document: Document, meta: Mapping[uuid.UUID, documents_service.VersionMeta]
) -> DocumentOut:
    current = meta.get(document.id)
    return DocumentOut.model_validate(document).model_copy(
        update={
            "uploaded_by_name": current.uploaded_by_name if current else None,
            "version_created_at": current.created_at if current else None,
        }
    )
```

with the imports `import uuid`, `from collections.abc import Mapping` and `from app.db.models import Document` added at the top.

Replace the body of `list_documents` after the service call:

```python
    meta = await documents_service.current_version_meta(db, (d.id for d in documents))
    return [_document_out(d, meta) for d in documents]
```

Replace `gap_report`:

```python
@router.get("/projects/{project_id}/gap-report", response_model=GapReportOut)
async def gap_report(ctx: InternalMember, db: DbSession, taxonomy: TaxonomyDep) -> GapReportOut:
    report = build_gap_report(
        taxonomy,
        await document_facts(db, ctx.project.id),
        project_slug=ctx.project.slug,
        project_name=ctx.project.name,
        generated_at=datetime.now(UTC),
    )
    return GapReportOut.model_validate(report.to_dict())
```

Replace `get_document`:

```python
@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(ctx: DocumentAccess, db: DbSession) -> DocumentOut:
    meta = await documents_service.current_version_meta(db, [ctx.document.id])
    return _document_out(ctx.document, meta)
```

Add after `download_markdown`:

```python
@router.get(
    "/documents/{document_id}/versions/{version}/content", response_model=DocumentContentOut
)
async def version_content(version: int, ctx: DocumentAccess, db: DbSession) -> DocumentContentOut:
    row = await documents_service.get_version(db, ctx.document.id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    frontmatter, body = documents_service.split_content(row.markdown_text)
    return DocumentContentOut(
        version=row.version,
        frontmatter=frontmatter,
        body=body,
        markdown_name=PurePosixPath(row.markdown_path).name,
        original_name=PurePosixPath(row.original_path).name if row.original_path else None,
    )
```

In `update_document`, replace the final `return DocumentOut.model_validate(ctx.document)` with:

```python
    meta = await documents_service.current_version_meta(db, [ctx.document.id])
    return _document_out(ctx.document, meta)
```

Replace `backend/app/api/routes/taxonomy.py`:

```python
from fastapi import APIRouter

from app.api.deps import AppSettings, CurrentUser, TaxonomyDep
from app.ingestion.intake import ALLOWED_EXTENSIONS, ZIP_MAX_ENTRIES
from app.schemas.taxonomy import TaxonomyOut
from app.schemas.uploads import UploadLimitsOut

router = APIRouter(tags=["meta"])


@router.get("/taxonomy", response_model=TaxonomyOut)
async def get_taxonomy(_: CurrentUser, taxonomy: TaxonomyDep) -> TaxonomyOut:
    return TaxonomyOut.from_taxonomy(taxonomy)


@router.get("/upload-limits", response_model=UploadLimitsOut)
async def get_upload_limits(_: CurrentUser, settings: AppSettings) -> UploadLimitsOut:
    """The intake limits the upload wizard enforces before sending anything."""
    return UploadLimitsOut(
        max_file_mb=settings.max_upload_file_mb,
        max_batch_mb=settings.max_upload_batch_mb,
        allowed_extensions=sorted(ALLOWED_EXTENSIONS),
        zip_max_entries=ZIP_MAX_ENTRIES,
    )
```

- [ ] **Step 6: Run the tests, regenerate the OpenAPI document**

Run: `uv run pytest tests/api -q`
Expected: every test passes except `test_committed_frontend_document_is_current`, which reports the document is stale. Then:

```bash
uv run python -m app.openapi_export ../frontend/openapi.json
uv run pytest tests/api/test_openapi_export.py -q
uv run ruff format . && uv run ruff check . && uv run mypy app
```

Expected: PASS. (The controller regenerates `openapi.json` and `schema.d.ts` again on merge; do not run `pnpm api:generate` in this worktree.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/documents.py backend/app/schemas/uploads.py backend/app/services/documents.py backend/app/api/routes/documents.py backend/app/api/routes/taxonomy.py backend/tests/api/test_documents.py backend/tests/api/test_uploads.py frontend/openapi.json
git commit -m "feat(backend): document content endpoint, uploader in listings, upload limits, typed gap report"
```

### Task 3: `GET /uploads/{upload_id}/events` — replay, polling stream, heartbeat, settled

**Files:**
- Modify: `backend/app/services/events.py` (append), `backend/app/api/routes/uploads.py` (imports; one route appended after `get_upload`)
- Create: `backend/tests/api/test_upload_events.py`
- Regenerate after the task: `frontend/openapi.json`

**Interfaces:**
- Consumes: `events_after`, `is_settled`, `EVENT_PAGE` (Task 1), `_upload_for` (existing auth helper in `routes/uploads.py`), `get_sessionmaker` (`app.db.session`), `CurrentUser`, `DbSession`.
- Produces: `events.RETRY_MS = 2000`, `events.HEARTBEAT = ": ping\n\n"`, `events.SETTLED_EVENT = "upload.settled"`, `events.SSE_HEADERS`, `events.sse_frame(event_type, data, event_id=None) -> str`, `events.parse_last_event_id(value: str | None) -> int`, `async events.stream_upload_events(maker, upload_id, *, last_event_id=0, poll_interval=0.5, heartbeat_interval=15.0) -> AsyncIterator[str]`; route `GET /api/v1/uploads/{upload_id}/events`. Frame contract the frontend (Task 5) relies on: `retry: 2000` first; then `id: <int>\nevent: item.status\ndata: <json payload from Task 1>\n\n` per row; `: ping\n\n` comments while idle; finally `event: upload.settled\ndata: {"upload_id": "<uuid>", "last_event_id": <int>}\n\n` (no `id:` line, so the browser's `lastEventId` stays on the last row) and the response ends.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/test_upload_events.py`:

```python
"""Server-Sent Events for one upload: replay after Last-Event-ID, authorisation like
GET /uploads/{id}, live delivery, heartbeat, termination, and no session held between polls.

``httpx.ASGITransport`` returns the body only when the app finishes, so the HTTP tests use
uploads whose stream terminates (settled uploads replay and close at once); live delivery,
heartbeats and disconnects are tested on the generator itself with a counting session maker."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import Project, UploadItem, User
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services import events
from app.services.pipeline import run_upload
from tests.factories import add_member, make_project, make_session_token, make_user
from tests.helpers.files import docx_bytes
from tests.helpers.ingest import ingest, pipeline_context

MakeClient = Callable[..., Awaitable[AsyncClient]]
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
PLAN = docx_bytes(["Scope of testing: login, upload and publish flows. Entry criteria: build."])


def _frames(text: str) -> list[dict[str, str]]:
    """Parse an SSE body into frames of field -> value (comments kept under ``comment``)."""
    frames: list[dict[str, str]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        frame: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            else:
                field, _, value = line.partition(":")
                frame[field] = value.strip()
        frames.append(frame)
    return frames


class CountingMaker:
    """Wraps a sessionmaker so a test can see how many sessions are open at any moment."""

    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self.maker = maker
        self.opened = 0
        self.closed = 0
        self.max_open = 0

    @property
    def open(self) -> int:
        return self.opened - self.closed

    def __call__(self) -> "CountingMaker._Ctx":
        return CountingMaker._Ctx(self)

    class _Ctx:
        def __init__(self, counter: "CountingMaker") -> None:
            self.counter = counter
            self.session: AsyncSession | None = None

        async def __aenter__(self) -> AsyncSession:
            self.counter.opened += 1
            self.counter.max_open = max(self.counter.max_open, self.counter.open)
            self.session = self.counter.maker()
            return self.session

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            self.counter.closed += 1
            assert self.session is not None
            await self.session.close()


async def _world(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> tuple[Project, dict[str, User]]:
    owner = await make_user(db, settings, email="owner@example.com", display_name="Owner")
    editor = await make_user(db, settings, email="editor@example.com", display_name="Editor")
    viewer = await make_user(db, settings, email="viewer@example.com", display_name="Viewer")
    client_a = await make_user(
        db, settings, email="a@client.com", display_name="Client A", account_type="customer"
    )
    client_b = await make_user(
        db, settings, email="b@client.com", display_name="Client B", account_type="customer"
    )
    outsider = await make_user(db, settings, email="out@example.com", display_name="Out")
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    for user, role in ((editor, "editor"), (viewer, "viewer"), (client_a, "client"), (client_b, "client")):
        await add_member(db, project, user, role)
    return project, {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "client_a": client_a,
        "client_b": client_b,
        "outsider": outsider,
    }


async def _client(
    make_client: MakeClient, db: AsyncSession, settings: Settings, user: User
) -> AsyncClient:
    return await make_client(await make_session_token(db, settings, user))


def test_parse_last_event_id() -> None:
    assert events.parse_last_event_id(None) == 0
    assert events.parse_last_event_id("") == 0
    assert events.parse_last_event_id("abc") == 0
    assert events.parse_last_event_id("-1") == 0
    assert events.parse_last_event_id("42") == 42


def test_sse_frame_format() -> None:
    assert events.sse_frame("item.status", {"a": 1}, 7) == 'id: 7\nevent: item.status\ndata: {"a":1}\n\n'
    assert events.sse_frame("upload.settled", {"x": "y"}) == 'event: upload.settled\ndata: {"x":"y"}\n\n'


async def test_settled_upload_replays_everything_and_terminates(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _world(db, settings, taxonomy)
    upload, items, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=users["editor"],
        role="editor",
        files=[("srs.docx", SRS)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    editor = await _client(make_client, db, settings, users["editor"])
    response = await editor.get(f"/api/v1/uploads/{upload.id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    frames = _frames(response.text)
    assert frames[0] == {"retry": "2000"}
    statuses = [json.loads(f["data"])["status"] for f in frames if f.get("event") == "item.status"]
    assert statuses == ["converting", "checking", "publishing", "published"]
    ids = [int(f["id"]) for f in frames if f.get("event") == "item.status"]
    assert ids == sorted(ids) and len(set(ids)) == 4
    assert json.loads(frames[-1]["data"]) == {"upload_id": str(upload.id), "last_event_id": ids[-1]}
    assert frames[-1]["event"] == "upload.settled" and "id" not in frames[-1]
    assert json.loads(frames[1]["data"])["item_id"] == str(items[0].id)


async def test_last_event_id_replays_only_later_events_once(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _world(db, settings, taxonomy)
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=users["editor"],
        role="editor",
        files=[("srs.docx", SRS)],
        specs=[UploadItemSpec(doc_type="srs")],
    )
    editor = await _client(make_client, db, settings, users["editor"])
    full = _frames((await editor.get(f"/api/v1/uploads/{upload.id}/events")).text)
    ids = [int(f["id"]) for f in full if "id" in f]
    resumed = await editor.get(
        f"/api/v1/uploads/{upload.id}/events", headers={"Last-Event-ID": str(ids[1])}
    )
    frames = _frames(resumed.text)
    assert [int(f["id"]) for f in frames if "id" in f] == ids[2:]
    assert [f["event"] for f in frames if "event" in f] == [
        "item.status",
        "item.status",
        "upload.settled",
    ]
    beyond = _frames(
        (
            await editor.get(
                f"/api/v1/uploads/{upload.id}/events", headers={"Last-Event-ID": str(ids[-1])}
            )
        ).text
    )
    assert [f.get("event") for f in beyond] == [None, "upload.settled"]  # retry, then settled
    garbage = _frames(
        (
            await editor.get(f"/api/v1/uploads/{upload.id}/events", headers={"Last-Event-ID": "x"})
        ).text
    )
    assert [int(f["id"]) for f in garbage if "id" in f] == ids  # unparsable → from the start


async def test_stream_is_authorised_like_get_upload(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, users = await _world(db, settings, taxonomy)
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=users["client_a"],
        role="client",
        files=[("brd.docx", SRS)],
        specs=[UploadItemSpec(doc_type="brd")],
    )
    url = f"/api/v1/uploads/{upload.id}/events"
    expected = {"client_a": 200, "owner": 200, "editor": 200, "viewer": 200, "client_b": 404, "outsider": 404}
    for name, status in expected.items():
        client = await _client(make_client, db, settings, users[name])
        response = await client.get(url)
        assert response.status_code == status, (name, response.status_code)
    assert (await (await make_client()).get(url)).status_code == 401
    assert (
        await (await _client(make_client, db, settings, users["owner"])).get(
            f"/api/v1/uploads/{uuid.uuid4()}/events"
        )
    ).status_code == 404


async def test_live_events_are_delivered_as_they_are_committed(
    db: AsyncSession,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    fake = FakeAnalyzer({"plan.docx": ScriptedVerdict("mismatch", "Looks wrong.", "test-plan")})
    upload, _, _ = await ingest(
        db,
        settings,
        taxonomy,
        project=project,
        uploader=owner,
        role="owner",
        files=[("srs.docx", SRS), ("plan.docx", PLAN)],
        specs=[UploadItemSpec(doc_type="srs"), UploadItemSpec(doc_type="srs", title="Plan")],
        analyzer=fake,
        run=False,
    )
    counter = CountingMaker(db_sessionmaker)
    stream = events.stream_upload_events(
        counter, upload.id, poll_interval=0.02, heartbeat_interval=60
    )
    assert await anext(stream) == "retry: 2000\n\n"
    collected: list[str] = []

    async def collect() -> None:
        async for frame in stream:
            collected.append(frame)
            assert counter.open == 0, "a session stayed open while a frame was yielded"

    collector = asyncio.create_task(collect())
    await asyncio.sleep(0.1)  # the stream is polling an upload with two ``uploaded`` items
    assert collected == [] and not collector.done()
    await run_upload(pipeline_context(settings, taxonomy, fake), upload.id)
    await asyncio.wait_for(collector, timeout=5)
    frames = _frames("".join(collected))
    statuses = [json.loads(f["data"])["status"] for f in frames if f.get("event") == "item.status"]
    assert sorted(statuses) == sorted(
        ["converting", "checking", "publishing", "published", "converting", "checking", "needs_confirmation"]
    )
    assert frames[-1]["event"] == "upload.settled"
    assert counter.max_open == 1 and counter.open == 0


async def test_heartbeat_while_idle_and_close_releases_sessions(
    db: AsyncSession,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    upload, items, _ = await ingest(
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
    items[0].status = "checking"  # stuck mid-flight: the stream must wait, not end
    await db.commit()
    counter = CountingMaker(db_sessionmaker)
    stream: AsyncIterator[str] = events.stream_upload_events(
        counter, upload.id, poll_interval=0.01, heartbeat_interval=0.03
    )
    assert await anext(stream) == "retry: 2000\n\n"
    assert await asyncio.wait_for(anext(stream), timeout=2) == events.HEARTBEAT
    assert await asyncio.wait_for(anext(stream), timeout=2) == events.HEARTBEAT
    assert counter.opened >= 2 and counter.open == 0  # one session per poll, none kept
    await stream.aclose()  # the client went away
    assert counter.open == 0
    item = await db.get_one(UploadItem, items[0].id)
    assert item.status == "checking"  # the stream only reads
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_upload_events.py -q`
Expected: FAIL with `AttributeError: module 'app.services.events' has no attribute 'parse_last_event_id'` and 404s.

- [ ] **Step 3: The stream**

Append to `backend/app/services/events.py` (add `import asyncio`, `import json`, `import time`, `from collections.abc import AsyncIterator, Mapping` — merge with the existing `Mapping` import — and `from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker`):

```python
RETRY_MS = 2000
HEARTBEAT = ": ping\n\n"
SETTLED_EVENT = "upload.settled"
POLL_INTERVAL = 0.5  # spec 17: SSE latency under 2 seconds
HEARTBEAT_INTERVAL = 15.0  # the Next.js rewrite proxy closes a response idle for 30 seconds
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def sse_frame(event_type: str, data: Mapping[str, Any], event_id: int | None = None) -> str:
    lines = [] if event_id is None else [f"id: {event_id}"]
    lines.append(f"event: {event_type}")
    lines.append("data: " + json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    return "\n".join(lines) + "\n\n"


def parse_last_event_id(value: str | None) -> int:
    """The browser's ``Last-Event-ID`` header; anything but a non-negative integer → 0."""
    if value is None or not value.strip().isdigit():
        return 0
    return int(value.strip())


async def stream_upload_events(
    maker: async_sessionmaker[AsyncSession],
    upload_id: uuid.UUID,
    *,
    last_event_id: int = 0,
    poll_interval: float = POLL_INTERVAL,
    heartbeat_interval: float = HEARTBEAT_INTERVAL,
) -> AsyncIterator[str]:
    """Replay the rows after ``last_event_id``, then poll for new ones until the upload is
    settled. Every poll opens and closes its own session, so no connection is held between
    polls or for the lifetime of the stream; a client disconnect cancels the generator at the
    next ``await`` and the ``async with`` closes whatever session is open.

    Settled is checked *before* the rows are read: everything committed before that check is
    visible to the read, so no row that made the upload settled is skipped. (A row committed
    between the two statements is sent; the next poll's settled check decides. The client
    refreshes the upload once on ``upload.settled`` and reopens the stream if anything is
    still active, which also covers identity ids that commit out of order.)"""
    cursor = last_event_id
    last_frame = time.monotonic()
    yield f"retry: {RETRY_MS}\n\n"
    while True:
        async with maker() as db:
            settled = await is_settled(db, upload_id)
            rows = await events_after(db, upload_id, cursor)
        for row in rows:
            cursor = row.id
            yield sse_frame(row.type, row.payload, row.id)
        if rows:
            last_frame = time.monotonic()
            if len(rows) == EVENT_PAGE:
                continue  # more to replay before deciding anything
        if settled:
            yield sse_frame(SETTLED_EVENT, {"upload_id": str(upload_id), "last_event_id": cursor})
            return
        if time.monotonic() - last_frame >= heartbeat_interval:
            yield HEARTBEAT
            last_frame = time.monotonic()
        await asyncio.sleep(poll_interval)
```

- [ ] **Step 4: The route**

In `backend/app/api/routes/uploads.py`: add `from fastapi.responses import JSONResponse, Response, StreamingResponse` (replacing the existing `JSONResponse, Response` import), `from fastapi import ... Header ...` (add `Header` to the existing `from fastapi import` list), `from app.db.session import get_sessionmaker`, and `from app.services import events as events_service`. Append directly after `get_upload`:

```python
@router.get(
    "/uploads/{upload_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-Sent Events: `item.status` frames, `: ping` comments, "
            "then `upload.settled`.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def upload_events(
    upload_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    await _upload_for(db, upload_id, user)
    # The dependency's session is closed only after the response finishes (FastAPI runs the
    # exit of yield dependencies after the stream ends); release it now so a listener never
    # pins a pooled connection. The generator opens its own short session per poll.
    await db.close()
    return StreamingResponse(
        events_service.stream_upload_events(
            get_sessionmaker(),
            upload_id,
            last_event_id=events_service.parse_last_event_id(last_event_id),
        ),
        media_type="text/event-stream",
        headers=events_service.SSE_HEADERS,
    )
```

- [ ] **Step 5: Run the tests, regenerate the OpenAPI document, run the checks**

Run: `uv run pytest tests/api/test_upload_events.py tests/api/test_uploads.py -q`
Expected: PASS. Then:

```bash
uv run python -m app.openapi_export ../frontend/openapi.json
uv run pytest -q && uv run ruff format . && uv run ruff check . && uv run mypy app
```

Expected: PASS (`test_committed_frontend_document_is_current` is green again after the export).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/events.py backend/app/api/routes/uploads.py backend/tests/api/test_upload_events.py frontend/openapi.json
git commit -m "feat(backend): Server-Sent Events for upload progress with Last-Event-ID replay"
```

### Task 4: Frontend foundation — dependencies, messages, Tabs, MarkdownView, upload helper, test doubles, responsive shell and dialog

**Files:**
- Modify: `frontend/package.json` (three dependencies), `frontend/pnpm-lock.yaml` (by `pnpm add`), `frontend/src/messages.ts`, `frontend/src/app/globals.css`, `frontend/src/lib/api/client.ts`, `frontend/src/components/ui/Dialog.tsx`, `frontend/src/components/shell/AppShell.tsx`, `frontend/src/components/shell/AppShell.test.tsx`
- Create: `frontend/src/components/ui/Tabs.tsx`, `frontend/src/components/ui/Tabs.test.tsx`, `frontend/src/components/ui/TypeOptions.tsx`, `frontend/src/components/ui/Markdown.tsx`, `frontend/src/components/ui/Markdown.test.tsx`, `frontend/src/components/ui/StatusBadge.tsx`, `frontend/src/lib/api/upload.ts`, `frontend/src/lib/api/upload.test.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/format.test.ts`, `frontend/src/lib/hooks/useDebouncedValue.ts`, `frontend/src/test/fake-xhr.ts`, `frontend/src/test/fake-event-source.ts`

**Interfaces:**
- Consumes: UI primitives and `cx` (Plan 3a), `useSession`, `roleLabel`, `mockFetch`, `withSession`.
- Produces: `m.nav.tasks`, new `m.common.*`, `m.uploads`, `m.tasks`, `m.documents`, `m.gaps` (every Plan 5 string); `Tabs({ label, items: TabItem[], value, onChange })` with `TabItem = { id: string; label: string; render: () => ReactNode }`; `MarkdownView({ markdown })`; `StatusBadge({ status })`; `TypeOptions({ taxonomy })` (one `<optgroup>` per folder, used inside a `<select>` by Tasks 5 and 7); `uploadMultipart<T>(path, form, onProgress?) -> Promise<UploadResponse<T>>` with `UploadResponse<T> = { ok: true; status; data: T } | { ok: false; status; error: unknown }`; `notifyUnauthorized()` exported from `client.ts`; `formatBytes(n)`, `formatDate(iso)`, `formatDateTime(iso)`; `useDebouncedValue(value, delayMs)`; test doubles `FakeXHR` (`FakeXHR.install()`, `FakeXHR.respondWith`, `FakeXHR.failWithNetworkError`, `FakeXHR.instances[i].{method,url,headers,body}`) and `FakeEventSource` (`FakeEventSource.install()`, `FakeEventSource.last`, `.open()`, `.emit(type, data, lastEventId)`, `.fail(readyState)`, `.closed`). `Dialog` is full-screen below `sm`; `AppShell` has a menu button (`aria-controls`, `aria-expanded`) below `md`; the `.markdown` CSS class.

- [ ] **Step 1: Dependencies**

Run from `frontend/`:

```bash
pnpm add react-markdown@10.1.0 remark-gfm@4.0.1 rehype-sanitize@6.0.0
```

Expected: `package.json` lists the three under `dependencies`; `pnpm-lock.yaml` updated. (`pnpm typecheck` still passes: nothing imports them yet.)

- [ ] **Step 2: Messages**

In `frontend/src/messages.ts`:

Add to `nav` (after `storage`): 

```ts
    tasks: "My tasks",
    openMenu: "Open menu",
    closeMenu: "Close menu",
```

Add to `common` (after `requestFailed`):

```ts
    download: "Download",
    edit: "Edit",
    remove: "Remove",
    refresh: "Refresh",
    back: "Back",
    all: "All",
```

Add to `projects` (after `notFound`): nothing — the tabs reuse `m.documents.title` and `m.gaps.title`.

Append these sections before the closing `} as const;`:

```ts
  uploads: {
    title: "Upload documents",
    intro:
      "Drop files here or choose them. For each file choose the document type, check the title and say whether it is a new document or a new version of an existing one.",
    dropHere: "Drop files here",
    chooseFiles: "Choose files",
    filesLabel: "Files",
    noFiles: "No files selected yet.",
    fileName: "File",
    size: "Size",
    titleField: "Title",
    docType: "Document type",
    chooseType: "Choose a type…",
    intent: "Intent",
    intentNew: "New document",
    intentVersion: "New version of an existing document",
    versionTarget: "Existing document",
    suggestionHint: (title: string, version: number) =>
      `Looks like a new version of "${title}" (currently v${version}).`,
    noSuggestions: "No similar document found; it will be created as a new document.",
    visibility: "Visibility",
    visibilityInternal: "Internal",
    visibilityShared: "Shared with customer",
    sharedForced: "Shared (documents uploaded by customer users are always shared)",
    applyToAll: "Apply to all files",
    applyTypeToAll: "Document type for all files",
    applyVisibilityToAll: "Visibility for all files",
    apply: "Apply",
    removeFile: (name: string) => `Remove ${name}`,
    submit: "Upload",
    uploading: (percent: number) => `Uploading… ${percent}%`,
    uploadProgress: "Upload progress",
    unsupportedType: (allowed: string) => `File type is not supported. Allowed: ${allowed}.`,
    tooLarge: (mb: number) => `File is larger than ${mb} MB.`,
    batchTooLarge: (mb: number) =>
      `The selected files exceed ${mb} MB in total. Remove some files or upload in several batches.`,
    zipNoVersion: "Zip archives are always uploaded as new documents.",
    typeRequired: "Choose a document type for every file.",
    nothingToUpload: "Nothing to upload: every file was refused.",
    consentRequired:
      "This project has not recorded the customer's LLM data-processing confirmation yet, so uploads are blocked.",
    consentLink: "Record it on the project's Overview tab",
    rejectedTitle: "Some files were not accepted",
    followProgress: "Follow progress",
    leaveWarning: "Files are still uploading.",
    progressTitle: "Upload progress",
    live: "Live",
    reconnecting: "Reconnecting…",
    polling: "Live updates are unavailable; refreshing every few seconds.",
    settled: "All files have been processed.",
    needsYou: "Waiting for your confirmation",
    goToTasks: "Confirm in My tasks",
    openDocument: "Open document",
    retryItem: "Retry",
    warnings: "Warnings",
    lowText: "Little extractable text (possibly scanned); the type check was skipped.",
    backToProject: "Back to project",
    notFound: "Upload not found.",
    connectionLabel: "Connection",
    status: {
      uploaded: "Queued",
      converting: "Converting",
      checking: "Checking type",
      needs_confirmation: "Needs confirmation",
      publishing: "Publishing",
      published: "Published",
      failed: "Failed",
    } as Record<string, string>,
    typeCheck: {
      match: "Type confirmed by the check",
      mismatch_kept: "Type kept after a mismatch",
      mismatch_changed: "Type changed after a mismatch",
      skipped: "Type check skipped",
    } as Record<string, string>,
  },
  tasks: {
    title: "My tasks",
    intro: "Documents you uploaded that are waiting for a decision from you.",
    empty: "Nothing is waiting for you.",
    review: "Review",
    confirmTitle: "Confirm the document type",
    selectedType: "You selected",
    verdict: "Type check",
    noVerdict:
      "The type check did not return a verdict. Confirm the type you selected or choose another one.",
    suggested: "Suggested type",
    useSuggested: "Use the suggested type",
    chooseType: "Document type to publish with",
    keep: "Keep selected type",
    change: "Change type",
    confirmed: "Type confirmed. The document is being published.",
    project: "Project",
    file: "File",
    waitingSince: "Waiting since",
  },
  documents: {
    title: "Documents",
    upload: "Upload documents",
    filterFolder: "Folder",
    filterType: "Document type",
    filterVisibility: "Visibility",
    search: "Search titles",
    allFolders: "All folders",
    allTypes: "All types",
    empty: "No documents match these filters.",
    stub: "Placeholder",
    stubHint: "No document of this type has been uploaded yet; this placeholder marks the gap.",
    version: (n: number) => `v${n}`,
    uploadedBy: "Uploaded by",
    date: "Date",
    internal: "Internal",
    shared: "Shared",
    tabMarkdown: "Markdown",
    tabVersions: "Versions",
    details: "Details",
    downloadOriginal: "Download original",
    downloadMarkdown: "Download Markdown",
    noOriginal: "Placeholders have no original file.",
    versionLabel: (n: number) => `Version ${n}`,
    current: "Current",
    viewVersion: (n: number) => `View version ${n}`,
    showing: (n: number) => `Showing version ${n}`,
    fmTitle: "Title",
    fmType: "Document type",
    fmVersion: "Version",
    fmUploadedBy: "Uploaded by",
    fmUploadedAt: "Uploaded at",
    fmTypeCheck: "Type check",
    fmLanguage: "Language",
    fmVisibility: "Visibility",
    fmSource: "Source file",
    fmKind: "Kind",
    editTitle: "Edit document",
    titleField: "Title",
    visibilityField: "Visibility",
    editorCannotHide: "Only a project owner can make a shared document internal.",
    saved: "Document saved.",
    notFound: "Document not found.",
    renderedNote: "Rendered from the converted Markdown; the original file is authoritative.",
  },
  gaps: {
    title: "Gap report",
    intro:
      "Required and optional document types per folder. Completeness counts the required types that have a real document.",
    completeness: (present: number, total: number, percent: number) =>
      `${present} of ${total} required types present (${percent}%)`,
    generated: (date: string) => `Generated ${date}`,
    folder: "Folder",
    type: "Document type",
    required: "Required",
    optional: "Optional",
    status: "Status",
    documents: "Documents",
    present: "Present",
    stub: "Placeholder",
    missing: "Missing",
  },
```

- [ ] **Step 3: Write the failing tests for Tabs, MarkdownView, the upload helper and the formatters**

`frontend/src/components/ui/Tabs.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it } from "vitest";
import { Tabs } from "./Tabs";

function Probe() {
  const [tab, setTab] = useState("one");
  return (
    <Tabs
      label="Demo"
      value={tab}
      onChange={setTab}
      items={[
        { id: "one", label: "One", render: () => <p>First panel</p> },
        { id: "two", label: "Two", render: () => <p>Second panel</p> },
        { id: "three", label: "Three", render: () => <p>Third panel</p> },
      ]}
    />
  );
}

it("renders tablist, tab and tabpanel with the ARIA wiring and switches on click", async () => {
  render(<Probe />);
  const list = screen.getByRole("tablist", { name: "Demo" });
  const one = screen.getByRole("tab", { name: "One" });
  const two = screen.getByRole("tab", { name: "Two" });
  expect(list).toContainElement(one);
  expect(one).toHaveAttribute("aria-selected", "true");
  expect(two).toHaveAttribute("aria-selected", "false");
  expect(two).toHaveAttribute("tabindex", "-1");
  const panel = screen.getByRole("tabpanel", { name: "One" });
  expect(panel).toHaveTextContent("First panel");
  expect(one).toHaveAttribute("aria-controls", panel.id);
  await userEvent.click(two);
  expect(screen.getByRole("tabpanel", { name: "Two" })).toHaveTextContent("Second panel");
  expect(screen.queryByText("First panel")).not.toBeInTheDocument();
});

it("moves with arrow keys, Home and End and wraps around", async () => {
  render(<Probe />);
  const one = screen.getByRole("tab", { name: "One" });
  one.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Two" })).toHaveFocus();
  expect(screen.getByRole("tabpanel", { name: "Two" })).toBeInTheDocument();
  await userEvent.keyboard("{End}");
  expect(screen.getByRole("tab", { name: "Three" })).toHaveFocus();
  await userEvent.keyboard("{ArrowRight}");
  expect(one).toHaveFocus(); // wraps
  await userEvent.keyboard("{ArrowLeft}");
  expect(screen.getByRole("tab", { name: "Three" })).toHaveFocus();
  await userEvent.keyboard("{Home}");
  expect(one).toHaveFocus();
});
```

`frontend/src/components/ui/Markdown.test.tsx` (the hostile fixtures are the security test for spec 12 v2.2; keep them when the component changes):

```tsx
import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { MarkdownView } from "./Markdown";

const HOSTILE = `# Title <script>alert(1)</script>

Para with <img src=x onerror="alert(1)"> and <a href="javascript:alert(1)">x</a>.

[js](javascript:alert(1)) [JS](JaVaScRiPt:alert(1)) [tab](java\tscript:alert(1)) [data](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==) [vbs](vbscript:msgbox) [ok](https://example.com "t") [rel](../other.md) [mail](mailto:a@example.com) [frag](#section)

![img](javascript:alert(1)) ![ok img](https://example.com/a.png)

<iframe src="https://evil.example"></iframe>
<object data="x"></object><embed src="x">
<svg onload="alert(1)"><circle r=1></svg>
<style>body{display:none}</style>
<div style="position:fixed;top:0" onclick="alert(1)">styled</div>
<form action="https://evil.example"><input name=q></form>
<a href="https://example.com" target="_blank">target</a>

| a | b |
|---|---|
| 1 | <b onmouseover=alert(1)>2</b> |

- [ ] task
- [x] done

~~strike~~ https://autolink.example.com

\`\`\`html
<script>in code block</script>
\`\`\`
`;

it("neutralises scripts, event handlers, dangerous URLs and embedded documents", () => {
  const { container } = render(<MarkdownView markdown={HOSTILE} />);
  const html = container.innerHTML;
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("iframe, object, embed, svg, style, form, input[name]")).toBeNull();
  expect(html).not.toMatch(/on(error|load|click|mouseover)=/i);
  expect(html).not.toMatch(/javascript:/i);
  expect(html).not.toMatch(/vbscript:/i);
  expect(html).not.toMatch(/href="data:/i);
  expect(html).not.toMatch(/ style="/i);
  expect(html).not.toMatch(/target="_blank"/);
  expect(container.querySelector("h1")?.textContent).toBe("Title alert(1)");
  // the hostile image lost its src entirely; the https one is kept
  const images = Array.from(container.querySelectorAll("img"));
  expect(images.map((img) => img.getAttribute("src"))).toEqual([null, "https://example.com/a.png"]);
});

it("keeps safe links, images and GitHub-flavoured Markdown", () => {
  const { container } = render(<MarkdownView markdown={HOSTILE} />);
  const hrefs = Array.from(container.querySelectorAll("a[href]")).map((a) => a.getAttribute("href"));
  expect(hrefs).toEqual([
    "https://example.com",
    "../other.md",
    "mailto:a@example.com",
    "#section",
    "https://autolink.example.com",
  ]); // the raw <a target="_blank"> block is removed entirely, not just its target attribute
  expect(container.querySelector("table thead th")?.textContent).toBe("a");
  expect(container.querySelectorAll("input[type=checkbox]")).toHaveLength(2);
  expect(container.querySelector("del")?.textContent).toBe("strike");
  expect(container.querySelector("pre code")?.textContent).toContain("<script>in code block</script>");
  expect(container.querySelector(".markdown")).not.toBeNull();
});

it("renders plain prose and headings from a converted document", () => {
  const { container } = render(
    <MarkdownView markdown={"## Scope\n\nThe system shall allow users to log in.\n\n- MFA\n- Recovery codes"} />,
  );
  expect(container.querySelector("h2")?.textContent).toBe("Scope");
  expect(container.querySelectorAll("li")).toHaveLength(2);
});
```

`frontend/src/lib/api/upload.test.ts`:

```ts
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setUnauthorizedHandler } from "@/lib/api/client";
import { FakeXHR } from "@/test/fake-xhr";
import { uploadMultipart } from "./upload";

beforeEach(() => FakeXHR.install());
afterEach(() => setUnauthorizedHandler(null));

function form() {
  const fd = new FormData();
  fd.append("files", new File(["abc"], "a.md", { type: "text/markdown" }), "a.md");
  fd.append("items", JSON.stringify([{ doc_type: "srs" }]));
  return fd;
}

it("posts the form with the CSRF header, reports progress and returns the parsed body", async () => {
  FakeXHR.respondWith = { status: 201, body: { id: "u1", items: [] } };
  const progress: number[] = [];
  const result = await uploadMultipart<{ id: string }>("/api/v1/projects/p1/uploads", form(), (f) =>
    progress.push(f),
  );
  expect(result).toEqual({ ok: true, status: 201, data: { id: "u1", items: [] } });
  const sent = FakeXHR.instances[0];
  expect(sent.method).toBe("POST");
  expect(sent.url).toBe("/api/v1/projects/p1/uploads");
  expect(sent.headers["X-QC-Agent"]).toBe("1");
  expect(sent.headers["Accept"]).toBe("application/json");
  expect((sent.body as FormData).getAll("files").map((f) => (f as File).name)).toEqual(["a.md"]);
  expect(progress).toEqual([0.5]);
});

it("returns the error body for non-2xx responses and notifies on 401", async () => {
  FakeXHR.respondWith = { status: 409, body: { detail: "Consent required." } };
  const conflict = await uploadMultipart("/api/v1/projects/p1/uploads", form());
  expect(conflict).toEqual({ ok: false, status: 409, error: { detail: "Consent required." } });
  const handler = vi.fn();
  setUnauthorizedHandler(handler);
  FakeXHR.respondWith = { status: 401, body: { detail: "Not authenticated." } };
  const unauthorized = await uploadMultipart("/api/v1/projects/p1/uploads", form());
  expect(unauthorized.ok).toBe(false);
  expect(handler).toHaveBeenCalledTimes(1);
});

it("rejects with the generic request error on a network failure", async () => {
  FakeXHR.failWithNetworkError = true;
  await expect(uploadMultipart("/api/v1/projects/p1/uploads", form())).rejects.toThrow(
    "The request failed. Try again.",
  );
});
```

`frontend/src/lib/format.test.ts`:

```ts
import { expect, it } from "vitest";
import { formatBytes, formatDate } from "./format";

it("formats byte counts for people", () => {
  expect(formatBytes(0)).toBe("0 B");
  expect(formatBytes(999)).toBe("999 B");
  expect(formatBytes(1024)).toBe("1.0 KB");
  expect(formatBytes(1536)).toBe("1.5 KB");
  expect(formatBytes(52_428_800)).toBe("50.0 MB");
  expect(formatBytes(1_073_741_824)).toBe("1.0 GB");
});

it("formats dates in the en-GB style the rest of the UI uses", () => {
  expect(formatDate("2026-10-01T10:00:00+00:00")).toBe("01/10/2026");
});
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run (from `frontend/`): `pnpm test -- src/components/ui/Tabs.test.tsx src/components/ui/Markdown.test.tsx src/lib/api/upload.test.ts src/lib/format.test.ts`
Expected: FAIL — modules `./Tabs`, `./Markdown`, `./upload`, `./format`, `@/test/fake-xhr` not found.

- [ ] **Step 5: Test doubles**

`frontend/src/test/fake-xhr.ts`:

```ts
import { vi } from "vitest";

type ProgressListener = (event: ProgressEvent) => void;

/** Stand-in for XMLHttpRequest: records open/headers/body, fires one 50% progress event and
 * resolves with `respondWith` (or a network error). jsdom's FormData reaches the test intact,
 * which `fetch`/`Request` cannot offer under jsdom 30 (see the plan's verified behaviour). */
export class FakeXHR {
  static instances: FakeXHR[] = [];
  static respondWith: { status: number; body?: unknown } = { status: 200, body: {} };
  static failWithNetworkError = false;

  static install(): void {
    FakeXHR.instances = [];
    FakeXHR.respondWith = { status: 200, body: {} };
    FakeXHR.failWithNetworkError = false;
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
  }

  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  responseText = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private progressListeners: ProgressListener[] = [];
  readonly upload = {
    addEventListener: (type: string, listener: ProgressListener) => {
      if (type === "progress") this.progressListeners.push(listener);
    },
  };

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value;
  }

  send(body: unknown): void {
    this.body = body;
    FakeXHR.instances.push(this);
    if (FakeXHR.failWithNetworkError) {
      queueMicrotask(() => this.onerror?.());
      return;
    }
    for (const listener of this.progressListeners) {
      listener({ lengthComputable: true, loaded: 50, total: 100 } as ProgressEvent);
    }
    this.status = FakeXHR.respondWith.status;
    this.responseText =
      FakeXHR.respondWith.body === undefined ? "" : JSON.stringify(FakeXHR.respondWith.body);
    queueMicrotask(() => this.onload?.());
  }
}
```

`frontend/src/test/fake-event-source.ts`:

```ts
import { vi } from "vitest";

type Listener = (event: Event) => void;

/** Stand-in for the browser's EventSource (absent from jsdom): tests open it, emit named
 * events with ids and simulate failures. */
export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  static install(): void {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  }

  static get last(): FakeEventSource {
    const last = FakeEventSource.instances.at(-1);
    if (!last) throw new Error("no EventSource was opened");
    return last;
  }

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  closed = false;
  private listeners = new Map<string, Set<Listener>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.dispatch("open", new Event("open"));
  }

  emit(type: string, data: unknown, lastEventId = ""): void {
    this.dispatch(type, new MessageEvent(type, { data: JSON.stringify(data), lastEventId }));
  }

  /** The browser fires `error` with readyState CONNECTING while it retries, CLOSED when it gave up. */
  fail(readyState: number = FakeEventSource.CONNECTING): void {
    this.readyState = readyState;
    this.dispatch("error", new Event("error"));
  }

  private dispatch(type: string, event: Event): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}
```

- [ ] **Step 6: Formatters, debounce, upload helper, client export**

`frontend/src/lib/format.ts`:

```ts
const UNITS = ["B", "KB", "MB", "GB"];

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${Math.round(value)} ${UNITS[unit]}` : `${value.toFixed(1)} ${UNITS[unit]}`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB");
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}
```

`frontend/src/lib/hooks/useDebouncedValue.ts`:

```ts
"use client";

import { useEffect, useState } from "react";

/** The value once it has stayed unchanged for `delayMs` (for search boxes and suggestions). */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
```

In `frontend/src/lib/api/client.ts`, after `setUnauthorizedHandler` add:

```ts
/** For request paths that bypass openapi-fetch (the multipart upload). */
export function notifyUnauthorized(): void {
  unauthorizedHandler?.();
}
```

`frontend/src/lib/api/upload.ts`:

```ts
import { m } from "@/messages";
import { CSRF_HEADER, notifyUnauthorized } from "./client";
import type { components } from "./schema";

export type UploadOut = components["schemas"]["UploadOut"];
export type UploadResponse<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: unknown };

function parse(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

/** Multipart POST over XMLHttpRequest: same-origin (the session cookie travels), CSRF header,
 * upload progress as a fraction, JSON body parsed. Used only for `POST /projects/{id}/uploads`;
 * every other call goes through the typed client. */
export function uploadMultipart<T = UploadOut>(
  path: string,
  form: FormData,
  onProgress?: (fraction: number) => void,
): Promise<UploadResponse<T>> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader(CSRF_HEADER, "1");
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
    });
    xhr.onload = () => {
      const body = parse(xhr.responseText);
      if (xhr.status === 401) notifyUnauthorized();
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve({ ok: true, status: xhr.status, data: body as T });
      } else {
        resolve({ ok: false, status: xhr.status, error: body });
      }
    };
    xhr.onerror = () => reject(new Error(m.common.requestFailed));
    xhr.send(form);
  });
}
```

- [ ] **Step 7: Tabs, MarkdownView, StatusBadge**

`frontend/src/components/ui/Tabs.tsx`:

```tsx
"use client";

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "@/lib/cx";

export type TabItem = { id: string; label: string; render: () => ReactNode };

type Props = { label: string; items: TabItem[]; value: string; onChange: (id: string) => void };

/** WAI-ARIA tabs: one tabstop (roving tabIndex), arrow keys / Home / End move and select,
 * the active panel is labelled by its tab. Only the active panel is rendered. */
export function Tabs({ label, items, value, onChange }: Props) {
  const prefix = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const active = items.find((item) => item.id === value) ?? items[0];
  if (!active) return null;

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const targets: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowLeft: index - 1,
      Home: 0,
      End: items.length - 1,
    };
    const target = targets[event.key];
    if (target === undefined) return;
    event.preventDefault();
    const next = items[(target + items.length) % items.length];
    onChange(next.id);
    refs.current[next.id]?.focus();
  }

  return (
    <>
      <div
        role="tablist"
        aria-label={label}
        className="mb-6 flex gap-4 overflow-x-auto border-b border-border"
      >
        {items.map((item, index) => {
          const selected = item.id === active.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`${prefix}-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`${prefix}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              ref={(element) => {
                refs.current[item.id] = element;
              }}
              onClick={() => onChange(item.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={cx(
                "-mb-px min-h-10 shrink-0 border-b-2 px-1 pb-2 text-sm",
                selected
                  ? "border-brand font-semibold text-brand"
                  : "border-transparent text-muted hover:text-fg",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${prefix}-panel-${active.id}`}
        aria-labelledby={`${prefix}-tab-${active.id}`}
      >
        {active.render()}
      </div>
    </>
  );
}
```

`frontend/src/components/ui/Markdown.tsx`:

```tsx
"use client";

import Markdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

/** The only place document Markdown is rendered (spec 12, v2.2). Customer uploads are
 * untrusted: react-markdown never emits raw HTML (no rehype-raw), its default urlTransform
 * drops javascript:/data:/vbscript: URLs, and rehype-sanitize's GitHub schema removes every
 * element and attribute outside the allow-list (event handlers, style, iframe, svg, form…).
 * Do not add rehype-raw, a custom schema or dangerouslySetInnerHTML here. */
export function MarkdownView({ markdown }: { markdown: string }) {
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSanitize, defaultSchema]]}>
        {markdown}
      </Markdown>
    </div>
  );
}
```

`frontend/src/components/ui/TypeOptions.tsx`:

```tsx
import type { components } from "@/lib/api/schema";

type Taxonomy = components["schemas"]["TaxonomyOut"];

/** Document-type choices grouped by folder (spec 6.1: "dropdown grouped by the six folders");
 * the browser's type-ahead on a native <select> is the search. Render inside a <select>. */
export function TypeOptions({ taxonomy }: { taxonomy: Taxonomy }) {
  return (
    <>
      {taxonomy.folders.map((folder) => (
        <optgroup key={folder.id} label={`${folder.dir} (${folder.stage})`}>
          {folder.doc_types.map((type) => (
            <option key={type.key} value={type.key}>
              {type.title}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}
```

`frontend/src/components/ui/StatusBadge.tsx`:

```tsx
import { Badge } from "@/components/ui/Badge";
import { m } from "@/messages";

const TONES: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  published: "success",
  failed: "danger",
  needs_confirmation: "warning",
};

/** Upload-item status as a labelled badge (text, never colour alone). */
export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={TONES[status] ?? "neutral"}>{m.uploads.status[status] ?? status}</Badge>;
}
```

Append to `frontend/src/app/globals.css`:

```css
/* Rendered document Markdown (components/ui/Markdown.tsx). Long tokens must wrap on phones. */
.markdown {
  overflow-wrap: anywhere;
  line-height: 1.6;
}
.markdown h1,
.markdown h2,
.markdown h3,
.markdown h4 {
  margin: 1.25em 0 0.5em;
  font-weight: 600;
  line-height: 1.25;
}
.markdown h1 {
  font-size: 1.5rem;
}
.markdown h2 {
  font-size: 1.25rem;
}
.markdown h3 {
  font-size: 1.1rem;
}
.markdown p,
.markdown ul,
.markdown ol,
.markdown blockquote,
.markdown pre,
.markdown table {
  margin: 0 0 0.9em;
}
.markdown ul {
  list-style: disc;
  padding-left: 1.5em;
}
.markdown ol {
  list-style: decimal;
  padding-left: 1.5em;
}
.markdown a {
  color: var(--brand);
  text-decoration: underline;
}
.markdown blockquote {
  border-left: 3px solid var(--border);
  color: var(--muted);
  padding-left: 0.75em;
}
.markdown code {
  background: var(--bg);
  border-radius: 0.25rem;
  font-size: 0.9em;
  padding: 0.1em 0.3em;
}
.markdown pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  overflow-x: auto;
  padding: 0.75em;
}
.markdown pre code {
  background: none;
  padding: 0;
}
.markdown table {
  border-collapse: collapse;
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
.markdown th,
.markdown td {
  border: 1px solid var(--border);
  padding: 0.35em 0.6em;
  text-align: left;
}
.markdown img {
  max-width: 100%;
}
.markdown hr {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 1.5em 0;
}
```

- [ ] **Step 8: Run the new tests**

Run: `pnpm test -- src/components/ui/Tabs.test.tsx src/components/ui/Markdown.test.tsx src/lib/api/upload.test.ts src/lib/format.test.ts`
Expected: PASS.

- [ ] **Step 9: Responsive dialog and shell — write the failing shell test**

Append to `frontend/src/components/shell/AppShell.test.tsx`:

```tsx
it("collapses the navigation behind a menu button on small screens", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: memberMe }]);
  renderShell();
  await screen.findByText("Page content");
  const button = screen.getByRole("button", { name: "Open menu" });
  const menu = document.getElementById(button.getAttribute("aria-controls") ?? "");
  expect(menu).not.toBeNull();
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(menu).toHaveClass("hidden"); // Tailwind hides it below md; md:flex shows it again
  await userEvent.click(button);
  expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
  expect(menu).not.toHaveClass("hidden");
  await userEvent.click(screen.getByRole("link", { name: "Projects" }));
  expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute("aria-expanded", "false");
});
```

Run: `pnpm test -- src/components/shell/AppShell.test.tsx`
Expected: FAIL with `Unable to find an accessible element with the role "button" and name "Open menu"`.

- [ ] **Step 10: Responsive dialog and shell — implementation**

In `frontend/src/components/ui/Dialog.tsx`, replace the `<dialog ... className=...>` element's class string with:

```tsx
      className={cx(
        "m-auto w-full max-w-lg rounded-lg border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/40",
        "max-sm:m-0 max-sm:h-dvh max-sm:max-h-none max-sm:w-screen max-sm:max-w-none max-sm:rounded-none max-sm:border-0",
      )}
```

(add `import { cx } from "@/lib/cx";`), and give the content wrapper a scroll region: replace `<div className="px-5 py-4">{children}</div>` with `<div className="max-h-[70dvh] overflow-y-auto px-5 py-4 max-sm:max-h-none">{children}</div>`.

Replace `frontend/src/components/shell/AppShell.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cx } from "@/lib/cx";
import { roleLabel } from "@/lib/session/next-route";
import { useSession } from "@/lib/session/SessionProvider";
import { m } from "@/messages";

type NavLink = { href: string; label: string; match: string };

/** Application frame. Below `md` the links and the user row live in a menu toggled by a
 * button (aria-expanded / aria-controls); from `md` up they are always visible. */
export function AppShell({ children }: { children: ReactNode }) {
  const { me, logout } = useSession();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const links: NavLink[] = [{ href: "/projects", label: m.nav.projects, match: "/projects" }];
  if (me.is_admin) links.push({ href: "/admin/users", label: m.nav.admin, match: "/admin" });
  return (
    <div className="min-h-full">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
          <Link href="/projects" className="min-h-10 py-2 font-semibold">
            {m.app.name}
          </Link>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={menuId}
            aria-label={open ? m.nav.closeMenu : m.nav.openMenu}
            onClick={() => setOpen((o) => !o)}
            className="min-h-10 rounded-md border border-border px-3 text-sm md:hidden"
          >
            {open ? "×" : "☰"}
          </button>
          <div
            id={menuId}
            className={cx(
              "w-full flex-col gap-3 md:flex md:w-auto md:flex-1 md:flex-row md:items-center md:justify-between",
              open ? "flex" : "hidden",
            )}
          >
            <nav aria-label={m.nav.main} className="flex flex-col gap-1 md:flex-row md:gap-5">
              {links.map((link) => {
                const current = pathname.startsWith(link.match);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    aria-current={current ? "page" : undefined}
                    onClick={() => setOpen(false)}
                    className={cx(
                      "min-h-10 py-2 text-sm",
                      current ? "font-semibold text-brand" : "text-muted hover:text-fg",
                    )}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span>{me.display_name}</span>
              <Badge>{roleLabel(me)}</Badge>
              <Link href="/change-password" className="text-muted hover:text-fg" onClick={() => setOpen(false)}>
                {m.nav.changePassword}
              </Link>
              <Button variant="secondary" onClick={() => void logout()}>
                {m.nav.logout}
              </Button>
            </div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
```

- [ ] **Step 11: Run every frontend check**

Run: `pnpm format:write && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build`
Expected: all PASS (the existing shell, dialog and feature tests are unchanged; `pnpm build` proves the ESM Markdown stack bundles in a client component).

- [ ] **Step 12: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/messages.ts frontend/src/app/globals.css frontend/src/lib/api/client.ts frontend/src/lib/api/upload.ts frontend/src/lib/api/upload.test.ts frontend/src/lib/format.ts frontend/src/lib/format.test.ts frontend/src/lib/hooks/useDebouncedValue.ts frontend/src/test/fake-xhr.ts frontend/src/test/fake-event-source.ts frontend/src/components/ui/Tabs.tsx frontend/src/components/ui/Tabs.test.tsx frontend/src/components/ui/TypeOptions.tsx frontend/src/components/ui/Markdown.tsx frontend/src/components/ui/Markdown.test.tsx frontend/src/components/ui/StatusBadge.tsx frontend/src/components/ui/Dialog.tsx frontend/src/components/shell/AppShell.tsx frontend/src/components/shell/AppShell.test.tsx
git commit -m "feat(frontend): Plan 5 foundation — messages, accessible tabs, sanitised Markdown view, upload helper, responsive shell"
```

### Task 5: Upload wizard and live progress

**Files:**
- Create: `frontend/src/features/uploads/types.ts`, `frontend/src/features/uploads/limits.ts`, `frontend/src/features/uploads/limits.test.ts`, `frontend/src/features/uploads/events.ts`, `frontend/src/features/uploads/events.test.ts`, `frontend/src/features/uploads/useUploadProgress.ts`, `frontend/src/features/uploads/useUploadProgress.test.tsx`, `frontend/src/features/uploads/FileRow.tsx`, `frontend/src/features/uploads/UploadWizard.tsx`, `frontend/src/features/uploads/UploadWizard.test.tsx`, `frontend/src/features/uploads/UploadProgress.tsx`, `frontend/src/features/uploads/UploadProgress.test.tsx`, `frontend/src/app/(app)/projects/[projectId]/upload/page.tsx`, `frontend/src/app/(app)/uploads/[uploadId]/page.tsx`

**Interfaces:**
- Consumes: `api`, `unwrap`, `apiErrorMessage`, `useLoad`, `useSession`, `uploadMultipart`, `FakeXHR`, `FakeEventSource`, `useDebouncedValue`, `formatBytes`, `StatusBadge`, `TypeOptions`, `Field`, `Select`, `Button`, `Alert`, `Badge`, `m` (Task 4); backend `GET /taxonomy`, `GET /upload-limits`, `GET /projects/{id}`, `GET /projects/{id}/version-suggestions`, `POST /projects/{id}/uploads`, `GET /uploads/{id}`, `POST /upload-items/{id}/retry` (Plan 2, Task 2); the SSE frame contract (Task 3).
- Produces: routes `/projects/[projectId]/upload` and `/uploads/[uploadId]`; `UploadWizard({ projectId })`, `UploadProgress({ uploadId })`, `useUploadProgress(uploadId, options?)`, `applyItemEvent(upload, event)`, `ItemStatusEvent`, `guardFile(file, limits) -> string | null`, `batchGuard(files, limits) -> string | null`. Labels Task 8 relies on: "Choose files", "Document type", "Title", "Upload", "Upload progress", status badges "Published"/"Failed", "Open document".

- [ ] **Step 1: Types and guards — failing tests**

`frontend/src/features/uploads/types.ts`:

```ts
import type { components } from "@/lib/api/schema";

export type Upload = components["schemas"]["UploadOut"];
export type UploadItem = components["schemas"]["UploadItemOut"];
export type UploadLimits = components["schemas"]["UploadLimitsOut"];
export type Taxonomy = components["schemas"]["TaxonomyOut"];
export type VersionSuggestion = components["schemas"]["VersionSuggestionOut"];
export type Visibility = "internal" | "shared";
export type Intent = "new" | "version";

export const ACTIVE_STATUSES = ["uploaded", "converting", "checking", "publishing"] as const;

export function isActive(status: string): boolean {
  return (ACTIVE_STATUSES as readonly string[]).includes(status);
}

export function hasActiveItems(upload: Upload): boolean {
  return upload.items.some((item) => isActive(item.status));
}
```

`frontend/src/features/uploads/limits.test.ts`:

```ts
import { expect, it } from "vitest";
import { batchGuard, extensionOf, guardFile } from "./limits";

const limits = {
  max_file_mb: 50,
  max_batch_mb: 500,
  allowed_extensions: ["csv", "docx", "html", "md", "pdf", "pptx", "txt", "xlsx", "zip"],
  zip_max_entries: 200,
};

function file(name: string, bytes: number): File {
  return new File([new Uint8Array(bytes)], name);
}

it("normalises extensions (case, htm alias, no extension)", () => {
  expect(extensionOf("Report.DOCX")).toBe("docx");
  expect(extensionOf("page.htm")).toBe("html");
  expect(extensionOf("archive.tar.gz")).toBe("gz");
  expect(extensionOf("README")).toBeNull();
});

it("refuses unsupported extensions and oversized files before upload", () => {
  expect(guardFile(file("virus.exe", 10), limits)).toBe(
    "File type is not supported. Allowed: csv, docx, html, md, pdf, pptx, txt, xlsx, zip.",
  );
  expect(guardFile(file("README", 10), limits)).toMatch(/not supported/);
  expect(guardFile(file("big.pdf", 50 * 1024 * 1024 + 1), limits)).toBe("File is larger than 50 MB.");
  expect(guardFile(file("ok.pdf", 50 * 1024 * 1024), limits)).toBeNull();
  expect(guardFile(file("page.HTM", 10), limits)).toBeNull();
});

it("refuses a batch over the total limit", () => {
  const half = 250 * 1024 * 1024;
  expect(batchGuard([file("a.pdf", half), file("b.pdf", half)], limits)).toBeNull();
  expect(batchGuard([file("a.pdf", half), file("b.pdf", half + 1)], limits)).toBe(
    "The selected files exceed 500 MB in total. Remove some files or upload in several batches.",
  );
});
```

Run: `pnpm test -- src/features/uploads/limits.test.ts` → FAIL (`./limits` not found).

- [ ] **Step 2: Guards**

`frontend/src/features/uploads/limits.ts`:

```ts
import { m } from "@/messages";
import type { UploadLimits } from "./types";

const ALIASES: Record<string, string> = { htm: "html" };
const MB = 1024 * 1024;

export function extensionOf(name: string): string | null {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return null;
  const ext = name.slice(dot + 1).toLowerCase();
  return ALIASES[ext] ?? ext;
}

/** The reason a file must not be sent, or null. Mirrors the backend's intake rules so an
 * obvious mistake fails in the row instead of after a 50 MB upload. */
export function guardFile(file: File, limits: UploadLimits): string | null {
  const ext = extensionOf(file.name);
  if (ext === null || !limits.allowed_extensions.includes(ext)) {
    return m.uploads.unsupportedType(limits.allowed_extensions.join(", "));
  }
  if (file.size > limits.max_file_mb * MB) return m.uploads.tooLarge(limits.max_file_mb);
  return null;
}

export function batchGuard(files: File[], limits: UploadLimits): string | null {
  const total = files.reduce((sum, file) => sum + file.size, 0);
  return total > limits.max_batch_mb * MB ? m.uploads.batchTooLarge(limits.max_batch_mb) : null;
}
```

Run: `pnpm test -- src/features/uploads/limits.test.ts` → PASS.

- [ ] **Step 3: Event application — failing test**

`frontend/src/features/uploads/events.test.ts`:

```ts
import { expect, it } from "vitest";
import { applyItemEvent, parseItemEvent } from "./events";
import type { Upload } from "./types";

const upload: Upload = {
  id: "u1",
  project_id: "p1",
  uploaded_by: "me",
  created_at: "2026-10-02T09:00:00+00:00",
  rejected: [],
  items: [
    {
      id: "i1",
      upload_id: "u1",
      original_name: "srs.docx",
      ext: "docx",
      size: 10,
      sha256: "x",
      selected_doc_type: "srs",
      final_doc_type: null,
      title: "SRS",
      intent: "new",
      target_document_id: null,
      visibility: "internal",
      status: "uploaded",
      type_check: null,
      check_explanation: null,
      suggested_doc_type: null,
      version_hint_document_id: null,
      warnings: [],
      conversion_meta: {},
      error: null,
      document_id: null,
      created_at: "2026-10-02T09:00:00+00:00",
      updated_at: "2026-10-02T09:00:00+00:00",
    },
  ],
};

it("parses a frame's JSON and ignores garbage", () => {
  expect(parseItemEvent('{"item_id":"i1","status":"converting"}')).toEqual({
    item_id: "i1",
    status: "converting",
  });
  expect(parseItemEvent("not json")).toBeNull();
  expect(parseItemEvent('{"status":"converting"}')).toBeNull(); // no item id
});

it("applies status and changed fields to the matching item only", () => {
  const next = applyItemEvent(upload, {
    item_id: "i1",
    status: "published",
    type_check: "skipped",
    check_explanation: "Type check is not available yet; the selected type was kept.",
    document_id: "d1",
    version: 1,
  });
  expect(next.items[0].status).toBe("published");
  expect(next.items[0].document_id).toBe("d1");
  expect(next.items[0].type_check).toBe("skipped");
  expect(next.items[0].title).toBe("SRS"); // untouched
  expect(upload.items[0].status).toBe("uploaded"); // immutable input
  expect(applyItemEvent(upload, { item_id: "other", status: "failed" })).toBe(upload);
});

it("clears the error when an item is retried", () => {
  const failed = applyItemEvent(upload, { item_id: "i1", status: "failed", error: "Broken." });
  expect(failed.items[0].error).toBe("Broken.");
  const retried = applyItemEvent(failed, { item_id: "i1", status: "uploaded", error: null });
  expect(retried.items[0].error).toBeNull();
});
```

Run: `pnpm test -- src/features/uploads/events.test.ts` → FAIL (`./events` not found).

- [ ] **Step 4: Event application**

`frontend/src/features/uploads/events.ts`:

```ts
import type { Upload } from "./types";

/** Payload of an `item.status` Server-Sent Event (backend `app/services/events.py`). */
export type ItemStatusEvent = {
  item_id: string;
  status: string;
  type_check?: string | null;
  check_explanation?: string | null;
  suggested_doc_type?: string | null;
  final_doc_type?: string | null;
  error?: string | null;
  document_id?: string | null;
  version?: number | null;
};

export function parseItemEvent(data: string): ItemStatusEvent | null {
  try {
    const parsed = JSON.parse(data) as Partial<ItemStatusEvent>;
    if (typeof parsed.item_id !== "string" || typeof parsed.status !== "string") return null;
    return parsed as ItemStatusEvent;
  } catch {
    return null;
  }
}

/** New upload state with the event applied to its item; the same object when no item matches. */
export function applyItemEvent(upload: Upload, event: ItemStatusEvent): Upload {
  const index = upload.items.findIndex((item) => item.id === event.item_id);
  if (index === -1) return upload;
  const item = upload.items[index];
  const next = {
    ...item,
    status: event.status,
    type_check: event.type_check === undefined ? item.type_check : event.type_check,
    check_explanation:
      event.check_explanation === undefined ? item.check_explanation : event.check_explanation,
    suggested_doc_type:
      event.suggested_doc_type === undefined ? item.suggested_doc_type : event.suggested_doc_type,
    final_doc_type: event.final_doc_type === undefined ? item.final_doc_type : event.final_doc_type,
    error: event.error === undefined ? item.error : event.error,
    document_id: event.document_id === undefined ? item.document_id : event.document_id,
  };
  const items = upload.items.slice();
  items[index] = next;
  return { ...upload, items };
}
```

Run: `pnpm test -- src/features/uploads/events.test.ts` → PASS.

- [ ] **Step 5: The progress hook — failing tests**

`frontend/src/features/uploads/useUploadProgress.test.tsx`:

```tsx
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { FakeEventSource } from "@/test/fake-event-source";
import { useUploadProgress } from "./useUploadProgress";

const UID = "22222222-2222-2222-2222-222222222222";
const item = (status: string, overrides: Record<string, unknown> = {}) => ({
  id: "i1",
  upload_id: UID,
  original_name: "srs.docx",
  ext: "docx",
  size: 10,
  sha256: "x",
  selected_doc_type: "srs",
  final_doc_type: null,
  title: "SRS",
  intent: "new",
  target_document_id: null,
  visibility: "internal",
  status,
  type_check: null,
  check_explanation: null,
  suggested_doc_type: null,
  version_hint_document_id: null,
  warnings: [],
  conversion_meta: {},
  error: null,
  document_id: null,
  created_at: "2026-10-02T09:00:00+00:00",
  updated_at: "2026-10-02T09:00:00+00:00",
  ...overrides,
});
const uploadWith = (status: string, overrides: Record<string, unknown> = {}) => ({
  id: UID,
  project_id: "p1",
  uploaded_by: "me",
  created_at: "2026-10-02T09:00:00+00:00",
  rejected: [],
  items: [item(status, overrides)],
});

function Probe({ pollIntervalMs }: { pollIntervalMs?: number }) {
  const progress = useUploadProgress(UID, { pollIntervalMs });
  if (progress.error) return <p role="alert">{progress.error}</p>;
  if (!progress.upload) return <p role="status">loading</p>;
  return (
    <div>
      <p data-testid="status">{progress.upload.items[0].status}</p>
      <p data-testid="connection">{progress.connection}</p>
      <p data-testid="doc">{progress.upload.items[0].document_id ?? "-"}</p>
    </div>
  );
}

beforeEach(() => FakeEventSource.install());

/** The EventSource is created in an effect after the upload loads; wait for it. */
async function lastSource(): Promise<FakeEventSource> {
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
  return FakeEventSource.last;
}

it("loads the upload, subscribes while items are active, applies events and refreshes on settled", async () => {
  let serverStatus = "converting";
  const f = mockFetch([
    { path: `/api/v1/uploads/${UID}`, handler: () => uploadWith(serverStatus, serverStatus === "published" ? { document_id: "d1" } : {}) },
  ]);
  render(<Probe />);
  expect(await screen.findByTestId("status")).toHaveTextContent("converting");
  const source = await lastSource();
  expect(source.url).toBe(`/api/v1/uploads/${UID}/events`);
  act(() => source.open());
  expect(screen.getByTestId("connection")).toHaveTextContent("live");
  act(() => source.emit("item.status", { item_id: "i1", status: "checking" }, "1"));
  expect(screen.getByTestId("status")).toHaveTextContent("checking");
  act(() => source.emit("item.status", { item_id: "i1", status: "publishing" }, "2"));
  serverStatus = "published";
  act(() => source.emit("upload.settled", { upload_id: UID, last_event_id: 2 }));
  expect(source.closed).toBe(true);
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("published"));
  expect(screen.getByTestId("doc")).toHaveTextContent("d1");
  expect(screen.getByTestId("connection")).toHaveTextContent("closed");
  expect(f.calls.filter((c) => new URL(c.url).pathname === `/api/v1/uploads/${UID}`)).toHaveLength(2);
});

it("does not subscribe when nothing is active any more", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: uploadWith("published", { document_id: "d1" }) }]);
  render(<Probe />);
  expect(await screen.findByTestId("status")).toHaveTextContent("published");
  expect(FakeEventSource.instances).toHaveLength(0);
  expect(screen.getByTestId("connection")).toHaveTextContent("closed");
});

it("reconnects with the browser's Last-Event-ID and applies each event once", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: uploadWith("converting") }]);
  render(<Probe />);
  await screen.findByTestId("status");
  const source = await lastSource();
  act(() => source.open());
  act(() => source.emit("item.status", { item_id: "i1", status: "checking" }, "7"));
  // the browser retries by itself: an error with readyState CONNECTING, then open again, then
  // the replay resumes after id 7 — the hook keeps the same EventSource (it carries the id)
  act(() => source.fail(FakeEventSource.CONNECTING));
  expect(screen.getByTestId("connection")).toHaveTextContent("reconnecting");
  expect(source.closed).toBe(false);
  act(() => source.open());
  expect(screen.getByTestId("connection")).toHaveTextContent("live");
  act(() => source.emit("item.status", { item_id: "i1", status: "checking" }, "7"));
  act(() => source.emit("item.status", { item_id: "i1", status: "publishing" }, "8"));
  expect(screen.getByTestId("status")).toHaveTextContent("publishing");
  expect(FakeEventSource.instances).toHaveLength(1);
});

it("falls back to polling when the browser gives up on the stream", async () => {
  let serverStatus = "converting";
  mockFetch([{ path: `/api/v1/uploads/${UID}`, handler: () => uploadWith(serverStatus) }]);
  render(<Probe pollIntervalMs={20} />);
  expect(await screen.findByTestId("status")).toHaveTextContent("converting");
  const source = await lastSource();
  act(() => source.fail(FakeEventSource.CLOSED));
  expect(screen.getByTestId("connection")).toHaveTextContent("polling");
  expect(source.closed).toBe(true);
  serverStatus = "published"; // the next poll (20 ms) sees it
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("published"));
  expect(screen.getByTestId("connection")).toHaveTextContent("closed");
});

it("reopens the stream when the refresh after settled still shows active items", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: uploadWith("publishing") }]);
  render(<Probe />);
  await screen.findByTestId("status");
  const first = await lastSource();
  act(() => first.open());
  act(() => first.emit("upload.settled", { upload_id: UID, last_event_id: 3 }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
  expect(first.closed).toBe(true);
  expect(FakeEventSource.last.closed).toBe(false);
});

it("shows not found for an upload the user may not see", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, status: 404, body: { detail: "Upload not found." } }]);
  render(<Probe />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Upload not found.");
  expect(FakeEventSource.instances).toHaveLength(0);
});
```

Run: `pnpm test -- src/features/uploads/useUploadProgress.test.tsx` → FAIL (`./useUploadProgress` not found).

- [ ] **Step 6: The progress hook**

`frontend/src/features/uploads/useUploadProgress.ts`:

```ts
"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import { applyItemEvent, parseItemEvent } from "./events";
import { hasActiveItems, type Upload } from "./types";

export type Connection = "idle" | "connecting" | "live" | "reconnecting" | "polling" | "closed";

/** The subset of EventSource the hook uses (jsdom has none; tests inject a fake). */
export interface EventSourceLike {
  readonly readyState: number;
  addEventListener(type: string, listener: (event: Event) => void): void;
  close(): void;
}

type Options = { pollIntervalMs?: number; createEventSource?: (url: string) => EventSourceLike };
type StreamState = { generation: number; connection: Connection };

const CLOSED = 2; // EventSource.CLOSED
const DEFAULT_POLL_MS = 3000;

/** Live state of one upload: load it, follow `/events` while any item is still being
 * processed, apply `item.status` frames, refresh once on `upload.settled` (and reopen if the
 * refresh still shows active items), fall back to polling when the browser gives up on the
 * stream. The browser's own reconnection (with Last-Event-ID) is left alone.
 *
 * `generation` counts the streams opened; the connection state is recorded per generation
 * and derived at render time, so the effect body never calls a state setter itself (only its
 * listeners do, asynchronously). */
export function useUploadProgress(uploadId: string, options: Options = {}) {
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_MS;
  const createEventSource = options.createEventSource;
  const [upload, setUpload] = useState<Upload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const [stream, setStream] = useState<StreamState>({ generation: 0, connection: "idle" });

  const load = useCallback(async (): Promise<Upload | null> => {
    const { data, error: apiError } = await api.GET("/api/v1/uploads/{upload_id}", {
      params: { path: { upload_id: uploadId } },
    });
    if (!data) {
      setError(apiErrorMessage(apiError, m.uploads.notFound));
      return null;
    }
    setError(null);
    setUpload(data);
    return data;
  }, [uploadId]);

  // initial load; subscribe only when something is still being processed
  useEffect(() => {
    let cancelled = false;
    void load().then((data) => {
      if (!cancelled && data && hasActiveItems(data)) setGeneration((g) => g + 1);
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  // one EventSource per generation
  useEffect(() => {
    if (generation === 0) return;
    const factory = createEventSource ?? ((url: string) => new EventSource(url));
    const source = factory(`/api/v1/uploads/${uploadId}/events`);
    const report = (connection: Connection) => setStream({ generation, connection });
    let polling: ReturnType<typeof setInterval> | null = null;
    let stopped = false;
    const stop = () => {
      if (stopped) return;
      stopped = true;
      source.close();
      if (polling) clearInterval(polling);
    };
    const finish = (fresh: Upload | null) => {
      if (fresh && hasActiveItems(fresh)) setGeneration((g) => g + 1);
      else report("closed");
    };
    source.addEventListener("open", () => report("live"));
    source.addEventListener("item.status", (event) => {
      const parsed = parseItemEvent(String((event as MessageEvent).data));
      if (parsed) setUpload((current) => (current ? applyItemEvent(current, parsed) : current));
    });
    source.addEventListener("upload.settled", () => {
      stop();
      void load().then(finish);
    });
    source.addEventListener("error", () => {
      if (source.readyState !== CLOSED) {
        report("reconnecting"); // the browser retries with Last-Event-ID by itself
        return;
      }
      stop(); // the browser gave up: poll until nothing is active
      report("polling");
      polling = setInterval(() => {
        void load().then((fresh) => {
          if (fresh && !hasActiveItems(fresh)) {
            if (polling) clearInterval(polling);
            report("closed");
          }
        });
      }, pollIntervalMs);
    });
    return stop;
  }, [generation, uploadId, createEventSource, pollIntervalMs, load]);

  const reload = useCallback(() => {
    void load().then((fresh) => {
      if (fresh && hasActiveItems(fresh)) setGeneration((g) => g + 1);
    });
  }, [load]);

  const connection: Connection =
    generation === 0
      ? upload
        ? "closed"
        : "idle"
      : stream.generation === generation
        ? stream.connection
        : "connecting";
  return { upload, error, connection, reload };
}
```

Run: `pnpm test -- src/features/uploads/useUploadProgress.test.tsx` → PASS.

- [ ] **Step 7: The wizard — failing tests**

`frontend/src/features/uploads/UploadWizard.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { FakeXHR } from "@/test/fake-xhr";
import { customerMe, memberMe, withSession } from "@/test/session";
import { UploadWizard } from "./UploadWizard";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const PID = "11111111-1111-1111-1111-111111111111";
const taxonomy = {
  version: 1,
  folders: [
    {
      id: "requirements",
      dir: "02-requirements",
      stage: "What",
      doc_types: [
        { key: "srs", id: "srs", title: "Software Requirements Specification", required: true, normalize: true, multi: false },
        { key: "requirements/other", id: "other", title: "Other", required: false, normalize: false, multi: false },
      ],
    },
    {
      id: "deployment",
      dir: "06-deployment",
      stage: "Run",
      doc_types: [{ key: "runbook", id: "runbook", title: "Runbook", required: true, normalize: true, multi: false }],
    },
  ],
};
const limits = {
  max_file_mb: 1,
  max_batch_mb: 2,
  allowed_extensions: ["csv", "docx", "html", "md", "pdf", "pptx", "txt", "xlsx", "zip"],
  zip_max_entries: 200,
};
const project = (role: string, consent = true) => ({
  id: PID,
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: role,
  settings: null,
  storage: null,
  llm_consent: consent ? { confirmed_by_name: "Rep", confirmed_at: "2026-10-01T11:00:00+00:00" } : null,
});

function routes(role = "editor", extra: Parameters<typeof mockFetch>[0] = []) {
  return mockFetch([
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: "/api/v1/upload-limits", body: limits },
    { path: `/api/v1/projects/${PID}`, body: project(role) },
    { path: `/api/v1/projects/${PID}/version-suggestions`, body: [] },
    ...extra,
  ]);
}

beforeEach(() => {
  FakeXHR.install();
  push.mockReset();
});

it("adds files by drop and by picker, lets the user set type and title, and uploads", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  const zone = await screen.findByText("Drop files here");
  fireEvent.drop(zone.closest("[data-dropzone]") as HTMLElement, {
    dataTransfer: { files: [new File([new Uint8Array(1234)], "Portal SRS.docx")], types: ["Files"] },
  });
  await userEvent.upload(screen.getByLabelText("Choose files"), new File(["# Runbook"], "runbook.md"));
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByLabelText("Title")).toHaveValue("Portal SRS");
  expect(within(rows[0]).getByText("1.2 KB")).toBeInTheDocument();
  await userEvent.selectOptions(within(rows[0]).getByLabelText("Document type"), "srs");
  await userEvent.selectOptions(within(rows[1]).getByLabelText("Document type"), "runbook");
  await userEvent.selectOptions(within(rows[1]).getByLabelText("Visibility"), "shared");
  await userEvent.clear(within(rows[1]).getByLabelText("Title"));
  await userEvent.type(within(rows[1]).getByLabelText("Title"), "Ops Runbook");
  FakeXHR.respondWith = { status: 201, body: { id: "u1", project_id: PID, uploaded_by: "me", created_at: "x", items: [], rejected: [] } };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/uploads/u1"));
  const sent = FakeXHR.instances[0];
  expect(sent.url).toBe(`/api/v1/projects/${PID}/uploads`);
  const body = sent.body as FormData;
  expect(body.getAll("files").map((f) => (f as File).name)).toEqual(["Portal SRS.docx", "runbook.md"]);
  expect(JSON.parse(body.get("items") as string)).toEqual([
    { doc_type: "srs", title: "Portal SRS", intent: "new", target_document_id: null, visibility: "internal" },
    { doc_type: "runbook", title: "Ops Runbook", intent: "new", target_document_id: null, visibility: "shared" },
  ]);
});

it("refuses files over the limit and unsupported extensions before upload", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), [
    new File([new Uint8Array(1024 * 1024 + 1)], "huge.pdf"),
    new File(["x"], "virus.exe"),
    new File(["ok"], "fine.md"),
  ]);
  const rows = screen.getAllByRole("listitem");
  expect(within(rows[0]).getByRole("alert")).toHaveTextContent("File is larger than 1 MB.");
  expect(within(rows[1]).getByRole("alert")).toHaveTextContent("File type is not supported.");
  expect(within(rows[0]).queryByLabelText("Document type")).not.toBeInTheDocument();
  await userEvent.selectOptions(within(rows[2]).getByLabelText("Document type"), "srs");
  FakeXHR.respondWith = { status: 201, body: { id: "u2", project_id: PID, uploaded_by: "me", created_at: "x", items: [], rejected: [] } };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(FakeXHR.instances).toHaveLength(1));
  expect((FakeXHR.instances[0].body as FormData).getAll("files").map((f) => (f as File).name)).toEqual(["fine.md"]);
});

it("blocks a batch over the total limit and requires a type for every file", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), [
    new File([new Uint8Array(1024 * 1024)], "a.pdf"),
    new File([new Uint8Array(1024 * 1024)], "b.pdf"),
    new File([new Uint8Array(10)], "c.pdf"),
  ]);
  expect(screen.getByRole("alert")).toHaveTextContent("exceed 2 MB in total");
  expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Remove c.pdf" }));
  await userEvent.click(screen.getByRole("button", { name: "Remove b.pdf" }));
  expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Choose a document type for every file.");
  expect(FakeXHR.instances).toHaveLength(0);
});

it("applies a type and visibility to all files and preselects a version suggestion", async () => {
  routes("owner", [
    {
      path: `/api/v1/projects/${PID}/version-suggestions`,
      handler: (request) =>
        new URL(request.url).searchParams.get("doc_type") === "srs"
          ? [{ document_id: "d-old", title: "Portal SRS", current_version: 2, similarity: 0.92 }]
          : [],
    },
  ]);
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), [new File(["a"], "Portal SRS v3.docx"), new File(["b"], "notes.md")]);
  await userEvent.selectOptions(screen.getByLabelText("Document type for all files"), "srs");
  await userEvent.selectOptions(screen.getByLabelText("Visibility for all files"), "shared");
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  const rows = screen.getAllByRole("listitem");
  expect(within(rows[1]).getByLabelText("Document type")).toHaveValue("srs");
  expect(within(rows[1]).getByLabelText("Visibility")).toHaveValue("shared");
  expect(await within(rows[0]).findByText(/Looks like a new version of "Portal SRS" \(currently v2\)/)).toBeInTheDocument();
  expect(within(rows[0]).getByLabelText("New version of an existing document")).toBeChecked();
  expect(within(rows[0]).getByLabelText("Existing document")).toHaveValue("d-old");
  await userEvent.click(within(rows[0]).getByLabelText("New document"));
  expect(within(rows[0]).queryByLabelText("Existing document")).not.toBeInTheDocument();
});

it("forces shared visibility for customer users and explains the consent gate", async () => {
  routes("client");
  render(withSession(<UploadWizard projectId={PID} />, customerMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), new File(["a"], "brd.docx"));
  const row = screen.getByRole("listitem");
  expect(within(row).queryByLabelText("Visibility")).not.toBeInTheDocument();
  expect(within(row).getByText(/Shared \(documents uploaded by customer users are always shared\)/)).toBeInTheDocument();
  await userEvent.selectOptions(within(row).getByLabelText("Document type"), "srs");
  FakeXHR.respondWith = { status: 409, body: { detail: "The project owner must confirm LLM data processing before documents can be uploaded." } };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("has not recorded the customer's LLM data-processing confirmation");
  expect(within(alert).getByRole("link", { name: "Record it on the project's Overview tab" })).toHaveAttribute("href", `/projects/${PID}`);
  expect(JSON.parse((FakeXHR.instances[0].body as FormData).get("items") as string)[0].visibility).toBe("shared");
});

it("shows rejected files and offers to follow the progress", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), new File(["a"], "a.docx"));
  await userEvent.selectOptions(screen.getByLabelText("Document type"), "srs");
  FakeXHR.respondWith = {
    status: 201,
    body: { id: "u3", project_id: PID, uploaded_by: "me", created_at: "x", items: [], rejected: [{ name: "a.docx", reason: "Zip archives cannot be uploaded as a new version." }] },
  };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  expect(await screen.findByText("Some files were not accepted")).toBeInTheDocument();
  expect(screen.getByText(/Zip archives cannot be uploaded/)).toBeInTheDocument();
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Follow progress" })).toHaveAttribute("href", "/uploads/u3");
});
```

Run: `pnpm test -- src/features/uploads/UploadWizard.test.tsx` → FAIL (`./UploadWizard` not found).

- [ ] **Step 8: FileRow and the wizard**

`frontend/src/features/uploads/FileRow.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { TypeOptions } from "@/components/ui/TypeOptions";
import { api } from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks/useDebouncedValue";
import { m } from "@/messages";
import { extensionOf } from "./limits";
import type { Intent, Taxonomy, VersionSuggestion, Visibility } from "./types";

export type RowState = {
  key: string;
  file: File;
  error: string | null; // guard failure: the row is shown but never sent
  docType: string;
  title: string;
  intent: Intent;
  targetDocumentId: string | null;
  visibility: Visibility;
};

type Props = {
  row: RowState;
  projectId: string;
  taxonomy: Taxonomy;
  clientUser: boolean;
  onChange: (next: RowState) => void;
  onRemove: () => void;
};

const SUGGESTION_THRESHOLD = 0.8; // spec 5.4

export function FileRow({ row, projectId, taxonomy, clientUser, onChange, onRemove }: Props) {
  const [suggestions, setSuggestions] = useState<VersionSuggestion[]>([]);
  const debouncedTitle = useDebouncedValue(row.title, 300);
  const isZip = extensionOf(row.file.name) === "zip";

  useEffect(() => {
    if (row.error || !row.docType || !debouncedTitle.trim() || isZip) return;
    let cancelled = false;
    api
      .GET("/api/v1/projects/{project_id}/version-suggestions", {
        params: { path: { project_id: projectId }, query: { doc_type: row.docType, title: debouncedTitle } },
      })
      .then(({ data }) => {
        if (cancelled || !data) return;
        setSuggestions(data);
        const best = data[0];
        if (best && best.similarity >= SUGGESTION_THRESHOLD && row.intent === "new" && row.targetDocumentId === null) {
          onChange({ ...row, intent: "version", targetDocumentId: best.document_id });
        }
      });
    return () => {
      cancelled = true;
    };
    // `row`/`onChange` change on every edit; the lookup keys are the type and the settled title
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, row.docType, debouncedTitle, row.error, isZip]);

  const best = suggestions[0];
  return (
    <li className="space-y-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium" title={row.file.name}>
            {row.file.name}
          </p>
          <p className="text-xs text-muted">{formatBytes(row.file.size)}</p>
        </div>
        <Button variant="secondary" onClick={onRemove} aria-label={m.uploads.removeFile(row.file.name)}>
          {m.common.remove}
        </Button>
      </div>
      {row.error ? (
        <Alert kind="error">{row.error}</Alert>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label={m.uploads.titleField}
            required
            maxLength={200}
            value={row.title}
            onChange={(event) => onChange({ ...row, title: event.target.value })}
          />
          <Select
            label={m.uploads.docType}
            required
            value={row.docType}
            onChange={(event) => onChange({ ...row, docType: event.target.value, intent: "new", targetDocumentId: null })}
          >
            <option value="">{m.uploads.chooseType}</option>
            <TypeOptions taxonomy={taxonomy} />
          </Select>
          <fieldset className="space-y-1 text-sm sm:col-span-2">
            <legend className="font-medium">{m.uploads.intent}</legend>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`intent-${row.key}`}
                checked={row.intent === "new"}
                onChange={() => onChange({ ...row, intent: "new", targetDocumentId: null })}
              />
              {m.uploads.intentNew}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`intent-${row.key}`}
                disabled={isZip || suggestions.length === 0}
                checked={row.intent === "version"}
                onChange={() => onChange({ ...row, intent: "version", targetDocumentId: suggestions[0]?.document_id ?? null })}
              />
              {m.uploads.intentVersion}
            </label>
            {isZip ? <p className="text-xs text-muted">{m.uploads.zipNoVersion}</p> : null}
            {!isZip && row.docType && suggestions.length === 0 ? (
              <p className="text-xs text-muted">{m.uploads.noSuggestions}</p>
            ) : null}
            {best && row.intent !== "version" ? (
              <p className="text-xs text-muted">{m.uploads.suggestionHint(best.title, best.current_version)}</p>
            ) : null}
            {row.intent === "version" ? (
              <Select
                label={m.uploads.versionTarget}
                value={row.targetDocumentId ?? ""}
                onChange={(event) => onChange({ ...row, targetDocumentId: event.target.value || null })}
              >
                {suggestions.map((s) => (
                  <option key={s.document_id} value={s.document_id}>
                    {s.title} (v{s.current_version})
                  </option>
                ))}
              </Select>
            ) : null}
            {best && row.intent === "version" ? (
              <p className="text-xs text-muted">{m.uploads.suggestionHint(best.title, best.current_version)}</p>
            ) : null}
          </fieldset>
          {clientUser ? (
            <p className="text-sm sm:col-span-2">
              <Badge>{m.uploads.sharedForced}</Badge>
            </p>
          ) : (
            <Select
              label={m.uploads.visibility}
              value={row.visibility}
              onChange={(event) => onChange({ ...row, visibility: event.target.value as Visibility })}
            >
              <option value="internal">{m.uploads.visibilityInternal}</option>
              <option value="shared">{m.uploads.visibilityShared}</option>
            </Select>
          )}
        </div>
      )}
    </li>
  );
}
```

`frontend/src/features/uploads/UploadWizard.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { TypeOptions } from "@/components/ui/TypeOptions";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { uploadMultipart, type UploadOut } from "@/lib/api/upload";
import { useLoad } from "@/lib/hooks/useLoad";
import { cx } from "@/lib/cx";
import { m } from "@/messages";
import { FileRow, type RowState } from "./FileRow";
import { batchGuard, guardFile } from "./limits";
import type { Visibility } from "./types";

function titleFromFilename(name: string): string {
  const base = name.replace(/\\/g, "/").split("/").pop() ?? name;
  const dot = base.lastIndexOf(".");
  const stem = dot > 0 ? base.slice(0, dot) : base;
  return stem.replace(/[_\-\s]+/g, " ").trim().slice(0, 200) || "Untitled";
}

let counter = 0;

export function UploadWizard({ projectId }: { projectId: string }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<RowState[]>([]);
  const [dragging, setDragging] = useState(false);
  const [bulkType, setBulkType] = useState("");
  const [bulkVisibility, setBulkVisibility] = useState<Visibility | "">("");
  const [formError, setFormError] = useState<string | null>(null);
  const [consentBlocked, setConsentBlocked] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<UploadOut | null>(null);

  const taxonomy = useLoad(() => api.GET("/api/v1/taxonomy").then((r) => unwrap(r)), []);
  const limits = useLoad(() => api.GET("/api/v1/upload-limits").then((r) => unwrap(r)), []);
  const project = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}", { params: { path: { project_id: projectId } } })
        .then((r) => unwrap(r, m.projects.notFound)),
    [projectId],
  );

  const uploading = progress !== null;
  useEffect(() => {
    if (!uploading) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = m.uploads.leaveWarning;
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [uploading]);

  const clientUser = project.data?.my_role === "client";
  const sendable = rows.filter((row) => row.error === null);
  const batchError = limits.data ? batchGuard(sendable.map((r) => r.file), limits.data) : null;

  function addFiles(files: FileList | File[]) {
    if (!limits.data) return;
    const current = limits.data;
    const added = Array.from(files).map<RowState>((file) => ({
      key: `f${(counter += 1)}`,
      file,
      error: guardFile(file, current),
      docType: "",
      title: titleFromFilename(file.name),
      intent: "new",
      targetDocumentId: null,
      visibility: "internal",
    }));
    setRows((existing) => [...existing, ...added]);
    setFormError(null);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  }

  function update(key: string, next: RowState) {
    setRows((existing) => existing.map((row) => (row.key === key ? next : row)));
  }

  function applyToAll() {
    setRows((existing) =>
      existing.map((row) => ({
        ...row,
        docType: bulkType || row.docType,
        intent: bulkType && bulkType !== row.docType ? "new" : row.intent,
        targetDocumentId: bulkType && bulkType !== row.docType ? null : row.targetDocumentId,
        visibility: bulkVisibility || row.visibility,
      })),
    );
  }

  async function submit() {
    setFormError(null);
    setConsentBlocked(false);
    if (sendable.length === 0) {
      setFormError(m.uploads.nothingToUpload);
      return;
    }
    if (sendable.some((row) => !row.docType)) {
      setFormError(m.uploads.typeRequired);
      return;
    }
    const form = new FormData();
    for (const row of sendable) form.append("files", row.file, row.file.name);
    form.append(
      "items",
      JSON.stringify(
        sendable.map((row) => ({
          doc_type: row.docType,
          title: row.title.trim() || null,
          intent: row.intent,
          target_document_id: row.intent === "version" ? row.targetDocumentId : null,
          visibility: clientUser ? "shared" : row.visibility,
        })),
      ),
    );
    setProgress(0);
    try {
      const response = await uploadMultipart(`/api/v1/projects/${projectId}/uploads`, form, (fraction) =>
        setProgress(Math.round(fraction * 100)),
      );
      if (!response.ok) {
        if (response.status === 409) setConsentBlocked(true);
        else {
          const detail = (response.error as { detail?: unknown } | null)?.detail;
          const message =
            detail && typeof detail === "object" && "message" in detail
              ? String((detail as { message: unknown }).message)
              : typeof detail === "string"
                ? detail
                : m.common.requestFailed;
          const rejected =
            detail && typeof detail === "object" && "rejected" in detail
              ? (detail as { rejected: { name: string; reason: string }[] }).rejected
              : [];
          setFormError([message, ...rejected.map((r) => `${r.name}: ${r.reason}`)].join(" "));
        }
        return;
      }
      if (response.data.rejected.length > 0) {
        setResult(response.data);
        return;
      }
      router.push(`/uploads/${response.data.id}`);
    } catch {
      setFormError(m.common.requestFailed);
    } finally {
      setProgress(null);
    }
  }

  const loadError = taxonomy.error ?? limits.error ?? project.error;
  if (loadError) return <Alert kind="error">{loadError}</Alert>;
  if (!taxonomy.data || !limits.data || !project.data) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }

  return (
    <>
      <PageHeader
        title={m.uploads.title}
        actions={
          <Link href={`/projects/${projectId}`} className="text-sm text-brand underline">
            {m.uploads.backToProject}
          </Link>
        }
      />
      <p className="mb-4 text-sm text-muted">{m.uploads.intro}</p>
      <div
        data-dropzone
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cx(
          "mb-6 flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-6 text-center",
          dragging ? "border-brand bg-brand/5" : "border-border",
        )}
      >
        <p className="text-sm text-muted">{m.uploads.dropHere}</p>
        <label htmlFor="wizard-files" className="sr-only">
          {m.uploads.chooseFiles}
        </label>
        <input
          id="wizard-files"
          ref={inputRef}
          type="file"
          multiple
          accept={limits.data.allowed_extensions.map((ext) => `.${ext}`).concat(".htm").join(",")}
          className="sr-only"
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <Button variant="secondary" onClick={() => inputRef.current?.click()}>
          {m.uploads.chooseFiles}
        </Button>
      </div>
      {rows.length === 0 ? <p className="text-muted">{m.uploads.noFiles}</p> : null}
      {rows.length > 1 ? (
        <div className="mb-4 grid gap-3 rounded-lg border border-border p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Select label={m.uploads.applyTypeToAll} value={bulkType} onChange={(event) => setBulkType(event.target.value)}>
            <option value="">—</option>
            <TypeOptions taxonomy={taxonomy.data} />
          </Select>
          {clientUser ? (
            <div />
          ) : (
            <Select
              label={m.uploads.applyVisibilityToAll}
              value={bulkVisibility}
              onChange={(event) => setBulkVisibility(event.target.value as Visibility | "")}
            >
              <option value="">—</option>
              <option value="internal">{m.uploads.visibilityInternal}</option>
              <option value="shared">{m.uploads.visibilityShared}</option>
            </Select>
          )}
          <Button variant="secondary" onClick={applyToAll} disabled={!bulkType && !bulkVisibility}>
            {m.uploads.apply}
          </Button>
        </div>
      ) : null}
      <ul className="space-y-3">
        {rows.map((row) => (
          <FileRow
            key={row.key}
            row={row}
            projectId={projectId}
            taxonomy={taxonomy.data}
            clientUser={clientUser}
            onChange={(next) => update(row.key, next)}
            onRemove={() => setRows((existing) => existing.filter((r) => r.key !== row.key))}
          />
        ))}
      </ul>
      <div className="mt-6 space-y-3">
        {batchError ? <Alert kind="error">{batchError}</Alert> : null}
        {formError ? <Alert kind="error">{formError}</Alert> : null}
        {consentBlocked ? (
          <Alert kind="error">
            {m.uploads.consentRequired}{" "}
            <Link href={`/projects/${projectId}`} className="underline">
              {m.uploads.consentLink}
            </Link>
          </Alert>
        ) : null}
        {result ? (
          <Alert kind="info">
            <p className="font-medium">{m.uploads.rejectedTitle}</p>
            <ul className="list-disc pl-5">
              {result.rejected.map((r) => (
                <li key={r.name}>
                  {r.name}: {r.reason}
                </li>
              ))}
            </ul>
            <Link href={`/uploads/${result.id}`} className="underline">
              {m.uploads.followProgress}
            </Link>
          </Alert>
        ) : null}
        {progress !== null ? (
          <div>
            <label htmlFor="wizard-progress" className="text-sm">
              {m.uploads.uploading(progress)}
            </label>
            <progress id="wizard-progress" className="block w-full" max={100} value={progress} />
          </div>
        ) : null}
        <Button onClick={() => void submit()} busy={uploading} disabled={rows.length === 0 || batchError !== null}>
          {m.uploads.submit}
        </Button>
      </div>
    </>
  );
}
```

(A 201 always carries at least one accepted item — an upload with none is a 422 — so the "Follow progress" link is unconditional.)

Routes — `frontend/src/app/(app)/projects/[projectId]/upload/page.tsx`:

```tsx
import { UploadWizard } from "@/features/uploads/UploadWizard";

export default async function Page({ params }: PageProps<"/projects/[projectId]/upload">) {
  const { projectId } = await params;
  return <UploadWizard projectId={projectId} />;
}
```

Run: `pnpm typecheck && pnpm test -- src/features/uploads/UploadWizard.test.tsx` → PASS. (`next typegen` in `pnpm typecheck` generates the `PageProps<"/projects/[projectId]/upload">` type from the new route file.)

- [ ] **Step 9: The progress view — failing tests**

`frontend/src/features/uploads/UploadProgress.test.tsx`:

```tsx
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { FakeEventSource } from "@/test/fake-event-source";
import { memberMe, withSession } from "@/test/session";
import { UploadProgress } from "./UploadProgress";

const UID = "22222222-2222-2222-2222-222222222222";
const PID = "11111111-1111-1111-1111-111111111111";
const base = {
  upload_id: UID,
  ext: "docx",
  size: 2048,
  sha256: "x",
  final_doc_type: null,
  intent: "new",
  target_document_id: null,
  visibility: "internal",
  type_check: null,
  check_explanation: null,
  suggested_doc_type: null,
  version_hint_document_id: null,
  warnings: [],
  conversion_meta: {},
  error: null,
  document_id: null,
  created_at: "2026-10-02T09:00:00+00:00",
  updated_at: "2026-10-02T09:00:00+00:00",
};
const upload = {
  id: UID,
  project_id: PID,
  uploaded_by: "me",
  created_at: "2026-10-02T09:00:00+00:00",
  rejected: [],
  items: [
    { ...base, id: "i1", original_name: "srs.docx", selected_doc_type: "srs", title: "SRS", status: "converting" },
    { ...base, id: "i2", original_name: "plan.docx", selected_doc_type: "srs", title: "Plan", status: "needs_confirmation", check_explanation: "Reads like a test plan.", suggested_doc_type: "test-plan" },
    { ...base, id: "i3", original_name: "broken.docx", selected_doc_type: "brd", title: "Broken", status: "failed", error: "File content does not match its extension." },
    { ...base, id: "i4", original_name: "scan.pdf", ext: "pdf", selected_doc_type: "deploy-guide", title: "Scan", status: "published", type_check: "skipped", document_id: "d4", warnings: ["low_text"] },
  ],
};

beforeEach(() => FakeEventSource.install());

async function lastSource(): Promise<FakeEventSource> {
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
  return FakeEventSource.last;
}

it("lists every file with its status, explanations, links and the live indicator", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: upload }]);
  render(withSession(<UploadProgress uploadId={UID} />, memberMe).element);
  expect(await screen.findByRole("heading", { name: "Upload progress" })).toBeInTheDocument();
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(4);
  expect(within(rows[0]).getByText("Converting")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Needs confirmation")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Reads like a test plan.")).toBeInTheDocument();
  expect(within(rows[1]).getByRole("link", { name: "Confirm in My tasks" })).toHaveAttribute("href", "/tasks");
  expect(within(rows[2]).getByText("Failed")).toBeInTheDocument();
  expect(within(rows[2]).getByText("File content does not match its extension.")).toBeInTheDocument();
  expect(within(rows[2]).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  expect(within(rows[3]).getByText("Published")).toBeInTheDocument();
  expect(within(rows[3]).getByRole("link", { name: "Open document" })).toHaveAttribute("href", "/documents/d4");
  expect(within(rows[3]).getByText(/Little extractable text/)).toBeInTheDocument();
  expect(within(rows[3]).getByText("Type check skipped")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Back to project" })).toHaveAttribute("href", `/projects/${PID}`);
  const source = await lastSource();
  act(() => source.open());
  expect(screen.getByRole("status", { name: "Connection" })).toHaveTextContent("Live");
});

it("updates a row from an event and retries a failed item", async () => {
  let retried = false; // the page reloads the upload after the retry
  const retriedItem = { ...upload.items[2], status: "uploaded", error: null };
  const f = mockFetch([
    {
      path: `/api/v1/uploads/${UID}`,
      handler: () => (retried ? { ...upload, items: [upload.items[0], upload.items[1], retriedItem, upload.items[3]] } : upload),
    },
    {
      method: "POST",
      path: "/api/v1/upload-items/i3/retry",
      handler: () => {
        retried = true;
        return retriedItem;
      },
    },
  ]);
  render(withSession(<UploadProgress uploadId={UID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Upload progress" });
  const source = await lastSource();
  act(() => source.open());
  act(() => source.emit("item.status", { item_id: "i1", status: "published", document_id: "d1", type_check: "match" }, "9"));
  const first = screen.getAllByRole("listitem")[0];
  expect(within(first).getByText("Published")).toBeInTheDocument();
  expect(within(first).getByRole("link", { name: "Open document" })).toHaveAttribute("href", "/documents/d1");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(f.find("POST", "/api/v1/upload-items/i3/retry")).toBeDefined();
  expect(await within(screen.getAllByRole("listitem")[2]).findByText("Queued")).toBeInTheDocument();
});

it("shows not found for an upload the user may not see", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, status: 404, body: { detail: "Upload not found." } }]);
  render(withSession(<UploadProgress uploadId={UID} />, memberMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Upload not found.");
});
```

Run: `pnpm test -- src/features/uploads/UploadProgress.test.tsx` → FAIL (`./UploadProgress` not found).

- [ ] **Step 10: The progress view**

`frontend/src/features/uploads/UploadProgress.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import { m } from "@/messages";
import type { UploadItem } from "./types";
import { useUploadProgress, type Connection } from "./useUploadProgress";

const CONNECTION_LABEL: Record<Connection, string> = {
  idle: "",
  connecting: m.uploads.reconnecting,
  live: m.uploads.live,
  reconnecting: m.uploads.reconnecting,
  polling: m.uploads.polling,
  closed: m.uploads.settled,
};

function ItemCard({ item, onRetry }: { item: UploadItem; onRetry: (item: UploadItem) => Promise<void> }) {
  const [retryError, setRetryError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const typeCheck = item.type_check ? m.uploads.typeCheck[item.type_check] : null;
  return (
    <li className="space-y-2 rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium" title={item.original_name}>
            {item.original_name}
          </p>
          <p className="text-xs text-muted">
            {item.title} · {formatBytes(item.size)}
          </p>
        </div>
        <StatusBadge status={item.status} />
      </div>
      {item.check_explanation ? <p className="text-sm text-muted">{item.check_explanation}</p> : null}
      {typeCheck ? <p className="text-xs text-muted">{typeCheck}</p> : null}
      {item.warnings.includes("low_text") ? <p className="text-xs text-warning">{m.uploads.lowText}</p> : null}
      {item.status === "failed" && item.error ? <p className="text-sm text-danger">{item.error}</p> : null}
      {retryError ? <Alert kind="error">{retryError}</Alert> : null}
      <div className="flex flex-wrap gap-3 text-sm">
        {item.status === "needs_confirmation" ? (
          <Link href="/tasks" className="text-brand underline">
            {m.uploads.goToTasks}
          </Link>
        ) : null}
        {item.status === "published" && item.document_id ? (
          <Link href={`/documents/${item.document_id}`} className="text-brand underline">
            {m.uploads.openDocument}
          </Link>
        ) : null}
        {item.status === "failed" ? (
          <Button
            variant="secondary"
            busy={busy}
            onClick={() => {
              setBusy(true);
              setRetryError(null);
              onRetry(item)
                .catch((reason: unknown) => setRetryError(reason instanceof Error ? reason.message : m.common.requestFailed))
                .finally(() => setBusy(false));
            }}
          >
            {m.uploads.retryItem}
          </Button>
        ) : null}
      </div>
    </li>
  );
}

export function UploadProgress({ uploadId }: { uploadId: string }) {
  const progress = useUploadProgress(uploadId);
  const upload = progress.upload;

  async function retry(item: UploadItem) {
    const { data, error } = await api.POST("/api/v1/upload-items/{item_id}/retry", {
      params: { path: { item_id: item.id } },
    });
    if (!data) throw new Error(apiErrorMessage(error, m.common.requestFailed));
    progress.reload(); // the retried item is active again: the hook reopens the stream
  }

  if (progress.error) return <Alert kind="error">{progress.error}</Alert>;
  if (!upload) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  return (
    <>
      <PageHeader
        title={m.uploads.progressTitle}
        actions={
          <Link href={`/projects/${upload.project_id}`} className="text-sm text-brand underline">
            {m.uploads.backToProject}
          </Link>
        }
      />
      <p role="status" aria-label={m.uploads.connectionLabel} className="mb-4 text-sm text-muted">
        {CONNECTION_LABEL[progress.connection]}
      </p>
      <ul className="space-y-3">
        {upload.items.map((item) => (
          <ItemCard key={item.id} item={item} onRetry={retry} />
        ))}
      </ul>
    </>
  );
}
```

Route — `frontend/src/app/(app)/uploads/[uploadId]/page.tsx`:

```tsx
import { UploadProgress } from "@/features/uploads/UploadProgress";

export default async function Page({ params }: PageProps<"/uploads/[uploadId]">) {
  const { uploadId } = await params;
  return <UploadProgress uploadId={uploadId} />;
}
```

Run: `pnpm typecheck && pnpm test -- src/features/uploads` → PASS.

- [ ] **Step 11: All frontend checks and commit**

Run: `pnpm format:write && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build`
Expected: PASS.

```bash
git add frontend/src/features/uploads "frontend/src/app/(app)/projects/[projectId]/upload/page.tsx" "frontend/src/app/(app)/uploads/[uploadId]/page.tsx"
git commit -m "feat(frontend): upload wizard with client-side guards and live progress over Server-Sent Events"
```

### Task 6: Document browser, document page, gap report, project tabs

**Files:**
- Create: `frontend/src/features/documents/types.ts`, `frontend/src/features/documents/DocumentBrowser.tsx`, `frontend/src/features/documents/DocumentBrowser.test.tsx`, `frontend/src/features/documents/DocumentPage.tsx`, `frontend/src/features/documents/DocumentPage.test.tsx`, `frontend/src/features/documents/FrontmatterPanel.tsx`, `frontend/src/features/documents/EditDocumentDialog.tsx`, `frontend/src/features/documents/GapReport.tsx`, `frontend/src/features/documents/GapReport.test.tsx`, `frontend/src/app/(app)/documents/[documentId]/page.tsx`
- Modify: `frontend/src/features/projects/ProjectPage.tsx` (tabs), `frontend/src/features/projects/ProjectPage.test.tsx` (Overview is no longer the landing tab), `frontend/e2e/first-run.spec.ts` (two `Overview` tab clicks)

**Interfaces:**
- Consumes: `api`, `unwrap`, `apiErrorMessage`, `useLoad`, `useSession`, `useDebouncedValue`, `Tabs`, `MarkdownView`, `Dialog`, `Field`, `Select`, `Badge`, `Alert`, `Button`, `formatDate`, `formatDateTime`, `m` (Task 4); backend `GET /taxonomy`, `GET /projects/{id}/documents` (filters `folder`, `doc_type`, `visibility`, `q`), `GET /documents/{id}`, `GET /documents/{id}/versions`, `GET /documents/{id}/versions/{v}/content`, `PATCH /documents/{id}`, `GET /projects/{id}/gap-report`, download URLs `/api/v1/documents/{id}/versions/{v}/original` and `/markdown` (Plan 2, Task 2).
- Produces: route `/documents/[documentId]`; `DocumentBrowser({ projectId, role })`, `DocumentPage({ documentId })`, `GapReport({ projectId })`, `FrontmatterPanel({ frontmatter })`, `EditDocumentDialog({ doc, role, onClose, onSaved })`; `ProjectPage` tabs "Documents" (default), "Overview", "Gap report" (internal), "Members" (internal), "Settings" (owner) with an "Upload documents" link to `/projects/{id}/upload` for uploader roles. Labels Task 8 relies on: tab names, "Upload documents", "Search titles", "Download original", "Download Markdown", "Markdown"/"Versions" tabs, "Details", gap report headings "Present"/"Placeholder"/"Missing".

- [ ] **Step 1: Types**

`frontend/src/features/documents/types.ts`:

```ts
import type { components } from "@/lib/api/schema";

export type Document = components["schemas"]["DocumentOut"];
export type DocumentVersion = components["schemas"]["DocumentVersionOut"];
export type DocumentContent = components["schemas"]["DocumentContentOut"];
export type GapReportData = components["schemas"]["GapReportOut"];
export type Taxonomy = components["schemas"]["TaxonomyOut"];

export const EDITOR_ROLES = ["owner", "editor"] as const;
export const INTERNAL_ROLES = ["owner", "editor", "viewer"] as const;

export function canEdit(role: string): boolean {
  return (EDITOR_ROLES as readonly string[]).includes(role);
}

export function isInternal(role: string): boolean {
  return (INTERNAL_ROLES as readonly string[]).includes(role);
}

export function originalUrl(documentId: string, version: number): string {
  return `/api/v1/documents/${documentId}/versions/${version}/original`;
}

export function markdownUrl(documentId: string, version: number): string {
  return `/api/v1/documents/${documentId}/versions/${version}/markdown`;
}
```

- [ ] **Step 2: Document browser — failing tests**

`frontend/src/features/documents/DocumentBrowser.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { DocumentBrowser } from "./DocumentBrowser";

const PID = "11111111-1111-1111-1111-111111111111";
const taxonomy = {
  version: 1,
  folders: [
    {
      id: "overview",
      dir: "01-overview",
      stage: "Why",
      doc_types: [{ key: "readme", id: "readme", title: "Project README", required: true, normalize: true, multi: false }],
    },
    {
      id: "requirements",
      dir: "02-requirements",
      stage: "What",
      doc_types: [{ key: "srs", id: "srs", title: "Software Requirements Specification", required: true, normalize: true, multi: false }],
    },
    {
      id: "deployment",
      dir: "06-deployment",
      stage: "Run",
      doc_types: [{ key: "runbook", id: "runbook", title: "Runbook", required: true, normalize: true, multi: false }],
    },
  ],
};
const doc = (overrides: Record<string, unknown>) => ({
  id: "d1",
  project_id: PID,
  folder_id: "requirements",
  doc_type: "srs",
  title: "Portal SRS",
  slug: "portal-srs",
  visibility: "internal",
  current_version: 2,
  is_stub: false,
  created_by: "u1",
  created_at: "2026-10-01T10:00:00+00:00",
  updated_at: "2026-10-01T12:00:00+00:00",
  uploaded_by_name: "Editor",
  version_created_at: "2026-10-01T12:00:00+00:00",
  ...overrides,
});
const documents = [
  doc({ id: "stub-readme", folder_id: "overview", doc_type: "readme", title: "Project README", slug: "", is_stub: true, current_version: 1, uploaded_by_name: "Owner" }),
  doc({}),
  doc({ id: "d2", title: "Ops Runbook", doc_type: "runbook", folder_id: "deployment", visibility: "shared" }),
];

it("groups documents by folder, shows stubs as placeholders and links to the document page", async () => {
  mockFetch([
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: documents },
  ]);
  render(<DocumentBrowser projectId={PID} role="editor" />);
  expect(await screen.findByRole("link", { name: "Portal SRS" })).toHaveAttribute("href", "/documents/d1");
  const groups = screen.getAllByRole("list", { name: /^(01-overview|02-requirements|06-deployment)/ });
  expect(groups).toHaveLength(3);
  const overview = screen.getByRole("list", { name: /^01-overview/ });
  expect(within(overview).getByText("Placeholder")).toBeInTheDocument();
  const srs = screen.getByRole("link", { name: "Portal SRS" }).closest("li") as HTMLElement;
  expect(within(srs).getByText("v2")).toBeInTheDocument();
  expect(within(srs).getByText(/Editor/)).toBeInTheDocument();
  expect(within(srs).getByText("Internal")).toBeInTheDocument();
  expect(within(srs).getByText(/Software Requirements Specification/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload documents" })).toHaveAttribute("href", `/projects/${PID}/upload`);
});

it("sends filters as query parameters and debounces the text search", async () => {
  const f = mockFetch([
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, handler: (request) => (new URL(request.url).searchParams.get("q") === "portal" ? [documents[1]] : documents) },
  ]);
  render(<DocumentBrowser projectId={PID} role="viewer" />);
  await screen.findByRole("link", { name: "Portal SRS" });
  await userEvent.selectOptions(screen.getByLabelText("Folder"), "requirements");
  await userEvent.selectOptions(screen.getByLabelText("Document type"), "srs");
  await userEvent.selectOptions(screen.getByLabelText("Visibility"), "shared");
  await userEvent.type(screen.getByLabelText("Search titles"), "portal");
  await waitFor(() => {
    const last = f.calls.filter((c) => new URL(c.url).pathname === `/api/v1/projects/${PID}/documents`).at(-1);
    expect(last && Object.fromEntries(new URL(last.url).searchParams)).toEqual({
      folder: "requirements",
      doc_type: "srs",
      visibility: "shared",
      q: "portal",
    });
  });
  await waitFor(() => expect(screen.queryByText("Ops Runbook")).not.toBeInTheDocument()); // only "Portal SRS" for q=portal
  expect(screen.queryByRole("link", { name: "Upload documents" })).not.toBeInTheDocument(); // viewers cannot upload
});

it("hides the visibility filter from clients and shows an empty state", async () => {
  mockFetch([
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
  ]);
  render(<DocumentBrowser projectId={PID} role="client" />);
  expect(await screen.findByText("No documents match these filters.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Visibility")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload documents" })).toBeInTheDocument(); // clients upload
});
```

Run: `pnpm test -- src/features/documents/DocumentBrowser.test.tsx` → FAIL (`./DocumentBrowser` not found).

- [ ] **Step 3: Document browser**

`frontend/src/features/documents/DocumentBrowser.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks/useDebouncedValue";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { isInternal, type Document, type Taxonomy } from "./types";

const UPLOADER_ROLES = ["owner", "editor", "client"];

function typeTitle(taxonomy: Taxonomy, key: string): string {
  for (const folder of taxonomy.folders) {
    const found = folder.doc_types.find((t) => t.key === key);
    if (found) return found.title;
  }
  return key;
}

export function DocumentBrowser({ projectId, role }: { projectId: string; role: string }) {
  const [folder, setFolder] = useState("");
  const [docType, setDocType] = useState("");
  const [visibility, setVisibility] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search.trim(), 300);
  const taxonomy = useLoad(() => api.GET("/api/v1/taxonomy").then((r) => unwrap(r)), []);
  const documents = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}/documents", {
          params: {
            path: { project_id: projectId },
            query: {
              folder: folder || undefined,
              doc_type: docType || undefined,
              visibility: (visibility || undefined) as "internal" | "shared" | undefined,
              q: q || undefined,
            },
          },
        })
        .then((r) => unwrap(r)),
    [projectId, folder, docType, visibility, q],
  );

  if (taxonomy.error) return <Alert kind="error">{taxonomy.error}</Alert>;
  if (!taxonomy.data) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  const folders = taxonomy.data.folders;
  const typeChoices = folders
    .filter((f) => !folder || f.id === folder)
    .flatMap((f) => f.doc_types.map((t) => ({ key: t.key, title: `${t.title}` })));
  const grouped = folders
    .map((f) => ({ folder: f, items: (documents.data ?? []).filter((d) => d.folder_id === f.id) }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid w-full gap-3 sm:grid-cols-2 md:w-auto md:grid-cols-4">
          <Select
            label={m.documents.filterFolder}
            value={folder}
            onChange={(event) => {
              setFolder(event.target.value);
              setDocType("");
            }}
          >
            <option value="">{m.documents.allFolders}</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.dir} ({f.stage})
              </option>
            ))}
          </Select>
          <Select label={m.documents.filterType} value={docType} onChange={(event) => setDocType(event.target.value)}>
            <option value="">{m.documents.allTypes}</option>
            {typeChoices.map((t) => (
              <option key={t.key} value={t.key}>
                {t.title}
              </option>
            ))}
          </Select>
          {isInternal(role) ? (
            <Select label={m.documents.filterVisibility} value={visibility} onChange={(event) => setVisibility(event.target.value)}>
              <option value="">{m.common.all}</option>
              <option value="internal">{m.documents.internal}</option>
              <option value="shared">{m.documents.shared}</option>
            </Select>
          ) : null}
          <Field label={m.documents.search} type="search" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
        {UPLOADER_ROLES.includes(role) ? (
          <Link href={`/projects/${projectId}/upload`} className="inline-flex min-h-10 items-center rounded-md bg-brand px-3 text-sm font-medium text-brand-fg">
            {m.documents.upload}
          </Link>
        ) : null}
      </div>
      {documents.error ? (
        <Alert kind="error">
          {documents.error}{" "}
          <Button variant="secondary" onClick={documents.reload}>
            {m.common.retry}
          </Button>
        </Alert>
      ) : null}
      {documents.loading && !documents.data ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : null}
      {documents.data && documents.data.length === 0 ? <p className="text-muted">{m.documents.empty}</p> : null}
      {grouped.map(({ folder: f, items }) => (
        <section key={f.id}>
          <h2 id={`folder-${f.id}`} className="mb-2 text-sm font-semibold text-muted">
            {f.dir} · {f.stage}
          </h2>
          <ul aria-labelledby={`folder-${f.id}`} className="space-y-2">
            {items.map((d) => (
              <DocumentCard key={d.id} document={d} taxonomy={taxonomy.data as Taxonomy} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function DocumentCard({ document, taxonomy }: { document: Document; taxonomy: Taxonomy }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3">
      <div className="min-w-0">
        <p className="truncate">
          <Link href={`/documents/${document.id}`} className="font-medium text-brand">
            {document.title}
          </Link>
        </p>
        <p className="text-xs text-muted">
          {typeTitle(taxonomy, document.doc_type)}
          {document.uploaded_by_name ? <> · {document.uploaded_by_name}</> : null}
          {document.version_created_at ? <> · {formatDate(document.version_created_at)}</> : null}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {document.is_stub ? (
          <Badge tone="warning">{m.documents.stub}</Badge>
        ) : (
          <Badge>{m.documents.version(document.current_version)}</Badge>
        )}
        <Badge tone={document.visibility === "shared" ? "success" : "neutral"}>
          {document.visibility === "shared" ? m.documents.shared : m.documents.internal}
        </Badge>
      </div>
    </li>
  );
}
```

The accessible name of each `<ul>` is the heading text (`01-overview · Why`), which the tests match with `/^01-overview/`. The `typeTitle` helper also returns `title` for `<folder>/other` keys ("Other").

Run: `pnpm test -- src/features/documents/DocumentBrowser.test.tsx` → PASS.

- [ ] **Step 4: Gap report — failing test, then implementation**

`frontend/src/features/documents/GapReport.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { GapReport } from "./GapReport";

const PID = "11111111-1111-1111-1111-111111111111";
const report = {
  qc_agent: 2,
  project: { slug: "demo", name: "Demo" },
  generated_at: "2026-10-02T09:30:00+00:00",
  required_total: 10,
  required_present: 2,
  completeness: 0.2,
  folders: [
    {
      id: "requirements",
      dir: "02-requirements",
      stage: "What",
      doc_types: [
        { doc_type: "brd", title: "Business Requirements Document", required: true, status: "stub", documents: 0 },
        { doc_type: "srs", title: "Software Requirements Specification", required: true, status: "present", documents: 1 },
        { doc_type: "use-cases", title: "Use Cases", required: false, status: "missing", documents: 0 },
      ],
    },
  ],
};

it("shows completeness and each type's status per folder", async () => {
  mockFetch([{ path: `/api/v1/projects/${PID}/gap-report`, body: report }]);
  render(<GapReport projectId={PID} />);
  expect(await screen.findByText("2 of 10 required types present (20%)")).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "02-requirements (What)" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(3);
  expect(within(rows[0]).getByText("Placeholder")).toBeInTheDocument();
  expect(within(rows[0]).getByText("Required")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Present")).toBeInTheDocument();
  expect(within(rows[1]).getByText("1")).toBeInTheDocument();
  expect(within(rows[2]).getByText("Missing")).toBeInTheDocument();
  expect(within(rows[2]).getByText("Optional")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Gap report" })).toHaveAttribute("aria-valuenow", "20");
});

it("shows the API error", async () => {
  mockFetch([{ path: `/api/v1/projects/${PID}/gap-report`, status: 403, body: { detail: "You do not have access to this action." } }]);
  render(<GapReport projectId={PID} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("You do not have access to this action.");
});
```

`frontend/src/features/documents/GapReport.tsx`:

```tsx
"use client";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";

const STATUS_LABEL: Record<string, string> = {
  present: m.gaps.present,
  stub: m.gaps.stub,
  missing: m.gaps.missing,
};
const STATUS_TONE: Record<string, "success" | "warning" | "danger"> = {
  present: "success",
  stub: "warning",
  missing: "danger",
};

export function GapReport({ projectId }: { projectId: string }) {
  const report = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}/gap-report", { params: { path: { project_id: projectId } } })
        .then((r) => unwrap(r)),
    [projectId],
  );
  if (report.error) return <Alert kind="error">{report.error}</Alert>;
  if (!report.data) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  const data = report.data;
  const percent = Math.round(data.completeness * 100);
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">{m.gaps.intro}</p>
      <div>
        <p className="font-medium">{m.gaps.completeness(data.required_present, data.required_total, percent)}</p>
        <div
          role="progressbar"
          aria-label={m.gaps.title}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="mt-1 h-2 w-full overflow-hidden rounded bg-border"
        >
          <div className="h-full bg-success" style={{ width: `${percent}%` }} />
        </div>
        <p className="mt-1 text-xs text-muted">{m.gaps.generated(formatDateTime(data.generated_at))}</p>
      </div>
      {data.folders.map((folder) => (
        <section key={folder.id}>
          <h2 className="mb-2 text-sm font-semibold">
            {folder.dir} ({folder.stage})
          </h2>
          <Table caption={`${folder.dir} (${folder.stage})`}>
            <thead>
              <tr>
                <Th>{m.gaps.type}</Th>
                <Th>{m.gaps.required}</Th>
                <Th>{m.gaps.status}</Th>
                <Th>{m.gaps.documents}</Th>
              </tr>
            </thead>
            <tbody>
              {folder.doc_types.map((entry) => (
                <tr key={entry.doc_type}>
                  <Td>{entry.title}</Td>
                  <Td>{entry.required ? m.gaps.required : m.gaps.optional}</Td>
                  <Td>
                    <Badge tone={STATUS_TONE[entry.status]}>{STATUS_LABEL[entry.status]}</Badge>
                  </Td>
                  <Td>{entry.documents}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </section>
      ))}
    </div>
  );
}
```

The `style={{ width }}` here is the component's own CSS for the bar, not rendered Markdown; it never carries customer input. Run: `pnpm test -- src/features/documents/GapReport.test.tsx` → PASS.

- [ ] **Step 5: Document page — failing tests**

`frontend/src/features/documents/DocumentPage.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { customerMe, memberMe, withSession } from "@/test/session";
import { DocumentPage } from "./DocumentPage";

const DID = "33333333-3333-3333-3333-333333333333";
const PID = "11111111-1111-1111-1111-111111111111";
const fixture = {
  id: DID,
  project_id: PID,
  folder_id: "requirements",
  doc_type: "srs",
  title: "Portal SRS",
  slug: "portal-srs",
  visibility: "internal",
  current_version: 2,
  is_stub: false,
  created_by: "u1",
  created_at: "2026-10-01T10:00:00+00:00",
  updated_at: "2026-10-01T12:00:00+00:00",
  uploaded_by_name: "Owner",
  version_created_at: "2026-10-01T12:00:00+00:00",
};
const versions = [
  { version: 1, sha256: "a", original_path: "02-requirements/srs--portal-srs.docx", markdown_path: "02-requirements/srs--portal-srs.md", uploaded_by: "Editor", upload_item_id: "i1", created_at: "2026-10-01T10:00:00+00:00" },
  { version: 2, sha256: "b", original_path: "02-requirements/srs--portal-srs.docx", markdown_path: "02-requirements/srs--portal-srs.md", uploaded_by: "Owner", upload_item_id: "i2", created_at: "2026-10-01T12:00:00+00:00" },
];
const content = (version: number) => ({
  version,
  frontmatter: {
    qc_agent: 2,
    document_id: DID,
    version,
    doc_type: "srs",
    folder: "02-requirements",
    title: "Portal SRS",
    kind: "converted",
    source_file: "srs--portal-srs.docx",
    source_sha256: "b",
    uploaded_by: version === 2 ? "Owner" : "Editor",
    uploaded_at: "2026-10-01T12:00:00+00:00",
    type_selected_by_user: "srs",
    type_check: "skipped",
    language: "en",
    visibility: "internal",
    normalized_approved_by: null,
  },
  body: `## Scope v${version}\n\nThe system shall allow users to log in.\n\n<img src=x onerror="alert(1)">`,
  markdown_name: "srs--portal-srs.md",
  original_name: "srs--portal-srs.docx",
});
const project = { id: PID, slug: "demo", name: "Demo", client_name: "ACME", created_at: "x", my_role: "owner", settings: null, storage: null, llm_consent: null };

function routes(role = "owner") {
  return mockFetch([
    { path: `/api/v1/documents/${DID}`, body: fixture },
    { path: `/api/v1/documents/${DID}/versions`, body: versions },
    { path: `/api/v1/documents/${DID}/versions/2/content`, body: content(2) },
    { path: `/api/v1/documents/${DID}/versions/1/content`, body: content(1) },
    { path: `/api/v1/projects/${PID}`, body: { ...project, my_role: role } },
  ]);
}

it("renders the Markdown body through MarkdownView, the details panel and the download links", async () => {
  routes();
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  expect(await screen.findByRole("heading", { name: "Portal SRS" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "Scope v2" })).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull(); // hostile inline HTML neutralised
  expect(screen.getByRole("link", { name: "Download original" })).toHaveAttribute("href", `/api/v1/documents/${DID}/versions/2/original`);
  expect(screen.getByRole("link", { name: "Download Markdown" })).toHaveAttribute("href", `/api/v1/documents/${DID}/versions/2/markdown`);
  await userEvent.click(screen.getByText("Details"));
  const details = screen.getByText("Details").closest("details") as HTMLElement;
  expect(within(details).getByText("Software Requirements Specification")).toBeInTheDocument();
  expect(within(details).getByText("Owner")).toBeInTheDocument();
  expect(within(details).getByText("Type check skipped")).toBeInTheDocument();
  expect(within(details).getByText("en")).toBeInTheDocument();
  expect(within(details).getByText("Internal")).toBeInTheDocument();
  expect(screen.getByText(/Rendered from the converted Markdown/)).toBeInTheDocument();
});

it("lists versions and switches the content to an older one", async () => {
  routes();
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Scope v2" });
  await userEvent.click(screen.getByRole("tab", { name: "Versions" }));
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rows[1]).getByText("Current")).toBeInTheDocument();
  expect(within(rows[0]).getByText(/Editor/)).toBeInTheDocument();
  expect(within(rows[0]).getByRole("link", { name: "Download original" })).toHaveAttribute("href", `/api/v1/documents/${DID}/versions/1/original`);
  await userEvent.click(within(rows[0]).getByRole("button", { name: "View version 1" }));
  await userEvent.click(screen.getByRole("tab", { name: "Markdown" }));
  expect(await screen.findByRole("heading", { name: "Scope v1" })).toBeInTheDocument();
  expect(screen.getByText("Showing version 1")).toBeInTheDocument();
});

it("lets an editor rename and share, but not make a shared document internal", async () => {
  const f = routes("editor");
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Portal SRS" });
  await userEvent.click(screen.getByRole("button", { name: "Edit" }));
  const dialog = screen.getByRole("dialog", { name: "Edit document" });
  await userEvent.clear(within(dialog).getByLabelText("Title"));
  await userEvent.type(within(dialog).getByLabelText("Title"), "Portal SRS v2");
  await userEvent.selectOptions(within(dialog).getByLabelText("Visibility"), "shared");
  f.fn.mockImplementationOnce(async () =>
    new Response(JSON.stringify({ ...fixture, title: "Portal SRS v2", visibility: "shared" }), { status: 200, headers: { "content-type": "application/json" } }),
  );
  await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("heading", { name: "Portal SRS v2" })).toBeInTheDocument();
  expect(screen.getByText("Shared")).toBeInTheDocument();
  // mockImplementationOnce bypassed the recorder, so read the Request from the mock's own calls
  const patch = f.fn.mock.calls
    .map(([input]) => input)
    .find((input): input is Request => input instanceof Request && input.method === "PATCH");
  expect(patch && JSON.parse(await patch.text())).toEqual({ title: "Portal SRS v2", visibility: "shared" });
  await userEvent.click(screen.getByRole("button", { name: "Edit" }));
  const again = screen.getByRole("dialog", { name: "Edit document" });
  expect(within(again).getByRole("option", { name: "Internal" })).toBeDisabled();
  expect(within(again).getByText("Only a project owner can make a shared document internal.")).toBeInTheDocument();
});

it("shows the not-found message for a document the user may not see", async () => {
  mockFetch([{ path: `/api/v1/documents/${DID}`, status: 404, body: { detail: "Document not found." } }]);
  render(withSession(<DocumentPage documentId={DID} />, customerMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Document not found.");
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
});

it("hides Edit from viewers and the original download from placeholders", async () => {
  mockFetch([
    { path: `/api/v1/documents/${DID}`, body: { ...fixture, is_stub: true, current_version: 1, title: "Business Requirements Document", doc_type: "brd" } },
    { path: `/api/v1/documents/${DID}/versions`, body: [{ ...versions[0], original_path: null }] },
    { path: `/api/v1/documents/${DID}/versions/1/content`, body: { ...content(1), original_name: null, frontmatter: { ...content(1).frontmatter, kind: "stub" } } },
    { path: `/api/v1/projects/${PID}`, body: { ...project, my_role: "viewer" } },
  ]);
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Business Requirements Document" });
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Download original" })).not.toBeInTheDocument();
  expect(screen.getByText("Placeholders have no original file.")).toBeInTheDocument();
  expect(screen.getByText("Placeholder")).toBeInTheDocument();
});
```

Notes for the implementer: `mockFetch` matches on pathname only, so the PATCH is intercepted with `f.fn.mockImplementationOnce` (the fetch mock's `vi.fn`) because the same path serves the GET, and the request is then read from `f.fn.mock.calls`; the details panel is located through its `<summary>` text; `document.querySelector("img")` is the DOM `document` (the API fixture is named `fixture` so nothing shadows it).

Run: `pnpm test -- src/features/documents/DocumentPage.test.tsx` → FAIL (`./DocumentPage` not found).

- [ ] **Step 6: Frontmatter panel, edit dialog, document page, route**

`frontend/src/features/documents/FrontmatterPanel.tsx`:

```tsx
import { formatDateTime } from "@/lib/format";
import { m } from "@/messages";

type Frontmatter = Record<string, unknown>;

function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return m.common.none;
  return String(value);
}

/** The converted file's frontmatter (spec 5.3) as a definition list inside a <details>. The
 * document type title and the type-check label are resolved by the caller. */
export function FrontmatterPanel({ frontmatter, typeTitle }: { frontmatter: Frontmatter; typeTitle: string }) {
  const typeCheck = typeof frontmatter.type_check === "string" ? m.uploads.typeCheck[frontmatter.type_check] : null;
  const uploadedAt = typeof frontmatter.uploaded_at === "string" ? formatDateTime(frontmatter.uploaded_at) : m.common.none;
  const visibility = frontmatter.visibility === "shared" ? m.documents.shared : frontmatter.visibility === "internal" ? m.documents.internal : text(frontmatter.visibility);
  const rows: [string, string][] = [
    [m.documents.fmTitle, text(frontmatter.title)],
    [m.documents.fmType, typeTitle],
    [m.documents.fmVersion, text(frontmatter.version)],
    [m.documents.fmUploadedBy, text(frontmatter.uploaded_by)],
    [m.documents.fmUploadedAt, uploadedAt],
    [m.documents.fmTypeCheck, typeCheck ?? text(frontmatter.type_check)],
    [m.documents.fmLanguage, text(frontmatter.language)],
    [m.documents.fmVisibility, visibility],
    [m.documents.fmSource, text(frontmatter.source_file)],
    [m.documents.fmKind, text(frontmatter.kind)],
  ];
  return (
    <details className="rounded-lg border border-border bg-surface p-3 text-sm">
      <summary className="cursor-pointer font-medium">{m.documents.details}</summary>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="break-words">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
```

`frontend/src/features/documents/EditDocumentDialog.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { Document } from "./types";

type Props = { doc: Document; role: string; onClose: () => void; onSaved: (saved: Document) => void };

/** Owners change anything; editors rename and may share, never hide (spec 9, Plan 2 rules). */
export function EditDocumentDialog({ doc, role, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(doc.title);
  const [visibility, setVisibility] = useState(doc.visibility);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const editorCannotHide = role === "editor" && doc.visibility === "shared";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/documents/{document_id}", {
        params: { path: { document_id: doc.id } },
        body: { title, visibility: visibility as "internal" | "shared" },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onSaved(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={m.documents.editTitle} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <Field label={m.documents.titleField} required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
        <Select
          label={m.documents.visibilityField}
          value={visibility}
          hint={editorCannotHide ? m.documents.editorCannotHide : undefined}
          onChange={(event) => setVisibility(event.target.value)}
        >
          <option value="internal" disabled={editorCannotHide}>
            {m.documents.internal}
          </option>
          <option value="shared">{m.documents.shared}</option>
        </Select>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button type="submit" busy={busy}>
            {m.common.save}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
```

`frontend/src/features/documents/DocumentPage.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { MarkdownView } from "@/components/ui/Markdown";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tabs } from "@/components/ui/Tabs";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { EditDocumentDialog } from "./EditDocumentDialog";
import { FrontmatterPanel } from "./FrontmatterPanel";
import { canEdit, markdownUrl, originalUrl, type Document } from "./types";

const TYPE_TITLES: Record<string, string> = {
  readme: "Project README",
  "project-charter": "Project Charter",
  glossary: "Glossary",
  brd: "Business Requirements Document",
  srs: "Software Requirements Specification",
  "use-cases": "Use Cases",
  "user-stories": "User Stories",
  "architecture-c4": "Architecture (C4)",
  erd: "Entity Relationship Diagram",
  workflows: "Workflows",
  "api-spec": "API Specification",
  "repo-structure": "Repository Structure",
  "coding-conventions": "Coding Conventions",
  adr: "Architecture Decision Record",
  "test-plan": "Test Plan",
  "test-cases": "Test Cases",
  "test-report": "Test Report",
  "deploy-guide": "Deployment Guide",
  runbook: "Runbook",
  "release-notes": "Release Notes",
};

function typeTitle(key: string): string {
  return TYPE_TITLES[key] ?? (key.endsWith("/other") ? "Other" : key);
}

export function DocumentPage({ documentId }: { documentId: string }) {
  const [override, setOverride] = useState<Document | null>(null);
  const [editing, setEditing] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [tab, setTab] = useState("markdown");
  const loaded = useLoad(
    () =>
      api
        .GET("/api/v1/documents/{document_id}", { params: { path: { document_id: documentId } } })
        .then((r) => unwrap(r, m.documents.notFound)),
    [documentId],
  );
  const doc = override ?? loaded.data;
  const project = useLoad(
    () =>
      doc
        ? api
            .GET("/api/v1/projects/{project_id}", { params: { path: { project_id: doc.project_id } } })
            .then((r) => unwrap(r, m.projects.notFound))
        : Promise.resolve(null),
    [doc?.project_id],
  );
  const versions = useLoad(
    () =>
      doc
        ? api
            .GET("/api/v1/documents/{document_id}/versions", { params: { path: { document_id: documentId } } })
            .then((r) => unwrap(r))
        : Promise.resolve(null),
    [documentId, doc?.current_version],
  );
  const version = selectedVersion ?? doc?.current_version ?? null;
  const content = useLoad(
    () =>
      doc && version !== null
        ? api
            .GET("/api/v1/documents/{document_id}/versions/{version}/content", {
              params: { path: { document_id: documentId, version } },
            })
            .then((r) => unwrap(r))
        : Promise.resolve(null),
    [documentId, version, doc !== undefined],
  );

  if (loaded.error) return <Alert kind="error">{loaded.error}</Alert>;
  if (!doc) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  const role = project.data?.my_role ?? "";
  const editable = canEdit(role) && !doc.is_stub;
  const isCurrent = version === doc.current_version;
  const original = content.data?.original_name;

  return (
    <>
      <PageHeader
        title={doc.title}
        actions={
          <>
            <Link href={`/projects/${doc.project_id}`} className="inline-flex min-h-10 items-center text-sm text-brand underline">
              {m.uploads.backToProject}
            </Link>
            {editable ? <Button variant="secondary" onClick={() => setEditing(true)}>{m.common.edit}</Button> : null}
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Badge>{typeTitle(doc.doc_type)}</Badge>
        {doc.is_stub ? <Badge tone="warning">{m.documents.stub}</Badge> : <Badge>{m.documents.version(doc.current_version)}</Badge>}
        <Badge tone={doc.visibility === "shared" ? "success" : "neutral"}>
          {doc.visibility === "shared" ? m.documents.shared : m.documents.internal}
        </Badge>
        {version !== null && !isCurrent ? <Badge tone="warning">{m.documents.showing(version)}</Badge> : null}
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          <Tabs
            label={doc.title}
            value={tab}
            onChange={setTab}
            items={[
              {
                id: "markdown",
                label: m.documents.tabMarkdown,
                render: () =>
                  content.error ? (
                    <Alert kind="error">{content.error}</Alert>
                  ) : !content.data ? (
                    <p role="status" className="text-muted">
                      {m.app.loading}
                    </p>
                  ) : (
                    <>
                      <p className="mb-3 text-xs text-muted">{m.documents.renderedNote}</p>
                      <MarkdownView markdown={content.data.body} />
                    </>
                  ),
              },
              {
                id: "versions",
                label: m.documents.tabVersions,
                render: () =>
                  versions.error ? (
                    <Alert kind="error">{versions.error}</Alert>
                  ) : !versions.data ? (
                    <p role="status" className="text-muted">
                      {m.app.loading}
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {versions.data.map((v) => (
                        <li key={v.version} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3 text-sm">
                          <div>
                            <p className="font-medium">
                              {m.documents.versionLabel(v.version)}{" "}
                              {v.version === doc.current_version ? <Badge tone="success">{m.documents.current}</Badge> : null}
                            </p>
                            <p className="text-xs text-muted">
                              {v.uploaded_by} · {formatDateTime(v.created_at)}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-3">
                            {v.version !== version ? (
                              <Button variant="secondary" onClick={() => setSelectedVersion(v.version)}>
                                {m.documents.viewVersion(v.version)}
                              </Button>
                            ) : null}
                            {v.original_path ? (
                              <a href={originalUrl(documentId, v.version)} download className="inline-flex min-h-10 items-center text-brand underline">
                                {m.documents.downloadOriginal}
                              </a>
                            ) : null}
                            <a href={markdownUrl(documentId, v.version)} download className="inline-flex min-h-10 items-center text-brand underline">
                              {m.documents.downloadMarkdown}
                            </a>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ),
              },
            ]}
          />
        </div>
        <aside className="space-y-3">
          <div className="flex flex-col gap-2 text-sm">
            {version !== null && original ? (
              <a href={originalUrl(documentId, version)} download className="inline-flex min-h-10 items-center text-brand underline">
                {m.documents.downloadOriginal}
              </a>
            ) : null}
            {doc.is_stub ? <p className="text-muted">{m.documents.noOriginal}</p> : null}
            {version !== null ? (
              <a href={markdownUrl(documentId, version)} download className="inline-flex min-h-10 items-center text-brand underline">
                {m.documents.downloadMarkdown}
              </a>
            ) : null}
          </div>
          {content.data ? <FrontmatterPanel frontmatter={content.data.frontmatter} typeTitle={typeTitle(doc.doc_type)} /> : null}
        </aside>
      </div>
      {editing ? (
        <EditDocumentDialog
          doc={doc}
          role={role}
          onClose={() => setEditing(false)}
          onSaved={(saved) => {
            setOverride(saved);
            setEditing(false);
          }}
        />
      ) : null}
    </>
  );
}
```

Two download links for the current version appear on the page (aside and Versions tab); the tests query the aside's by role+name while the Markdown tab is active, and the Versions tab's within its row. The type titles are duplicated from the taxonomy on purpose: the document page should not need a second request to label one badge; `GET /taxonomy` stays the source for pickers.

Route — `frontend/src/app/(app)/documents/[documentId]/page.tsx`:

```tsx
import { DocumentPage } from "@/features/documents/DocumentPage";

export default async function Page({ params }: PageProps<"/documents/[documentId]">) {
  const { documentId } = await params;
  return <DocumentPage documentId={documentId} />;
}
```

Run: `pnpm typecheck && pnpm test -- src/features/documents` → PASS.

- [ ] **Step 7: Project page tabs — update the test, then the page**

Replace `frontend/src/features/projects/ProjectPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { customerMe, memberMe, withSession } from "@/test/session";
import { ProjectPage } from "./ProjectPage";

const PID = "11111111-1111-1111-1111-111111111111";
const base = {
  id: PID,
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: "owner",
  settings: { model: "claude-opus-5", check_budget_usd: 1, normalize_budget_usd: 2 },
  storage: { connection_id: "c1", connection_name: "Archive", type: "localfs", root: "demo" },
  llm_consent: null,
};
const taxonomy = { version: 1, folders: [] };

it("lands on Documents, shows storage on Overview to internal roles and lets an owner record the consent", async () => {
  const consent = { confirmed_by_name: "Customer Rep", confirmed_at: "2026-10-01T11:00:00+00:00" };
  let recorded = false; // the page reloads the project after recording
  const f = mockFetch([
    { path: `/api/v1/projects/${PID}`, handler: () => ({ ...base, llm_consent: recorded ? consent : null }) },
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
    {
      method: "POST",
      path: `/api/v1/projects/${PID}/llm-consent`,
      status: 201,
      handler: () => {
        recorded = true;
        return consent;
      },
    },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  expect(await screen.findByRole("heading", { name: "Demo" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Documents" })).toHaveAttribute("aria-selected", "true");
  expect(await screen.findByText("No documents match these filters.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload documents" })).toHaveAttribute("href", `/projects/${PID}/upload`);
  for (const name of ["Overview", "Gap report", "Members", "Settings"]) {
    expect(screen.getByRole("tab", { name })).toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("tab", { name: "Overview" }));
  expect(screen.getByText("Archive")).toBeInTheDocument();
  expect(screen.getByText("Local filesystem")).toBeInTheDocument();
  expect(screen.queryByText("localfs")).toBeNull();
  expect(screen.getByText("demo")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Name of the confirming person"), "Customer Rep");
  await userEvent.click(screen.getByRole("button", { name: "Record customer confirmation" }));
  expect(await screen.findByText(/Confirmed by Customer Rep on/)).toBeInTheDocument();
  const consentCall = f.calls.find((c) => c.method === "POST");
  expect(consentCall && JSON.parse(await consentCall.clone().text())).toEqual({ confirmed_by_name: "Customer Rep" });
});

it("hides storage, gap report, members and settings from clients", async () => {
  mockFetch([
    { path: `/api/v1/projects/${PID}`, body: { ...base, my_role: "client", settings: null, storage: null } },
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, customerMe).element);
  expect(await screen.findByRole("heading", { name: "Demo" })).toBeInTheDocument();
  for (const name of ["Gap report", "Members", "Settings"]) {
    expect(screen.queryByRole("tab", { name })).not.toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("tab", { name: "Overview" }));
  expect(screen.queryByText("Archive")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Name of the confirming person")).not.toBeInTheDocument();
  expect(screen.getByText(/Not confirmed yet/)).toBeInTheDocument();
});

it("shows the gap report tab to viewers but no settings", async () => {
  mockFetch([
    { path: `/api/v1/projects/${PID}`, body: { ...base, my_role: "viewer" } },
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Demo" });
  expect(screen.getByRole("tab", { name: "Gap report" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Members" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Settings" })).not.toBeInTheDocument();
});

it("reports an unknown project", async () => {
  mockFetch([{ path: `/api/v1/projects/${PID}`, status: 404, body: { detail: "Project not found." } }]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Project not found.");
});
```

Run: `pnpm test -- src/features/projects/ProjectPage.test.tsx` → FAIL (no "Documents" tab).

Replace the tab section of `frontend/src/features/projects/ProjectPage.tsx`: import `Tabs` from `@/components/ui/Tabs`, `DocumentBrowser` from `@/features/documents/DocumentBrowser`, `GapReport` from `@/features/documents/GapReport`; remove the `cx` import and the local `Tab` type; replace `const [tab, setTab] = useState<Tab>("overview");` with `const [tab, setTab] = useState("documents");`; delete the hand-rolled `role="tablist"` block and the three `{tab === "…" ? … : null}` blocks, and render instead:

```tsx
      <Tabs
        label={project.name}
        value={tab}
        onChange={setTab}
        items={[
          {
            id: "documents",
            label: m.documents.title,
            render: () => <DocumentBrowser projectId={project.id} role={project.my_role} />,
          },
          { id: "overview", label: m.projects.overview, render: () => overview },
          ...(internal
            ? [{ id: "gaps", label: m.gaps.title, render: () => <GapReport projectId={project.id} /> }]
            : []),
          ...(internal
            ? [{ id: "members", label: m.projects.members, render: () => <MembersPanel projectId={project.id} canEdit={owner} /> }]
            : []),
          ...(owner
            ? [{ id: "settings", label: m.projects.settings, render: () => <SettingsPanel project={project} onUpdated={setOverride} /> }]
            : []),
        ]}
      />
```

where `overview` is the existing `<dl className="grid gap-4 sm:grid-cols-2">…</dl>` block assigned to a `const overview = (…)` above the `return`. Delete the now-unused `tabs` array.

Run: `pnpm test -- src/features/projects` → PASS.

- [ ] **Step 8: Keep the end-to-end suite green**

In `frontend/e2e/first-run.spec.ts`, in the step `owner creates a project on that connection and records the consent`, insert `await page.getByRole("tab", { name: "Overview" }).click();` directly after `await expect(page.getByRole("heading", { name: "E2E Project" })).toBeVisible();` (the storage facts and the consent form now live on the Overview tab). The Members step already clicks its tab.

Run: `pnpm format:write && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build && pnpm e2e`
Expected: PASS (the Playwright suite needs PostgreSQL on 5434 and `uv` as in Plan 3a).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/documents "frontend/src/app/(app)/documents/[documentId]/page.tsx" frontend/src/features/projects/ProjectPage.tsx frontend/src/features/projects/ProjectPage.test.tsx frontend/e2e/first-run.spec.ts
git commit -m "feat(frontend): document browser, document page with sanitised Markdown and versions, gap report, project tabs"
```

### Task 7: My tasks and the type-confirmation dialog

**Files:**
- Create: `frontend/src/features/tasks/TasksPage.tsx`, `frontend/src/features/tasks/TasksPage.test.tsx`, `frontend/src/features/tasks/ConfirmTypeDialog.tsx`, `frontend/src/features/tasks/ConfirmTypeDialog.test.tsx`, `frontend/src/app/(app)/tasks/page.tsx`
- Modify: `frontend/src/components/shell/AppShell.tsx` (one navigation link), `frontend/src/components/shell/AppShell.test.tsx` (one assertion)

**Interfaces:**
- Consumes: `api`, `unwrap`, `apiErrorMessage`, `useLoad`, `Dialog`, `Select`, `Button`, `Alert`, `Badge`, `StatusBadge`, `TypeOptions`, `formatDateTime`, `m` (Task 4); backend `GET /me/tasks`, `GET /taxonomy`, `POST /upload-items/{id}/confirm-type` (Plan 2).
- Produces: route `/tasks`; `TasksPage()`, `ConfirmTypeDialog({ task, taxonomy, onClose, onConfirmed })`; the "My tasks" link in the shell. Labels: "My tasks", "Review", dialog "Confirm the document type", buttons "Keep selected type" / "Change type" / "Use the suggested type".

- [ ] **Step 1: Failing tests**

`frontend/src/features/tasks/ConfirmTypeDialog.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { ConfirmTypeDialog } from "./ConfirmTypeDialog";

const taxonomy = {
  version: 1,
  folders: [
    {
      id: "requirements",
      dir: "02-requirements",
      stage: "What",
      doc_types: [{ key: "srs", id: "srs", title: "Software Requirements Specification", required: true, normalize: true, multi: false }],
    },
    {
      id: "testing",
      dir: "05-testing",
      stage: "Verify",
      doc_types: [{ key: "test-plan", id: "test-plan", title: "Test Plan", required: true, normalize: true, multi: false }],
    },
  ],
};
const item = (overrides: Record<string, unknown> = {}) => ({
  id: "i1",
  upload_id: "u1",
  original_name: "plan.docx",
  ext: "docx",
  size: 10,
  sha256: "x",
  selected_doc_type: "srs",
  final_doc_type: null,
  title: "Plan",
  intent: "new",
  target_document_id: null,
  visibility: "internal",
  status: "needs_confirmation",
  type_check: null,
  check_explanation: "Reads like a test plan: scope, entry criteria, schedule.",
  suggested_doc_type: "test-plan",
  version_hint_document_id: null,
  warnings: [],
  conversion_meta: {},
  error: null,
  document_id: null,
  created_at: "2026-10-02T09:00:00+00:00",
  updated_at: "2026-10-02T09:05:00+00:00",
  ...overrides,
});
const task = (overrides: Record<string, unknown> = {}) => ({ item: item(overrides), project_id: "p1", project_name: "Demo" });

it("shows the selected type, the explanation and the suggestion, and changes the type", async () => {
  const f = mockFetch([
    { method: "POST", path: "/api/v1/upload-items/i1/confirm-type", body: item({ status: "publishing", final_doc_type: "test-plan" }) },
  ]);
  const onConfirmed = vi.fn();
  render(<ConfirmTypeDialog task={task()} taxonomy={taxonomy} onClose={vi.fn()} onConfirmed={onConfirmed} />);
  const dialog = screen.getByRole("dialog", { name: "Confirm the document type" });
  // each title appears twice: as the "You selected" / "Suggested type" value and as a <select> option
  expect(within(dialog).getAllByText("Software Requirements Specification")).toHaveLength(2);
  expect(within(dialog).getByText("Reads like a test plan: scope, entry criteria, schedule.")).toBeInTheDocument();
  expect(within(dialog).getAllByText("Test Plan")).toHaveLength(2);
  expect(within(dialog).getByLabelText("Document type to publish with")).toHaveValue("test-plan"); // suggestion preselected
  await userEvent.click(within(dialog).getByRole("button", { name: "Change type" }));
  expect(await f.body(0)).toEqual({ doc_type: "test-plan" });
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});

it("keeps the selected type with one click", async () => {
  const f = mockFetch([
    { method: "POST", path: "/api/v1/upload-items/i1/confirm-type", body: item({ status: "publishing", final_doc_type: "srs" }) },
  ]);
  render(<ConfirmTypeDialog task={task()} taxonomy={taxonomy} onClose={vi.fn()} onConfirmed={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Keep selected type" }));
  expect(await f.body(0)).toEqual({ doc_type: "srs" });
});

it("handles an item without a verdict", () => {
  mockFetch([]);
  render(
    <ConfirmTypeDialog
      task={task({ check_explanation: null, suggested_doc_type: null })}
      taxonomy={taxonomy}
      onClose={vi.fn()}
      onConfirmed={vi.fn()}
    />,
  );
  expect(screen.getByText(/did not return a verdict/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use the suggested type" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Document type to publish with")).toHaveValue("srs");
});

it("shows the conflict message when the item is no longer waiting", async () => {
  mockFetch([
    { method: "POST", path: "/api/v1/upload-items/i1/confirm-type", status: 409, body: { detail: "This item is not waiting for a type confirmation." } },
  ]);
  const onConfirmed = vi.fn();
  render(<ConfirmTypeDialog task={task()} taxonomy={taxonomy} onClose={vi.fn()} onConfirmed={onConfirmed} />);
  await userEvent.click(screen.getByRole("button", { name: "Keep selected type" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("This item is not waiting for a type confirmation.");
  expect(onConfirmed).not.toHaveBeenCalled();
});
```

`frontend/src/features/tasks/TasksPage.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { memberMe, withSession } from "@/test/session";
import { TasksPage } from "./TasksPage";

const taxonomy = {
  version: 1,
  folders: [
    {
      id: "requirements",
      dir: "02-requirements",
      stage: "What",
      doc_types: [{ key: "srs", id: "srs", title: "Software Requirements Specification", required: true, normalize: true, multi: false }],
    },
  ],
};
const task = {
  item: {
    id: "i1",
    upload_id: "u1",
    original_name: "plan.docx",
    ext: "docx",
    size: 10,
    sha256: "x",
    selected_doc_type: "srs",
    final_doc_type: null,
    title: "Plan",
    intent: "new",
    target_document_id: null,
    visibility: "internal",
    status: "needs_confirmation",
    type_check: null,
    check_explanation: "Reads like a test plan.",
    suggested_doc_type: null,
    version_hint_document_id: null,
    warnings: [],
    conversion_meta: {},
    error: null,
    document_id: null,
    created_at: "2026-10-02T09:00:00+00:00",
    updated_at: "2026-10-02T09:05:00+00:00",
  },
  project_id: "p1",
  project_name: "Demo",
};

it("lists waiting items, opens the dialog and refreshes after a confirmation", async () => {
  let confirmed = false;
  mockFetch([
    { path: "/api/v1/me/tasks", handler: () => (confirmed ? [] : [task]) },
    { path: "/api/v1/taxonomy", body: taxonomy },
    {
      method: "POST",
      path: "/api/v1/upload-items/i1/confirm-type",
      handler: () => {
        confirmed = true;
        return { ...task.item, status: "publishing", final_doc_type: "srs" };
      },
    },
  ]);
  render(withSession(<TasksPage />, memberMe).element);
  const card = (await screen.findByText("plan.docx")).closest("li") as HTMLElement;
  expect(within(card).getByText("Demo")).toBeInTheDocument();
  expect(within(card).getByText("Needs confirmation")).toBeInTheDocument();
  await userEvent.click(within(card).getByRole("button", { name: "Review" }));
  await userEvent.click(screen.getByRole("button", { name: "Keep selected type" }));
  expect(await screen.findByText("Nothing is waiting for you.")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Type confirmed. The document is being published.");
});

it("shows the empty state", async () => {
  mockFetch([
    { path: "/api/v1/me/tasks", body: [] },
    { path: "/api/v1/taxonomy", body: taxonomy },
  ]);
  render(withSession(<TasksPage />, memberMe).element);
  expect(await screen.findByText("Nothing is waiting for you.")).toBeInTheDocument();
});
```

Append to `frontend/src/components/shell/AppShell.test.tsx`, inside the first test after the "Projects" link assertion:

```tsx
  expect(screen.getByRole("link", { name: "My tasks" })).toHaveAttribute("href", "/tasks");
```

Run: `pnpm test -- src/features/tasks src/components/shell` → FAIL (modules not found; no "My tasks" link).

- [ ] **Step 2: Dialog, page, route, navigation link**

`frontend/src/features/tasks/ConfirmTypeDialog.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { TypeOptions } from "@/components/ui/TypeOptions";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { m } from "@/messages";

export type Task = components["schemas"]["TaskOut"];
type Taxonomy = components["schemas"]["TaxonomyOut"];

type Props = { task: Task; taxonomy: Taxonomy; onClose: () => void; onConfirmed: (item: Task["item"]) => void };

export function typeTitle(taxonomy: Taxonomy, key: string | null | undefined): string {
  if (!key) return m.common.none;
  for (const folder of taxonomy.folders) {
    const found = folder.doc_types.find((t) => t.key === key);
    if (found) return found.title;
  }
  return key;
}

/** Spec screen 6: the selected type, the check's explanation and suggestion, keep or change.
 * Without a verdict (SkipAnalyzer, or a check that failed) the dialog says so and still lets
 * the user confirm or change the type. */
export function ConfirmTypeDialog({ task, taxonomy, onClose, onConfirmed }: Props) {
  const { item } = task;
  const [docType, setDocType] = useState(item.suggested_doc_type ?? item.selected_doc_type);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirm(key: string) {
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/upload-items/{item_id}/confirm-type", {
        params: { path: { item_id: item.id } },
        body: { doc_type: key },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onConfirmed(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      title={m.tasks.confirmTitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button variant="secondary" busy={busy} onClick={() => void confirm(item.selected_doc_type)}>
            {m.tasks.keep}
          </Button>
          <Button busy={busy} disabled={docType === item.selected_doc_type} onClick={() => void confirm(docType)}>
            {m.tasks.change}
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <p className="font-medium">
          {item.original_name} · {task.project_name}
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
          <dt className="text-muted">{m.tasks.selectedType}</dt>
          <dd>{typeTitle(taxonomy, item.selected_doc_type)}</dd>
          <dt className="text-muted">{m.tasks.verdict}</dt>
          <dd>{item.check_explanation ?? m.tasks.noVerdict}</dd>
          {item.suggested_doc_type ? (
            <>
              <dt className="text-muted">{m.tasks.suggested}</dt>
              <dd className="flex flex-wrap items-center gap-2">
                <span>{typeTitle(taxonomy, item.suggested_doc_type)}</span>
                <Button variant="secondary" onClick={() => setDocType(item.suggested_doc_type ?? item.selected_doc_type)}>
                  {m.tasks.useSuggested}
                </Button>
              </dd>
            </>
          ) : null}
        </dl>
        <Select label={m.tasks.chooseType} value={docType} onChange={(event) => setDocType(event.target.value)}>
          <TypeOptions taxonomy={taxonomy} />
        </Select>
      </div>
    </Dialog>
  );
}
```

`frontend/src/features/tasks/TasksPage.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { ConfirmTypeDialog, typeTitle, type Task } from "./ConfirmTypeDialog";

export function TasksPage() {
  const tasks = useLoad(() => api.GET("/api/v1/me/tasks").then((r) => unwrap(r)), []);
  const taxonomy = useLoad(() => api.GET("/api/v1/taxonomy").then((r) => unwrap(r)), []);
  const [reviewing, setReviewing] = useState<Task | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  const error = tasks.error ?? taxonomy.error;
  return (
    <>
      <PageHeader title={m.tasks.title} />
      <p className="mb-4 text-sm text-muted">{m.tasks.intro}</p>
      {confirmed ? <Alert kind="success">{m.tasks.confirmed}</Alert> : null}
      {error ? (
        <Alert kind="error">
          {error}{" "}
          <Button variant="secondary" onClick={tasks.reload}>
            {m.common.retry}
          </Button>
        </Alert>
      ) : null}
      {!tasks.data || !taxonomy.data ? (
        error ? null : (
          <p role="status" className="text-muted">
            {m.app.loading}
          </p>
        )
      ) : tasks.data.length === 0 ? (
        <p className="text-muted">{m.tasks.empty}</p>
      ) : (
        <ul className="space-y-3">
          {tasks.data.map((task) => (
            <li key={task.item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-3">
              <div className="min-w-0 text-sm">
                <p className="truncate font-medium">{task.item.original_name}</p>
                <p className="text-xs text-muted">
                  <Link href={`/projects/${task.project_id}`} className="underline">
                    {task.project_name}
                  </Link>{" "}
                  · {typeTitle(taxonomy.data, task.item.selected_doc_type)} · {m.tasks.waitingSince}{" "}
                  {formatDateTime(task.item.updated_at)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={task.item.status} />
                <Button onClick={() => setReviewing(task)}>{m.tasks.review}</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {reviewing && taxonomy.data ? (
        <ConfirmTypeDialog
          task={reviewing}
          taxonomy={taxonomy.data}
          onClose={() => setReviewing(null)}
          onConfirmed={() => {
            setReviewing(null);
            setConfirmed(true);
            tasks.reload();
          }}
        />
      ) : null}
    </>
  );
}
```

`frontend/src/app/(app)/tasks/page.tsx`:

```tsx
import { TasksPage } from "@/features/tasks/TasksPage";

export default function Page() {
  return <TasksPage />;
}
```

In `frontend/src/components/shell/AppShell.tsx`, replace the `links` initialisation with:

```tsx
  const links: NavLink[] = [
    { href: "/projects", label: m.nav.projects, match: "/projects" },
    { href: "/tasks", label: m.nav.tasks, match: "/tasks" },
  ];
```

Run: `pnpm format:write && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build`
Expected: PASS. (In the TasksPage test the success alert has `role="status"`, which `getByRole("status")` finds once the loading paragraph is gone — the empty state is a plain paragraph.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/tasks "frontend/src/app/(app)/tasks/page.tsx" frontend/src/components/shell/AppShell.tsx frontend/src/components/shell/AppShell.test.tsx
git commit -m "feat(frontend): My tasks list and type-confirmation dialog"
```

### Task 8: Playwright — upload, live progress over SSE, read, download, gap report; phone smoke test

**Files:**
- Create: `frontend/e2e/helpers.ts`, `frontend/e2e/upload-flow.spec.ts`
- Modify: `frontend/e2e/global-setup.ts` (generate the sample `.docx`), `frontend/e2e/first-run.spec.ts` (persist the TOTP secret and the new password for later specs)

**Interfaces:**
- Consumes: every screen (Tasks 4–7), the SSE endpoint (Task 3), `e2e/env.ts` (`STATE_FILE`, `backendEnv`), `otplib`'s `generate`, python-docx from the backend's uv environment (dev dependency, Plan 2).
- Produces: `e2e/.state/admin.json` now `{ email, password, totpSecret }` after `first-run.spec.ts`; `e2e/.state/sample.docx`; `signIn(page)` helper performing login + TOTP; the suite order first-run → guards → upload-flow (Playwright runs spec files in path order with `workers: 1`).

- [ ] **Step 1: Sample document and persisted credentials**

In `frontend/e2e/global-setup.ts`, add after the admin creation (same imports; add `SAMPLE_DOCX` to `e2e/env.ts`: `export const SAMPLE_DOCX = path.join(__dirname, ".state", "sample.docx");`):

```ts
  // A small synthetic .docx for the upload flow, generated by python-docx from the backend's
  // environment so nothing binary is committed and no customer content is used.
  execFileSync(
    "uv",
    [
      "run",
      "--directory",
      path.join(__dirname, "..", "..", "backend"),
      "python",
      "-c",
      [
        "import sys",
        "from docx import Document",
        "d = Document()",
        "d.add_heading('Scope', level=1)",
        "d.add_paragraph('The system shall allow users to log in with a password and a one-time code.')",
        "d.add_paragraph('The system shall keep an audit log of every upload.')",
        "d.save(sys.argv[1])",
      ].join("\n"),
      SAMPLE_DOCX,
    ],
    { encoding: "utf8", env: { ...process.env, ...backendEnv } },
  );
```

In `frontend/e2e/first-run.spec.ts`: add `import { writeFileSync } from "node:fs";` (merge with the existing `readFileSync` import), capture the TOTP secret outside the step (`let totpSecret = "";` before the test body's first step, and `totpSecret = secret;` right after `const secret = …inputValue();`), and at the end of the "forced password change" step append:

```ts
    // later spec files sign in with these (the password just changed; the authenticator secret
    // exists only in this browser session)
    writeFileSync(STATE_FILE, JSON.stringify({ email: admin.email, password: NEW_PASSWORD, totpSecret }));
```

`frontend/e2e/helpers.ts`:

```ts
import { readFileSync } from "node:fs";
import { expect, type Page } from "@playwright/test";
import { generate } from "otplib";
import { STATE_FILE } from "./env";

export type AdminState = { email: string; password: string; totpSecret: string };

export function adminState(): AdminState {
  const state = JSON.parse(readFileSync(STATE_FILE, "utf8")) as Partial<AdminState>;
  if (!state.totpSecret) throw new Error("first-run.spec.ts must run first: no TOTP secret saved");
  return state as AdminState;
}

/** Sign in as the administrator created by first-run.spec.ts: password, then a TOTP code. */
export async function signIn(page: Page): Promise<void> {
  const admin = adminState();
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(admin.email);
  await page.getByLabel("Password").fill(admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-factor authentication" })).toBeVisible();
  await page.getByLabel("Authentication or recovery code").fill(await generate({ secret: admin.totpSecret }));
  await page.getByRole("button", { name: "Verify" }).click();
  await page.waitForURL("**/projects");
}
```

(The MFA verification screen's labels come from Plan 3a: heading "Two-factor authentication", field "Authentication or recovery code", button "Verify".)

- [ ] **Step 2: The upload flow spec**

`frontend/e2e/upload-flow.spec.ts`:

```ts
import { expect, test } from "@playwright/test";
import { SAMPLE_DOCX } from "./env";
import { signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

let documentUrl = "";

test("upload with a chosen type, live progress over SSE, read, download, gap report", async ({ page }) => {
  await signIn(page);

  await test.step("open the project created by first-run on its Documents tab", async () => {
    await page.getByRole("link", { name: "E2E Project" }).click();
    await expect(page.getByRole("tab", { name: "Documents", selected: true })).toBeVisible();
    await expect(page.getByText("Placeholder").first()).toBeVisible(); // stubs for required types
  });

  await test.step("upload a .docx as an SRS", async () => {
    await page.getByRole("link", { name: "Upload documents" }).click();
    await page.getByLabel("Choose files").setInputFiles(SAMPLE_DOCX);
    const row = page.getByRole("listitem").first();
    await expect(row.getByLabel("Title")).toHaveValue("sample");
    await row.getByLabel("Title").fill("E2E SRS");
    await row.getByLabel("Document type").selectOption({ label: "Software Requirements Specification" });
    const sse = page.waitForRequest((request) => request.url().includes("/events"));
    await page.getByRole("button", { name: "Upload" }).click();
    await page.waitForURL(/\/uploads\/[0-9a-f-]{36}$/);
    await sse; // the progress page subscribed to the event stream
  });

  await test.step("watch it publish live", async () => {
    await expect(page.getByRole("heading", { name: "Upload progress" })).toBeVisible();
    await expect(page.getByText("Published")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("status", { name: "Connection" })).toHaveText("All files have been processed.");
    await page.getByRole("link", { name: "Open document" }).click();
    await page.waitForURL(/\/documents\/[0-9a-f-]{36}$/);
    documentUrl = page.url();
  });

  await test.step("read the rendered Markdown and the details", async () => {
    await expect(page.getByRole("heading", { name: "E2E SRS" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Scope" })).toBeVisible();
    await expect(page.getByText("The system shall allow users to log in with a password and a one-time code.")).toBeVisible();
    await page.getByText("Details").click();
    const details = page.getByRole("group", { name: "Details" });
    await expect(details.getByText("Software Requirements Specification")).toBeVisible();
    await expect(details.getByText("Type check skipped")).toBeVisible();
  });

  await test.step("download the original and the Markdown", async () => {
    const [original] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download original" }).first().click(),
    ]);
    expect(original.suggestedFilename()).toBe("srs--e2e-srs.docx");
    const [markdown] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download Markdown" }).first().click(),
    ]);
    expect(markdown.suggestedFilename()).toBe("srs--e2e-srs.md");
  });

  await test.step("the gap report shows the SRS present", async () => {
    await page.getByRole("link", { name: "Back to project" }).click();
    await page.getByRole("tab", { name: "Gap report" }).click();
    const table = page.getByRole("table", { name: "02-requirements (What)" });
    const srsRow = table.getByRole("row", { name: /Software Requirements Specification/ });
    await expect(srsRow.getByText("Present")).toBeVisible();
    await expect(table.getByRole("row", { name: /Business Requirements Document/ }).getByText("Placeholder")).toBeVisible();
  });

  await test.step("My tasks is empty (no mismatch with the production analyzer)", async () => {
    await page.getByRole("link", { name: "My tasks" }).click();
    await expect(page.getByText("Nothing is waiting for you.")).toBeVisible();
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("navigation collapses, the document page reads without horizontal scroll", async ({ page }) => {
    await signIn(page);
    const menu = page.getByRole("button", { name: "Open menu" });
    await expect(menu).toBeVisible();
    await expect(page.getByRole("link", { name: "My tasks" })).toBeHidden();
    await menu.click();
    await expect(page.getByRole("link", { name: "My tasks" })).toBeVisible();
    await page.getByRole("link", { name: "Projects" }).click();
    await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible(); // closed after navigating
    await page.goto(documentUrl);
    await expect(page.getByRole("heading", { name: "E2E SRS" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Markdown" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.getByRole("tab", { name: "Versions" }).click();
    await expect(page.getByText("Version 1")).toBeVisible();
  });
});
```

- [ ] **Step 3: Run the suite**

Run (from `frontend/`, PostgreSQL on 5434 running): `pnpm e2e`
Expected: `first-run.spec.ts`, `guards.spec.ts` and both `upload-flow.spec.ts` tests pass. If the "Published" badge does not appear within 30 s, inspect the Playwright trace: the backend converts the docx with markitdown (~1 s cold) and the stream must show `Converting` → `Checking type` → `Publishing` → `Published` without a reload.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/env.ts frontend/e2e/global-setup.ts frontend/e2e/first-run.spec.ts frontend/e2e/helpers.ts frontend/e2e/upload-flow.spec.ts
git commit -m "test(frontend): Playwright upload flow with live progress, document reading, downloads, gap report and a phone smoke test"
```

### Task 9: Documentation — frontend README, root README, roadmap, pending items

**Files:**
- Modify: `frontend/README.md`, `README.md`, `docs/superpowers/plans/2026-10-01-phase1-roadmap.md`, `docs/PENDING.md`

**Interfaces:**
- Consumes: the shipped behaviour of Tasks 1–8.
- Produces: documentation that matches it; the roadmap with Plan 5 before Plan 4; PENDING updated with what Plan 5 closed and what it hands on.

- [ ] **Step 1: Frontend README**

In `frontend/README.md`, replace the last paragraph (`Not yet in the UI (Plan 5): …`) with:

````markdown
## Screens

- Projects → project page with tabs **Documents** (browser grouped by the six folders, filters, placeholders for missing required types), **Overview** (storage, LLM data-processing confirmation), **Gap report** (internal roles), **Members**, **Settings**
- **Upload documents** (`/projects/<id>/upload`): drag-and-drop or picker, per-file type / title / new-or-version / visibility, "apply to all", client-side guards from `GET /upload-limits`; customer users always upload as shared
- **Upload progress** (`/uploads/<id>`): live per-file status over Server-Sent Events, polling fallback, retry for failed files
- **My tasks** (`/tasks`): files waiting for a type confirmation; the dialog shows the check's explanation and suggestion (or "no verdict" while the agent layer is not deployed)
- **Document page** (`/documents/<id>`): Markdown tab (rendered in the browser), Versions tab, downloads of the original and the Markdown per version, details panel from the frontmatter, edit title / visibility for owners and editors

Not yet in the UI: normalised-draft review (Plan 4), SharePoint / Google Drive connection forms (Plan 3b), storage change (Plan 3c).

## Live progress

The progress page opens `EventSource("/api/v1/uploads/<id>/events")`. The backend replays events after `Last-Event-ID`, sends a `: ping` every 15 s (the Next rewrite proxy closes an idle proxied response after 30 s — `experimental.proxyTimeout`), and ends the stream with `upload.settled`. The browser reconnects on its own; when it gives up (`readyState === CLOSED`) the page polls `GET /uploads/<id>` every 3 s. Multipart uploads use `XMLHttpRequest` (`src/lib/api/upload.ts`) for progress and jsdom-testability; everything else uses the typed client.

## Markdown is a security boundary

Document text comes from customer uploads. It is rendered only by `src/components/ui/Markdown.tsx` (react-markdown + remark-gfm + rehype-sanitize with the default GitHub schema; no raw HTML, no `dangerouslySetInnerHTML`). `Markdown.test.tsx` holds the hostile fixtures; keep them when touching the component.

## Responsive layout

Mobile-first Tailwind: lists are card lists, data tables scroll inside their container, dialogs are full-screen below `sm`, the navigation collapses behind a menu button below `md`, the document page becomes two columns at `lg`. `e2e/upload-flow.spec.ts` includes a 390 px smoke test.
````

Also update the `Layout` list: add `tasks`, `uploads`, `documents` to the `src/features/` line and `Tabs, Markdown, StatusBadge, TypeOptions` to the primitives line.

- [ ] **Step 2: Root README**

In `README.md`, in the section that lists what the UI offers (added by Plan 3a), add one line after the admin pages line:

```markdown
- Upload wizard with live progress (Server-Sent Events), My tasks and type confirmation, document browser with in-browser Markdown, versions and downloads, gap report (Plan 5)
```

- [ ] **Step 3: Roadmap**

In `docs/superpowers/plans/2026-10-01-phase1-roadmap.md`:

- Replace the Plan 5 row with:

```markdown
| 5 | Upload and document UI | `events` table + `GET /uploads/{id}/events` (SSE, `Last-Event-ID` replay, heartbeat, settled); upload wizard with client-side guards; live progress with polling fallback; My tasks; type confirmation; document browser, document page with sanitised in-browser Markdown, versions and downloads; gap report; responsive layout; Playwright flow | 6.1, 6.2, 10 (`events`), 11 (SSE, `GET /me/tasks`, documents), 12 (screens 3, 4, 5, 6, 8; responsive; sanitised Markdown), 14, 17 | Plan 3a merged (Plan 4 **not** required: the confirmation screen handles "no verdict") | Written: `2026-10-02-plan-5-upload-documents-ui.md` |
```

- Replace the Plan 4 row's `Delivers` cell so it starts with `Claude Agent SDK runner, …` and ends with `…, opt-in live tests, **normalised-draft review screen and "normalised" badge in the UI (moved from Plan 5)**`, and its entry criteria with `Plan 5 merged; Plan 0 agent spike; dedicated Anthropic API key (PENDING section 6)`.
- Below the table, replace the last paragraph with: `Plan 0 has no dependency on Plans 1–3a; its storage spike feeds Plan 3b and its agent spike feeds Plan 4. Plans 3b and 3c are independent of each other once Plan 3a is merged. Re-sequenced on 2026-10-02: Plan 5 runs before Plan 4 because the agent layer is blocked on an API key; Plan 4 takes the draft-review screen with it.`
- Update the header's spec reference to `(v2.2, 2026-10-02)`.

- [ ] **Step 4: Pending items**

In `docs/PENDING.md`:

- Section 4: mark `Thực thi Plan 3a` as `[x]` (merged PR #4) and append:

```markdown
- [x] Lập kế hoạch Plan 5 (upload + document UI, chạy trước Plan 4 vì chưa có API key): `docs/superpowers/plans/2026-10-02-plan-5-upload-documents-ui.md`.
- [ ] Thực thi Plan 5 (owner: Claude; review: Connor).
- [ ] Lập kế hoạch Plan 4 (agent): nhận thêm màn hình duyệt bản nháp chuẩn hóa và badge "normalised" từ Plan 5.
```

- Section 5: mark the tab-markup item (`tab trên trang dự án dùng role="tablist"…`) as `[x]` with the suffix ` — Plan 5: component Tabs (tabpanel, aria-controls, phím mũi tên).` Leave the `useLoad` 401 item and the MFA 401 item open (unchanged). Append:

```markdown
- [ ] Plan 6: Caddy phải không buffer phản hồi `text/event-stream` (`flush_interval -1` cho `/api/v1/uploads/*/events`) và giữ kết nối lâu hơn 30 giây; backend gửi `: ping` mỗi 15 giây vì rewrite proxy của Next đóng phản hồi im lặng sau 30 giây (`experimental.proxyTimeout`).
- [ ] Theo dõi: id của bảng `events` là identity, hai giao dịch có thể commit ngược thứ tự id nên một client đang stream có thể bỏ lỡ một trạng thái trung gian; client làm mới toàn bộ upload khi nhận `upload.settled` nên trạng thái cuối luôn đúng. Nếu cần tuyệt đối, chuyển sang khóa advisory theo upload khi ghi event.
- [ ] Plan 4: tiêu đề loại tài liệu trên trang tài liệu (`DocumentPage.tsx`, `TYPE_TITLES`) lặp lại taxonomy để tránh thêm một request; khi taxonomy đổi phải cập nhật cả hai.
- [ ] Plan 5 (nếu người dùng cần): tìm kiếm trong dropdown loại tài liệu hiện dựa vào type-ahead của `<select>` gốc; cân nhắc combobox có tìm kiếm nếu phản hồi người dùng yêu cầu.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/README.md README.md docs/superpowers/plans/2026-10-01-phase1-roadmap.md docs/PENDING.md
git commit -m "docs: Plan 5 screens, SSE and Markdown boundary in the READMEs; roadmap and pending items"
```

---

## Self-review (done while writing; kept so the executor sees what was checked)

- **Spec coverage.** 6.1 wizard: Task 5 (drop/picker, type grouped by folder, title, new/version with suggestion ≥ 0.8 preselected, visibility, client forced shared, apply to all, live progress, leave and come back). 6.2 states: `StatusBadge` labels every state this plan's backend emits. 10 `events`: Task 1. 11 `GET /uploads/{id}/events`, `GET /me/tasks`, documents: Tasks 3, 7, 6. 12 screens 3 (browser, document page tabs Markdown/Versions — Original preview and Normalised tabs belong to Plan 4 and are not stubbed), 4, 5, 6, 8: Tasks 6, 5, 7, 7, 6; responsive and sanitised rendering: Tasks 4 and 8. 13 authorisation on the stream: Task 3. 14 SSE disconnect → replay: Tasks 3 and 5. 17 latency: 0.5 s poll. 15 frontend tests: Vitest in every frontend task, Playwright in Task 8.
- **Scope brief items.** Backend 1–4 → Tasks 1, 3 (the naming decision is stated in "Changes from the scope brief"); frontend 5–13 → Tasks 4–8; docs 14 → Task 9. Owners and editors edit title/visibility: Task 6's `EditDocumentDialog` with the Plan 2 rules.
- **Type consistency.** `ItemStatusEvent` fields mirror `events.PAYLOAD_FIELDS` (`type_check`, `check_explanation`, `suggested_doc_type`, `final_doc_type`, `error`, `document_id`, `version`); the SSE frame names `item.status` / `upload.settled` are identical in `app/services/events.py`, `useUploadProgress.ts` and the fakes; `useUploadProgress` returns `{ upload, error, connection, reload }` and `UploadProgress` uses exactly those; `Tabs` items use `{ id, label, render }` in Tasks 4, 6; `TypeOptions` lives in `components/ui` and is imported by Tasks 5 and 7; `DocumentContentOut` fields (`version`, `frontmatter`, `body`, `markdown_name`, `original_name`) match the backend schema and the frontend fixtures; `UploadLimitsOut` matches `limits.ts`.
- **Placeholders.** None: every step carries its code; the two "write then simplify" notes were folded into the final code.
- **Review Focus** items 1–5 each name their owning test (Tasks 3/5, 5, 4/6, 6/5, 7).
