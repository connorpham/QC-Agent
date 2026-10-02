# QC-Agent frontend

Next.js 16 (App Router, TypeScript strict, Tailwind CSS v4) web application for QC-Agent.

## How it talks to the backend

The browser only calls `/api/...` on the frontend's own origin; `next.config.ts` rewrites `/api/:path*` to `BACKEND_URL` (default `http://localhost:8000`). The session is an HttpOnly cookie set by the backend; the frontend never stores tokens. `BACKEND_URL` is read when the app is **built**, so build with the value of the environment the build is for.

The typed client (`src/lib/api/client.ts`, openapi-fetch) uses types generated from `openapi.json` (exported by the backend). Every non-GET request carries the CSRF header `X-QC-Agent: 1`; a 401 outside `/auth/*` sends the user to `/login`.

```bash
pnpm api:generate   # regenerate src/lib/api/schema.d.ts from openapi.json
pnpm api:check      # fail when the generated file is stale (CI)
```

## Layout

- `src/app/(auth)/` — login, MFA, change password (no shell)
- `src/app/(app)/` — signed-in area: `SessionProvider` (route guard) + `AppShell`; `admin/` is admin-only
- `src/features/` — screen components by area (`auth`, `projects`, `admin`, `tasks`, `uploads`, `documents`)
- `src/components/ui/` — primitives (Button, Field, Select, Checkbox, Dialog, Alert, Badge, Table, PageHeader, Tabs, Markdown, StatusBadge, TypeOptions)
- `src/lib/` — API client, session, hooks
- `src/messages.ts` — every UI string
- `e2e/` — Playwright suite (real backend, disposable database)

## Commands

```bash
pnpm dev                 # http://localhost:3000
pnpm test                # Vitest + Testing Library (jsdom)
pnpm lint && pnpm format && pnpm typecheck && pnpm build
pnpm e2e                 # build for the e2e ports (8001/3001) and run Playwright
```

The end-to-end suite starts the backend itself (`e2e/backend.sh`: recreates `qc_agent_e2e`, migrates, runs uvicorn on 8001) and `next start -p 3001`; override the database with `QC_E2E_DATABASE_URL`. Browsers: `pnpm exec playwright install chromium` once.

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
