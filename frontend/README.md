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
- `src/features/` — screen components by area (`auth`, `projects`, `admin`)
- `src/components/ui/` — primitives (Button, Field, Select, Checkbox, Dialog, Alert, Badge, Table, PageHeader)
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

Not yet in the UI (Plan 5): upload wizard, document browser, type confirmation, draft review, gap report, My tasks.
