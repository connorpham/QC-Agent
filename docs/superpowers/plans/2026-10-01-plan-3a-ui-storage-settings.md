# Plan 3a — UI Shell and Storage Settings: Storage Connections, Project Binding, Next.js Frontend Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Administrators configure storage connections in the web UI, project owners choose a connection and root folder when creating a project, and a new Next.js frontend delivers sign-in with MFA and forced password change, the application shell, projects (list, create, overview, members, settings, LLM consent) and the admin pages for users and storage — with unit tests, a Playwright end-to-end suite against the real backend and PostgreSQL, and CI for both halves.

**Architecture:** The backend gains a `storage_connections` table (type, name, non-secret JSONB config, Fernet-encrypted write-only secret, exactly one default enforced by a partial unique index), rebinds `projects.storage` to `{"connection_id", "root"}` with a data migration, resolves storage adapters through the connection row (`app/storage/select.py`), exposes admin endpoints plus a non-admin "available connections" list, and exports its OpenAPI document into `frontend/openapi.json`. The frontend is a Next.js 16 App Router application in `frontend/` that talks to the backend same-origin through a rewrite (`/api/:path*` → `BACKEND_URL`) so the HttpOnly session cookie keeps working; a typed client is generated from `frontend/openapi.json` (openapi-typescript + openapi-fetch, with a middleware that adds the CSRF header); a client-side `SessionProvider` implements the route guards; screens are built from a few local UI primitives on Tailwind CSS v4 (native `<dialog>` for modals); Vitest + Testing Library cover components and the client, Playwright covers the first-run flow end to end.

**Tech Stack:** Backend unchanged (Python 3.12, FastAPI 0.142, SQLAlchemy 2.1 asyncio, Alembic 1.20, cryptography/Fernet; no new Python dependency). Frontend: Node 24, pnpm 11, Next.js 16.3 (Turbopack), React 19.2, TypeScript 5.9 (strict), Tailwind CSS 4.3 via `@tailwindcss/postcss`, ESLint 9 with `eslint-config-next` (flat config), Prettier 3, openapi-typescript 7.13, openapi-fetch 0.17, qrcode 1.5 (+ `@types/qrcode`), Vitest 5 + jsdom 30 + `@vitejs/plugin-react` 6 + Testing Library (`react` 16, `dom` 10, `jest-dom` 7, `user-event` 14), Playwright 1.63, otplib 13 (end-to-end tests only). CI: GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` v2.1 — section 8.5 (connections and project binding; authority for storage), 8.6, 9 (roles), 10 (`storage_connections`, `projects` binding), 11 (admin `storage-connections` endpoints), 12 (screens 1, 2, 9, 10, 11; the rest is Plan 5), 13 (security), 15 (frontend tests), 16 (configuration). Scope decided with the stakeholder on 2026-10-01: Plan 3 is split into **3a** (this plan), **3b** (SharePoint and Google Drive adapters, blocked on IT test sites) and **3c** (changing a project's storage with data migration). Plans 4 (agent), 5 (upload wizard, document browser, draft review, gap report UI, My tasks), 6 (deployment) follow.

**Deferred from this plan (where it goes):** SharePoint / Google Drive adapters and their configuration forms, secret-bearing connection types, live contract tests → Plan 3b. Storage change with migration (`storage_migrations`, read-only `migrating` state) → Plan 3c. Upload wizard, document browser, type confirmation, draft review, gap report UI, My tasks, Server-Sent Events → Plan 5. `/health` per-connection checks, Docker Compose, Caddy → Plan 6.

**Changes from the scope brief (and why):**

- Secrets: the write-only `secret` field is accepted for every connection type and stored Fernet-encrypted; `localfs` simply never reads it. The brief only needed the field for later types, but accepting it generically lets the write-only mechanism (`has_secret`, never returned, encrypted at rest) be tested now instead of in Plan 3b. The UI hides the field for `localfs`.
- Added `GET /users/directory` (internal users only; id, e-mail, display name, account type of active users). The Members tab must let an owner pick users by id, and `GET /users` is admin-only; without this the owner would have to type UUIDs.
- The project root folder is one segment matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$` (no leading dot, ASCII only) and must be unique per connection; two projects must never share a folder.
- `ProjectOut.storage` becomes `{connection_id, connection_name, type, root}` (internal roles only), so the overview can show the connection without a second request.
- Route guards run in a client-side `SessionProvider` (one `GET /auth/me` per app load) rather than in `proxy.ts` (the Next 16 name for middleware): the cookie is HttpOnly and MFA / password state live only in the backend, so a server-side guard would need a backend call per navigation; the client guard is simpler and unit-testable. Non-admins on `/admin/*` get the root `not-found.tsx` through `notFound()` (verified to work from a client component).
- UI components are a handful of local primitives (Button, Field, Select, Checkbox, Dialog, Alert, Badge, Table, PageHeader) styled with Tailwind, and dialogs use the native `<dialog>` element (`showModal()` gives the focus trap and Escape handling). No component library: Plan 3a's screens are forms and tables, and a shadcn/Radix dependency set is not justified yet; Plan 5 can revisit.
- The OpenAPI drift check is two-sided: a pytest test asserts the committed `frontend/openapi.json` equals the running app's document, and `pnpm api:check` asserts `schema.d.ts` is generated from the committed JSON. The frontend CI job therefore needs no Python, and the backend job needs no Node.
- End-to-end servers listen on ports 8001 (backend) and 3001 (frontend) so the suite never collides with a developer's running `uvicorn`/`next dev`.

## Global Constraints

- Backend: Python `>=3.12,<3.13` with uv; run backend commands from `backend/`. `uv run ruff format .`, `uv run ruff check .` and `uv run mypy app` (strict) pass after every backend task. All Plan 1 and Plan 2 Global Constraints still apply: API prefix `/api/v1`, English copy, CSRF header `X-QC-Agent: 1` on every state-changing request, Annotated dependencies, services never import `app.api`, audit rows via `app.services.audit.record` (never commits), PostgreSQL 16 on `localhost:5434` with tests against `qc_agent_test` (never SQLite), no blocking I/O directly in `async def`.
- Storage connections (spec 8.5): `type` is one of `localfs`, `sharepoint`, `gdrive`; only `localfs` can be created in this plan (others → 422 "not available in this version"). Exactly one connection is the default (partial unique index `uq_storage_connections_single_default` on `is_default WHERE is_default`). Secrets are stored in `secret_enc` encrypted with `SECRET_ENCRYPTION_KEY` (Fernet via `app.core.crypto.SecretBox`), are write-only, and no API response ever contains them — only `has_secret: bool`. A `localfs` connection's `root_path` must resolve inside `LOCAL_STORAGE_ROOT` (`.` is the storage root itself). Deactivating the default connection, or one used by a non-archived project, returns 409. Connections are never deleted. Audit actions: `storage_connection.created`, `storage_connection.updated`, `storage_connection.tested`, `storage_connection.default_changed`.
- Project binding: `projects.storage = {"connection_id": "<uuid>", "root": "<segment>"}` plus `provisioned_at` once the workspace exists. The root is one path segment matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`, never a reserved name, unique per connection, and defaults to the project slug. Only internal roles see the binding (connection id, name, type, root).
- Startup: when the `storage_connections` table is empty the application creates the default `localfs` connection named `Local storage` with `root_path: "."`; migration 0003 creates the same row and rebinds existing projects to it (their `root` stays the slug, `provisioned_at` is kept).
- Frontend: Node 24 and pnpm 11 (`packageManager` pinned in `package.json`; CI uses `pnpm install --frozen-lockfile`). TypeScript `strict`. After every frontend task these pass from `frontend/`: `pnpm lint`, `pnpm format`, `pnpm typecheck`, `pnpm test`, `pnpm api:check`, `pnpm build`. Run `pnpm format:write` before committing.
- Frontend talks to the backend only same-origin through the rewrite `/api/:path*` → `BACKEND_URL` (build-time environment variable, default `http://localhost:8000`) and only through the typed client in `src/lib/api/client.ts`; every non-GET request carries `X-QC-Agent: 1`. The frontend never stores tokens (session cookie only, HttpOnly) and never writes temporary passwords, TOTP secrets, recovery codes or any API payload to `localStorage`, logs or fixtures. All UI copy is English and lives in `src/messages.ts`.
- Accessibility: every input has a `<label>`; dialogs are native `<dialog>` elements opened with `showModal()` (focus trap, Escape closes) and carry `aria-labelledby`; error messages use `role="alert"`, loading and result text `role="status"`; tables have header cells with `scope="col"`.
- Generated files `frontend/openapi.json` and `frontend/src/lib/api/schema.d.ts` are never edited by hand. Regenerate with `uv run python -m app.openapi_export ../frontend/openapi.json` (from `backend/`) and `pnpm api:generate` (from `frontend/`). On merge conflicts, regenerate instead of merging.
- Tests: no customer data; synthetic names and e-mails only (`example.com`). End-to-end tests run against a disposable database `qc_agent_e2e` recreated on every run, temporary storage and staging folders, and random per-run secrets.

## Verified third-party behaviour this plan depends on (checked on 2026-10-01 in a scratch environment)

- `pnpm dlx create-next-app@16 <dir> --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm --disable-git --yes` runs without prompts and generates: `package.json` (next 16.3.x, react 19.2.x, `eslint ^9`, `eslint-config-next`, `tailwindcss ^4`, `@tailwindcss/postcss ^4`, `typescript ^5` → 5.9.3, scripts `dev`/`build`/`start`/`lint: eslint`, `"packageManager": "pnpm@11.1.3"`), `pnpm-workspace.yaml` (`allowBuilds`), `tsconfig.json` (strict, `paths: {"@/*": ["./src/*"]}`, `moduleResolution: bundler`), `eslint.config.mjs` (flat config with `defineConfig`, `globalIgnores`, `eslint-config-next/core-web-vitals` and `/typescript`), `postcss.config.mjs`, `src/app/{layout.tsx,page.tsx,globals.css,favicon.ico}`, `public/*.svg`, `.gitignore`, `README.md`, plus `AGENTS.md` and `CLAUDE.md` which `next dev` re-creates whenever they are missing (commit them). The layout uses the global `LayoutProps<"/">` type; `PageProps<"/route/[param]">` with `const { param } = await params` type-checks and builds; `tsc --noEmit` passes on a fresh checkout before any build, and `next typegen` generates route types without a build. Fonts from `next/font/google` download at build time; this plan uses a system font stack instead.
- Next 16.3: `next build` runs TypeScript (test files included, so a type error in a test fails the build); `async rewrites()` in `next.config.ts` with `{ source: "/api/:path*", destination: \`${BACKEND_URL}/api/:path*\` }` is baked into `.next/routes-manifest.json` at **build** time (so `BACKEND_URL` must be set when building, not when starting); `next start -p <port>` works; `notFound()` from `next/navigation` called during the render of a **client** component after state loads renders the root `src/app/not-found.tsx` (without that file Next shows its default 404); `redirect()` in a server component page works for `/`; the middleware file is named `proxy.ts` in Next 16 (not used here). Through the rewrite, a POST without `X-QC-Agent` reaches the backend and gets its 403, the backend's `Set-Cookie` reaches the browser and the cookie is sent back on later `/api` calls.
- openapi-typescript 7.13.0: `pnpm exec openapi-typescript openapi.json -o src/lib/api/schema.d.ts` generates `paths`, `components` and `operations` interfaces (operation ids such as `login_api_v1_auth_login_post`, request bodies under `requestBody.content["application/json"]`, responses keyed by status); the output is byte-identical across runs, so `git diff --exit-code` is a valid drift check. FastAPI documents only the modelled status codes (200/201/204 and 422), so openapi-fetch types `error` as `HTTPValidationError`; 401/403/404/409 bodies are `{"detail": string}` at runtime and are handled through an `unknown`-typed helper.
- openapi-fetch 0.17.0: `createClient<paths>({ baseUrl, fetch, credentials })`; `client.use({ onRequest({ request }) { …; return request } }, { onResponse({ request, response }) { …; return response } })`; `client.POST("/api/v1/auth/login", { body })` and `client.GET("/api/v1/projects/{project_id}", { params: { path: { project_id } } })` return `{ data, error, response }`; a 204 or empty body yields `data: undefined` and `error: undefined`; the custom `fetch` receives a `Request` object; a relative `baseUrl` fails in Node/jsdom (undici needs an absolute URL), so the client uses `window.location.origin` in the browser and jsdom (`http://localhost:3000` by default) and a placeholder on the server.
- Vitest 5.0 + `@vitejs/plugin-react` 6.1 + jsdom 30.1 + Testing Library: config must be `vitest.config.mts` (a `.ts` config in a non-`"type": "module"` package logs an ESM warning); `environment: "jsdom"`, `setupFiles: ["./vitest.setup.ts"]` importing `@testing-library/jest-dom/vitest`; `vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push }), usePathname: () => "/x" }))` works for App Router hooks; jsdom 30 has **no** `HTMLDialogElement.showModal`/`close`, so the setup file polyfills them (set/remove the `open` attribute, dispatch `close`); `vi.stubGlobal("fetch", fn)` is honoured when the client calls `globalThis.fetch` at request time.
- `qrcode` 1.5.4 (+ `@types/qrcode` 1.5.6): `import QRCode from "qrcode"; await QRCode.toDataURL(otpauthUri, { width: 192, margin: 1 })` returns a `data:image/png;base64,…` string in Node and jsdom.
- otplib 13.5.0 is a rewrite: `import { generate } from "otplib"; await generate({ secret })` (async, base32 secret) returns the same 6-digit code as the backend's `pyotp.TOTP(secret).now()` for the same secret and time step (checked back to back). There is no `authenticator` export any more.
- Playwright 1.63.0: `webServer` accepts an array of `{ name, command, url, env, cwd, reuseExistingServer, timeout, stdout, stderr }`; servers are started **before** `globalSetup` runs (a `globalSetup` that calls the backend CLI against the migrated database works); `test.describe.configure({ mode: "serial" })` and `test.step` exist; `playwright install --with-deps chromium` installs the browser and system libraries; browsers cache under `~/.cache/ms-playwright` on Linux.
- Node 24 `randomBytes(32).toString("base64")` is a valid Fernet key for `cryptography` (44 characters, standard alphabet with padding); `randomBytes(32).toString("hex")` (64 chars) satisfies `SESSION_SECRET`'s 32-character minimum.
- PostgreSQL 16 / SQLAlchemy 2.1.1 / Alembic 1.20.0: `Index("uq_storage_connections_single_default", "is_default", unique=True, postgresql_where=text("is_default"))` in `__table_args__` is created by `metadata.create_all`, a second `is_default = true` row raises `IntegrityError`, and `compare_metadata` reports no diff against either `create_all` or a raw `CREATE UNIQUE INDEX … WHERE is_default` (so `alembic check` and `test_migrations_match_models` stay green). `op.execute(sa.text("… CAST(:id AS uuid) …").bindparams(id=str(uuid)))` and `UPDATE projects SET storage = (storage - 'type') || jsonb_build_object('connection_id', CAST(:id AS text))` work through asyncpg and keep `provisioned_at`. `Project.storage.op("->>")("connection_id") == "<uuid>"` compiles to `storage ->> 'connection_id' = …`.
- FastAPI 0.142.2: `create_app(Settings(...))` with explicit constructor values (highest priority over environment and `.env`) builds the app and `app.openapi()` without touching the database (the engine is created in the lifespan, which `app.openapi()` does not run); `json.dumps(app.openapi(), indent=2, sort_keys=True)` is identical across processes. `httpx.ASGITransport` does **not** run the lifespan, so test fixtures must create the default storage connection themselves.
- GitHub Actions release tags verified: `pnpm/action-setup@v6`, `actions/setup-node@v4`, `actions/cache@v4`, `actions/upload-artifact@v4` (existing jobs keep `actions/checkout@v4` and `astral-sh/setup-uv@v6`). `pnpm/action-setup` reads the pnpm version from `package.json`'s `packageManager` field when `version` is omitted.

## Review Focus

1. An admin entering a `localfs` root path outside `LOCAL_STORAGE_ROOT` (`/etc/qc`, `../outside`, a symlink pointing out) must be refused with 422 and nothing written → `test_localfs_root_rejects_paths_outside_the_storage_root` (Task 1) and `test_root_path_outside_allowlist_is_rejected` (Task 2).
2. Setting a new default while another admin does the same must leave exactly one default, and deactivating the default or a connection with live projects must be refused with a clear message → `test_concurrent_set_default_leaves_exactly_one_default`, `test_deactivation_rules` (Task 2).
3. Two projects created with the same custom root on one connection (or a custom root equal to another project's slug) must not share a folder → `test_duplicate_root_on_same_connection_is_rejected` (Task 3).
4. A session that expires while the user works: the next API call returns 401 and the shell must send the user to `/login` instead of showing a broken page, while a 401 from a wrong login or MFA code must **not** redirect → `test_401_outside_auth_calls_the_unauthorized_handler` and `test_401_from_auth_endpoints_does_not_redirect` (Task 6).
5. Recovery codes must be shown exactly once and the user cannot continue without acknowledging them → `test_continue_is_disabled_until_the_codes_are_acknowledged` (Task 7); a temporary password is shown once and only in a dialog the admin closes → `test_create_user_shows_the_temporary_password_once` (Task 9).

---

## File Structure

```
QC-Agent/
├── .github/workflows/ci.yml                     # + frontend and e2e jobs (Task 11)
├── .pre-commit-config.yaml                      # + frontend lint/format hook (Task 11)
├── README.md                                    # running backend + frontend (Task 11)
├── docs/PENDING.md, docs/superpowers/plans/2026-10-01-phase1-roadmap.md   # 3a/3b/3c split (Task 11)
├── backend/
│   ├── app/
│   │   ├── main.py                              # lifespan ensures the default connection (T1); storage router (T2)
│   │   ├── openapi_export.py                    # python -m app.openapi_export <path> (T4)
│   │   ├── db/models/storage.py                 # StorageConnection, STORAGE_TYPES (T1)
│   │   ├── db/models/__init__.py                # exports (T1)
│   │   ├── storage/base.py                      # + validate_root_segment (T1)
│   │   ├── storage/select.py                    # storage_binding, localfs_root, connection_backend, backend_for, project_backend (T1)
│   │   ├── services/storage_connections.py      # defaults + lookups (T1); create/update/set_default/test rules (T2)
│   │   ├── services/projects.py                 # create_project(connection_id, root) (T1); root uniqueness (T3)
│   │   ├── services/pipeline.py                 # project_backend (T1)
│   │   ├── api/routes/documents.py              # project_backend (T1)
│   │   ├── api/routes/projects.py               # storage_out with connection (T1); create fields (T3)
│   │   ├── api/routes/users.py                  # GET /users/directory (T3)
│   │   ├── api/routes/storage_connections.py    # admin + available endpoints (T2)
│   │   ├── schemas/storage.py (T2), schemas/projects.py (T1, T3), schemas/users.py (T3)
│   ├── migrations/versions/0003_storage_connections.py (T1)
│   └── tests/
│       ├── conftest.py, factories.py            # default connection per test, make_connection, make_project(connection_id, root) (T1)
│       ├── db/test_models.py, db/test_migrations.py (T1)
│       ├── storage/test_select.py (T1), services/__init__.py, services/test_storage_connections.py (T1)
│       ├── api/test_consent.py (T1), api/test_storage_connections.py (T2), api/test_projects.py, api/test_users.py (T3)
│       └── api/test_openapi_export.py (T4)
└── frontend/
    ├── package.json, pnpm-lock.yaml, pnpm-workspace.yaml, tsconfig.json, next.config.ts, postcss.config.mjs,
    │   eslint.config.mjs, .prettierrc, .prettierignore, vitest.config.mts, vitest.setup.ts, .gitignore,
    │   README.md, AGENTS.md, CLAUDE.md             # T5 (README finalised in T11)
    ├── openapi.json                              # exported by the backend (T4; refreshed after every wave)
    ├── playwright.config.ts, e2e/env.ts, e2e/backend.sh, e2e/global-setup.ts, e2e/first-run.spec.ts, e2e/guards.spec.ts   # T10
    └── src/
        ├── messages.ts                           # every UI string (T5)
        ├── test/fetch-mock.ts, test/session.tsx   # test helpers (T5, T6)
        ├── lib/cx.ts (T5)
        ├── lib/api/schema.d.ts (generated), lib/api/client.ts, lib/api/errors.ts (T6)
        ├── lib/session/next-route.ts, lib/session/SessionProvider.tsx (T6)
        ├── lib/hooks/useLoad.ts (T6)
        ├── components/ui/{Button,Field,Select,Checkbox,Dialog,Alert,Badge,Table,PageHeader}.tsx (T5)
        ├── components/shell/AppShell.tsx (T6)
        ├── features/auth/{LoginForm,MfaPage,MfaEnrol,RecoveryCodes,MfaVerify,ChangePasswordPage,ChangePasswordForm}.tsx (T7)
        ├── features/projects/{ProjectsPage,CreateProjectDialog,ProjectPage,ConsentForm,MembersPanel,SettingsPanel}.tsx (T8)
        ├── features/admin/{UsersAdmin,CreateUserDialog,TemporaryPasswordDialog,StorageAdmin,ConnectionDialog}.tsx (T9)
        └── app/
            ├── layout.tsx, globals.css, page.tsx (redirect to /projects), not-found.tsx (T5)
            ├── (auth)/layout.tsx (T6), (auth)/login/page.tsx, (auth)/mfa/page.tsx, (auth)/change-password/page.tsx (T7)
            ├── (app)/layout.tsx (T6), (app)/admin/layout.tsx (T6)
            ├── (app)/projects/page.tsx, (app)/projects/[projectId]/page.tsx (T8)
            └── (app)/admin/users/page.tsx, (app)/admin/storage/page.tsx (T9)
```

## Execution waves

Tasks are written so that a wave's tasks touch disjoint files; parallel implementers work in separate worktrees and the controller merges each wave before the next starts.

| Wave | Tasks (parallel) | Shared files to watch |
|---|---|---|
| 1 | **T1** storage connections core (backend), **T4** OpenAPI export module (backend), **T5** frontend scaffold, tooling, UI kit, messages | none (T4 creates `frontend/openapi.json`; T5 creates everything else under `frontend/`) |
| 2 | **T2** storage connection API (backend), **T3** project creation with connection + root, user directory (backend), **T6** typed client, session provider, shell, guards (frontend) | T2 and T3 both re-export `frontend/openapi.json` → regenerate on merge (see below); T6 generates `schema.d.ts` from the wave-1 export |
| 3 | **T7** auth screens, **T8** projects screens, **T9** admin screens (all frontend) | `src/messages.ts` is read-only (all strings pre-defined in T5; an addition is appended at the end of the owning section); nobody edits `package.json` |
| 4 | **T10** Playwright end-to-end suite, **T11** CI jobs and documentation | none (T10 owns `playwright.config.ts`, `e2e/`, the `e2e` script; T11 owns `ci.yml`, READMEs, roadmap, PENDING) |

**Controller merge step after every wave** (on the integration branch, from the repository root):

```bash
(cd backend && uv run python -m app.openapi_export ../frontend/openapi.json)          # from wave 1 on
(cd frontend && pnpm install --frozen-lockfile && pnpm api:generate && pnpm format:write)  # from wave 2 on
git add frontend/openapi.json frontend/src/lib/api/schema.d.ts && git commit -m "chore: refresh generated OpenAPI files" || true
(cd backend && uv run pytest -q && uv run ruff check . && uv run mypy app)
(cd frontend && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build)
```

Never hand-merge `frontend/openapi.json`, `frontend/src/lib/api/schema.d.ts` or `frontend/pnpm-lock.yaml`: take either side and regenerate (`pnpm install` rewrites the lockfile). Frontend worktrees need `pnpm install --frozen-lockfile` once (node_modules is not committed) and T10 additionally `pnpm exec playwright install chromium`.

---

### Task 1: Storage connections — model, migration 0003, default connection, adapter resolution through the connection

**Files:**
- Create: `backend/app/db/models/storage.py`, `backend/migrations/versions/0003_storage_connections.py`, `backend/app/services/storage_connections.py`, `backend/tests/services/__init__.py` (empty), `backend/tests/services/test_storage_connections.py`
- Modify: `backend/app/db/models/__init__.py`, `backend/app/storage/base.py` (append), `backend/app/storage/select.py` (replace), `backend/app/services/projects.py` (imports, new error, `resolve_connection`, `create_project`), `backend/app/services/pipeline.py:35,292`, `backend/app/api/routes/documents.py:28,129`, `backend/app/api/routes/projects.py` (imports, `storage_out`, `_out`, every route that returns `ProjectOut`), `backend/app/schemas/projects.py:56-58` (`ProjectStorageOut`), `backend/app/main.py` (imports, lifespan), `backend/tests/conftest.py` (`db_sessionmaker`), `backend/tests/factories.py` (`make_connection`, `make_project`), `backend/tests/storage/test_select.py` (replace), `backend/tests/db/test_models.py` (append), `backend/tests/db/test_migrations.py` (append), `backend/tests/api/test_consent.py` (two places)
- Test: all of the above test files

**Interfaces:**
- Consumes: `Base`, `User`, `Project` (Plan 1); `LocalFsBackend`, `StorageError`, `StoragePathError`, `normalize_path` (Plan 2 Task 3); `ensure_workspace` (Plan 2 Task 6); `audit.record`, `acquire_xact_lock`.
- Produces:
  - `app.db.models.StorageConnection(id, type, name, config, secret_enc, is_default, is_active, created_by, created_at, updated_at)`; `STORAGE_TYPES = ("localfs", "sharepoint", "gdrive")`; partial unique index `uq_storage_connections_single_default`.
  - `app.storage.base`: `ROOT_SEGMENT_RE`, `ROOT_SEGMENT_MESSAGE`, `validate_root_segment(root: str) -> str` (one safe folder name; raises `StoragePathError`). `app.storage.select`: `LOCALFS`, `ROOT_OUTSIDE_MESSAGE`; `storage_binding(connection_id: uuid.UUID, root: str) -> dict[str, Any]`; `localfs_root(root_path: str, settings: Settings) -> Path` (raises `StorageError` when outside `LOCAL_STORAGE_ROOT`); `connection_backend(connection: StorageConnection, settings) -> StorageBackend` (the connection's own root, for health checks); `backend_for(connection: StorageConnection, root: str, settings) -> StorageBackend`; `async project_backend(db: AsyncSession, project: Project, settings) -> StorageBackend`.
  - `app.services.storage_connections`: `DEFAULT_CONNECTION_NAME = "Local storage"`, `DEFAULT_ROOT_PATH = "."`, `ACCEPTED_TYPES = ("localfs",)`; `async list_connections(db) -> list[StorageConnection]` (by name); `async connections_by_id(db) -> dict[uuid.UUID, StorageConnection]`; `async get_connection(db, connection_id) -> StorageConnection | None`; `async default_connection(db) -> StorageConnection | None`; `async ensure_default_connection(db) -> StorageConnection | None` (creates the default `localfs` row when the table is empty; commits; audit `storage_connection.created` with `details.system = True`).
  - `app.services.projects`: `ProjectValidationError(message)` (route → 422); `async resolve_connection(db, connection_id: uuid.UUID | None) -> StorageConnection`; `create_project(db, *, name, client_name, creator, settings, taxonomy, connection_id: uuid.UUID | None = None, root: str | None = None) -> Project` binding `storage_binding(connection.id, root or slug)`.
  - `app.schemas.projects.ProjectStorageOut(connection_id: uuid.UUID, connection_name: str, type: str, root: str)`; `app.api.routes.projects.storage_out(project, connections: Mapping[uuid.UUID, StorageConnection]) -> ProjectStorageOut | None`.
  - Lifespan calls `ensure_default_connection` right after the engine is initialised. Test fixture `db_sessionmaker` does the same after truncating. Factories: `make_connection(db, *, name="Second storage", root_path="second", type_="localfs", is_active=True) -> StorageConnection`; `make_project(..., connection_id: uuid.UUID | None = None, root: str | None = None)`.

- [ ] **Step 1: Write the failing model and migration tests**

Append to `backend/tests/db/test_models.py` (and extend its imports to `from sqlalchemy import select` and add `StorageConnection` to the `app.db.models` import list):

```python
async def test_storage_connection_defaults_and_single_default(db: AsyncSession) -> None:
    default = (await db.scalars(select(StorageConnection))).one()  # created by the fixture
    assert default.is_default is True and default.is_active is True
    assert default.secret_enc is None and default.created_by is None
    second = StorageConnection(type="localfs", name="Archive", config={"root_path": "archive"})
    db.add(second)
    await db.commit()
    assert second.is_default is False and second.is_active is True
    assert second.created_at is not None and second.updated_at is not None
    second.is_default = True  # a second default violates the partial unique index
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_storage_connection_type_is_constrained(db: AsyncSession) -> None:
    db.add(StorageConnection(type="ftp", name="Old", config={}))
    with pytest.raises(IntegrityError):
        await db.commit()
```

Append to `backend/tests/db/test_migrations.py`:

```python
async def _execute(statements: list[str]) -> None:
    engine = create_async_engine(_migtest_url(), poolclass=NullPool)
    async with engine.begin() as conn:
        for statement in statements:
            await conn.execute(text(statement))
    await engine.dispose()


async def _fetch(statement: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(_migtest_url(), poolclass=NullPool)
    async with engine.connect() as conn:
        rows = [tuple(row) for row in await conn.execute(text(statement))]
    await engine.dispose()
    return rows


OLD_BINDING = '{"type": "localfs", "root": "demo", "provisioned_at": "2026-10-01T00:00:00+00:00"}'


def test_0003_rebinds_existing_projects_to_the_default_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_recreate_database(create=True))
    try:
        monkeypatch.setenv("DATABASE_URL", _migtest_url())
        get_settings.cache_clear()
        config = Config()
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(config, "0002")
        asyncio.run(
            _execute(
                [
                    "INSERT INTO users (id, email, password_hash, display_name, account_type, "
                    "is_admin, is_active, must_change_password, mfa_enabled, recovery_codes_hash, "
                    "failed_logins) VALUES ('11111111-1111-1111-1111-111111111111', "
                    "'a@example.com', 'x', 'A', 'internal', false, true, false, false, '[]', 0)",
                    "INSERT INTO projects (id, slug, name, settings, storage, created_by) VALUES "
                    "('22222222-2222-2222-2222-222222222222', 'demo', 'Demo', '{}', "
                    f"'{OLD_BINDING}', '11111111-1111-1111-1111-111111111111')",
                ]
            )
        )
        command.upgrade(config, "head")
        connections = asyncio.run(
            _fetch("SELECT id, type, name, config, is_default, is_active FROM storage_connections")
        )
        assert len(connections) == 1
        connection_id, kind, name, config_json, is_default, is_active = connections[0]
        assert (kind, name, config_json) == ("localfs", "Local storage", {"root_path": "."})
        assert (is_default, is_active) == (True, True)
        (storage,) = asyncio.run(_fetch("SELECT storage FROM projects"))[0]
        assert storage == {
            "connection_id": str(connection_id),
            "root": "demo",
            "provisioned_at": "2026-10-01T00:00:00+00:00",
        }
        command.downgrade(config, "0002")
        (storage,) = asyncio.run(_fetch("SELECT storage FROM projects"))[0]
        assert storage == {
            "type": "localfs",
            "root": "demo",
            "provisioned_at": "2026-10-01T00:00:00+00:00",
        }
    finally:
        get_settings.cache_clear()
        asyncio.run(_recreate_database(create=False))
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/db -v`
Expected: the two model tests fail with `ImportError: cannot import name 'StorageConnection'`; the migration test fails with `alembic.util.exc.CommandError: Can't locate revision identified by '0003'` (or the schema test fails because the table is missing).

- [ ] **Step 3: Model and migration**

`backend/app/db/models/storage.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STORAGE_TYPES = ("localfs", "sharepoint", "gdrive")


class StorageConnection(Base):
    """A configured storage location projects bind to (spec 8.5). ``config`` holds the
    non-secret settings (``localfs``: ``{"root_path": ...}`` relative to LOCAL_STORAGE_ROOT);
    ``secret_enc`` the Fernet-encrypted write-only secret. Exactly one row is the default,
    enforced by the partial unique index on ``is_default``."""

    __tablename__ = "storage_connections"
    __table_args__ = (
        CheckConstraint(f"type IN ({', '.join(repr(t) for t in STORAGE_TYPES)})", name="type"),
        Index(
            "uq_storage_connections_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secret_enc: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

In `backend/app/db/models/__init__.py` add the import and export:

```python
from app.db.models.storage import STORAGE_TYPES, StorageConnection
```

and add `"STORAGE_TYPES",` (after `"PROJECT_ROLES",`) and `"StorageConnection",` (after `"ProjectMember",`) to `__all__`.

`backend/migrations/versions/0003_storage_connections.py`:

```python
"""storage connections; projects bind to a connection

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01 20:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_CONNECTION_NAME = "Local storage"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "storage_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_enc", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
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
            "type IN ('localfs', 'sharepoint', 'gdrive')", name=op.f("ck_storage_connections_type")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_storage_connections_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_connections")),
        sa.UniqueConstraint("name", name=op.f("uq_storage_connections_name")),
    )
    op.create_index(
        "uq_storage_connections_single_default",
        "storage_connections",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    # One default local connection rooted at LOCAL_STORAGE_ROOT ("."). Every existing project is
    # bound to it and keeps its root (the slug) and provisioned_at, so no file moves.
    connection_id = str(uuid.uuid4())
    op.execute(
        sa.text(
            "INSERT INTO storage_connections "
            "(id, type, name, config, secret_enc, is_default, is_active, created_by) "
            "VALUES (CAST(:id AS uuid), 'localfs', :name, CAST(:config AS jsonb), "
            "NULL, true, true, NULL)"
        ).bindparams(id=connection_id, name=DEFAULT_CONNECTION_NAME, config='{"root_path": "."}')
    )
    op.execute(
        sa.text(
            "UPDATE projects SET storage = (storage - 'type') "
            "|| jsonb_build_object('connection_id', CAST(:id AS text))"
        ).bindparams(id=connection_id)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE projects SET storage = (storage - 'connection_id') "
        "|| jsonb_build_object('type', 'localfs')"
    )
    op.drop_index("uq_storage_connections_single_default", table_name="storage_connections")
    op.drop_table("storage_connections")
```

- [ ] **Step 4: Run the model and migration tests**

Run: `uv run pytest tests/db -v`
Expected: `test_storage_connection_type_is_constrained` and `test_migrations_match_models` and `test_0003_rebinds_existing_projects_to_the_default_connection` PASS; `test_storage_connection_defaults_and_single_default` still FAILS at `.one()` (no default row yet — the fixture change comes in Step 9).

- [ ] **Step 5: Write the failing resolution tests**

Replace `backend/tests/storage/test_select.py`:

```python
"""Unit tests for app.storage.select: connection roots, project root segments and adapter
choice. No database: connections are plain model instances."""

import os
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.db.models import StorageConnection
from app.storage.base import StorageError, StoragePathError, validate_root_segment
from app.storage.localfs import LocalFsBackend
from app.storage.select import backend_for, connection_backend, localfs_root, storage_binding

VALID_SECRET = "s" * 32


def _settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        session_secret=VALID_SECRET,
        secret_encryption_key=Fernet.generate_key().decode(),
        local_storage_root=str(tmp_path / "workspace"),
    )


def _connection(root_path: str, type_: str = "localfs") -> StorageConnection:
    return StorageConnection(type=type_, name="Test", config={"root_path": root_path})


@pytest.mark.parametrize(
    ("root_path", "expected"), [(".", ""), ("archive", "archive"), ("clients/acme", "clients/acme")]
)
def test_localfs_root_resolves_inside_the_storage_root(
    tmp_path: Path, root_path: str, expected: str
) -> None:
    assert localfs_root(root_path, _settings(tmp_path)) == (
        tmp_path / "workspace" / expected
    ).resolve()


def test_localfs_root_accepts_an_absolute_path_inside_the_storage_root(tmp_path: Path) -> None:
    inside = tmp_path / "workspace" / "abs"
    assert localfs_root(str(inside), _settings(tmp_path)) == inside.resolve()


@pytest.mark.parametrize("root_path", ["..", "../outside", "/etc/qc", "archive/../../x"])
def test_localfs_root_rejects_paths_outside_the_storage_root(
    tmp_path: Path, root_path: str
) -> None:
    with pytest.raises(StorageError, match="inside LOCAL_STORAGE_ROOT"):
        localfs_root(root_path, _settings(tmp_path))


def test_localfs_root_rejects_a_symlink_pointing_outside(tmp_path: Path) -> None:
    (tmp_path / "workspace").mkdir()
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "workspace" / "link")
    with pytest.raises(StorageError, match="inside LOCAL_STORAGE_ROOT"):
        localfs_root("link", _settings(tmp_path))


@pytest.mark.parametrize("root", ["demo", "acme-2026", "a", "x.y_z", "0start", "A" * 80])
def test_valid_root_segments(root: str) -> None:
    assert validate_root_segment(root) == root


@pytest.mark.parametrize(
    "root",
    ["", ".hidden", "../x", "a/b", "/abs", "with space", "x" * 81, "dự-án", ".trash", "-dash"],
)
def test_invalid_root_segments(root: str) -> None:
    with pytest.raises(StoragePathError):
        validate_root_segment(root)


def test_backend_for_localfs_is_rooted_under_the_connection_root(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    backend = backend_for(_connection("archive"), "acme", settings)
    assert isinstance(backend, LocalFsBackend)
    assert backend.root == (tmp_path / "workspace" / "archive" / "acme").resolve()
    own = connection_backend(_connection("archive"), settings)
    assert isinstance(own, LocalFsBackend)
    assert own.root == (tmp_path / "workspace" / "archive").resolve()


def test_backend_for_rejects_bad_segments_and_unknown_types(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(StoragePathError):
        backend_for(_connection("."), "a/b", settings)
    with pytest.raises(StorageError, match="not available in this deployment"):
        backend_for(_connection(".", type_="sharepoint"), "acme", settings)
    with pytest.raises(StorageError, match="incomplete"):
        connection_backend(StorageConnection(type="localfs", name="x", config={}), settings)


def test_storage_binding_shape() -> None:
    connection_id = uuid.uuid4()
    assert storage_binding(connection_id, "demo") == {
        "connection_id": str(connection_id),
        "root": "demo",
    }
```

Run: `QC_SKIP_DB=1 uv run pytest tests/storage/test_select.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_root_segment'`.

- [ ] **Step 6: Root-segment rule in `app/storage/base.py`, replace `app/storage/select.py`**

Append to `backend/app/storage/base.py` (after `normalize_path`; `re` is already imported):

```python
ROOT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
ROOT_SEGMENT_MESSAGE = (
    "Root folder must be a single folder name of up to 80 letters, digits, '.', '_' or '-', "
    "starting with a letter or digit."
)


def validate_root_segment(root: str) -> str:
    """A project's folder inside its storage connection: one safe path segment (spec 8.5)."""
    if not ROOT_SEGMENT_RE.fullmatch(root):
        raise StoragePathError(ROOT_SEGMENT_MESSAGE)
    normalize_path(root)  # defence in depth: reserved names such as .versions and .trash
    return root
```

Replace `backend/app/storage/select.py`:

```python
"""Resolve the storage adapter for a connection and for a project's binding (spec 8.5).

A project's ``storage`` column holds ``{"connection_id": "<uuid>", "root": "<folder>"}`` plus
``provisioned_at`` once the workspace exists. The connection row supplies the adapter type and
its non-secret configuration; for ``localfs`` that is ``root_path``, which must stay inside
``LOCAL_STORAGE_ROOT`` so an administrator cannot point storage at arbitrary system folders.
"""

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Project, StorageConnection
from app.storage.base import StorageBackend, StorageError, validate_root_segment
from app.storage.localfs import LocalFsBackend

LOCALFS = "localfs"
ROOT_OUTSIDE_MESSAGE = "Storage root must be inside LOCAL_STORAGE_ROOT."


def storage_binding(connection_id: uuid.UUID, root: str) -> dict[str, Any]:
    return {"connection_id": str(connection_id), "root": root}


def localfs_root(root_path: str, settings: Settings) -> Path:
    """Absolute folder of a ``localfs`` connection. ``root_path`` is relative to
    ``LOCAL_STORAGE_ROOT`` ("." is the storage root itself); an absolute path is accepted only
    when it lies inside it. Symlinks are resolved before the check."""
    base = Path(settings.local_storage_root).resolve()
    candidate = Path(root_path)
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        raise StorageError(ROOT_OUTSIDE_MESSAGE)
    return resolved


def _localfs_connection_root(connection: StorageConnection, settings: Settings) -> Path:
    root_path = connection.config.get("root_path")
    if not isinstance(root_path, str) or not root_path:
        raise StorageError("Storage connection configuration is incomplete.")
    return localfs_root(root_path, settings)


def connection_backend(connection: StorageConnection, settings: Settings) -> StorageBackend:
    """Adapter for the connection's own root (used by "Test connection")."""
    if connection.type == LOCALFS:
        return LocalFsBackend(_localfs_connection_root(connection, settings))
    raise StorageError(f"Storage type {connection.type!r} is not available in this deployment.")


def backend_for(connection: StorageConnection, root: str, settings: Settings) -> StorageBackend:
    """Adapter for the project folder ``root`` inside the connection."""
    if connection.type == LOCALFS:
        segment = validate_root_segment(root)
        return LocalFsBackend(_localfs_connection_root(connection, settings) / segment)
    raise StorageError(f"Storage type {connection.type!r} is not available in this deployment.")


async def project_backend(db: AsyncSession, project: Project, settings: Settings) -> StorageBackend:
    """Load the project's connection row and return the adapter for its folder."""
    raw_id = project.storage.get("connection_id")
    root = project.storage.get("root")
    if not isinstance(raw_id, str) or not isinstance(root, str) or not root:
        raise StorageError("Project storage binding is incomplete.")
    try:
        connection_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise StorageError("Project storage binding is incomplete.") from exc
    connection = await db.get(StorageConnection, connection_id)
    if connection is None:
        raise StorageError("The project's storage connection no longer exists.")
    return backend_for(connection, root, settings)
```

Run: `QC_SKIP_DB=1 uv run pytest tests/storage/test_select.py -v`
Expected: 28 passed.

- [ ] **Step 7: Write the failing service tests**

Create `backend/tests/services/__init__.py` (empty) and `backend/tests/services/test_storage_connections.py`:

```python
"""Default connection at startup and project-to-adapter resolution through the connection."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, StorageConnection
from app.ingestion.taxonomy import Taxonomy
from app.services.storage_connections import (
    DEFAULT_CONNECTION_NAME,
    connections_by_id,
    default_connection,
    ensure_default_connection,
)
from app.storage.base import StorageError
from app.storage.localfs import LocalFsBackend
from app.storage.select import project_backend
from tests.factories import make_connection, make_project, make_user


async def test_ensure_default_connection_is_idempotent(db: AsyncSession) -> None:
    first = await ensure_default_connection(db)  # the fixture already created it
    second = await ensure_default_connection(db)
    assert first is not None and second is not None and first.id == second.id
    assert first.name == DEFAULT_CONNECTION_NAME and first.config == {"root_path": "."}
    assert first.type == "localfs" and first.is_default and first.is_active
    assert await db.scalar(select(func.count()).select_from(StorageConnection)) == 1
    created = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "storage_connection.created"))
    ).all()
    assert len(created) == 1 and created[0].details["system"] is True


async def test_ensure_default_connection_creates_one_when_the_table_is_empty(
    db: AsyncSession,
) -> None:
    await db.execute(delete(StorageConnection))
    await db.commit()
    created = await ensure_default_connection(db)
    assert created is not None and created.is_default is True
    assert (await default_connection(db)) is not None


async def test_project_backend_resolves_through_the_connection(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, storage_root: Path
) -> None:
    owner = await make_user(db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    project = await make_project(
        db, settings, taxonomy, owner=owner, name="Demo", connection_id=archive.id, root="acme"
    )
    backend = await project_backend(db, project, settings)
    assert isinstance(backend, LocalFsBackend)
    assert backend.root == (storage_root / "archive" / "acme").resolve()
    assert (storage_root / "archive" / "acme" / "project.yaml").exists()
    assert project.storage["connection_id"] == str(archive.id)
    assert project.storage["root"] == "acme" and "provisioned_at" in project.storage
    default = await default_connection(db)
    assert default is not None
    assert set((await connections_by_id(db)).keys()) == {archive.id, default.id}


async def test_project_backend_with_a_missing_or_broken_binding_raises(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner)
    project.storage = {**project.storage, "connection_id": str(uuid.uuid4())}
    with pytest.raises(StorageError, match="no longer exists"):
        await project_backend(db, project, settings)
    project.storage = {"root": "demo"}
    with pytest.raises(StorageError, match="incomplete"):
        await project_backend(db, project, settings)
```

Run: `uv run pytest tests/services -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.storage_connections'`.

- [ ] **Step 8: Service core**

`backend/app/services/storage_connections.py`:

```python
"""Storage connections (spec 8.5): the configured storage locations projects bind to.
Plan 3a accepts ``localfs`` only; SharePoint and Google Drive arrive with Plan 3b."""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StorageConnection
from app.services import audit

logger = logging.getLogger(__name__)

DEFAULT_CONNECTION_NAME = "Local storage"
DEFAULT_ROOT_PATH = "."
ACCEPTED_TYPES = ("localfs",)


async def list_connections(db: AsyncSession) -> list[StorageConnection]:
    rows = await db.scalars(select(StorageConnection).order_by(StorageConnection.name))
    return list(rows.all())


async def connections_by_id(db: AsyncSession) -> dict[uuid.UUID, StorageConnection]:
    return {connection.id: connection for connection in await list_connections(db)}


async def get_connection(db: AsyncSession, connection_id: uuid.UUID) -> StorageConnection | None:
    return await db.get(StorageConnection, connection_id)


async def default_connection(db: AsyncSession) -> StorageConnection | None:
    return await db.scalar(
        select(StorageConnection).where(StorageConnection.is_default.is_(True))
    )


async def ensure_default_connection(db: AsyncSession) -> StorageConnection | None:
    """Create the default local connection when no connection exists yet (first start of a
    fresh database). Commits. Returns the default, or None when connections exist but none is
    marked default (logged; the admin API keeps exactly one, so this means manual tampering)."""
    existing = await default_connection(db)
    if existing is not None:
        return existing
    if await db.scalar(select(func.count()).select_from(StorageConnection)):
        logger.error("Storage connections exist but none is the default")
        return None
    connection = StorageConnection(
        type="localfs",
        name=DEFAULT_CONNECTION_NAME,
        config={"root_path": DEFAULT_ROOT_PATH},
        is_default=True,
        is_active=True,
        created_by=None,
    )
    db.add(connection)
    try:
        await db.flush()
    except IntegrityError:  # another process created it first
        await db.rollback()
        return await default_connection(db)
    await audit.record(
        db,
        "storage_connection.created",
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"type": connection.type, "name": connection.name, "system": True},
    )
    await db.commit()
    return connection
```

- [ ] **Step 9: Fixtures and factories**

In `backend/tests/conftest.py` add the import (with the other `# noqa: E402` imports):

```python
from app.services.storage_connections import ensure_default_connection  # noqa: E402
```

and change `db_sessionmaker` so the truncation block becomes:

```python
    async with maker() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
        await ensure_default_connection(session)  # what the application lifespan does
```

In `backend/tests/factories.py` extend the models import to `from app.db.models import AuthSession, Project, ProjectMember, StorageConnection, User`, replace `make_project` and add `make_connection`:

```python
async def make_connection(
    db: AsyncSession,
    *,
    name: str = "Second storage",
    root_path: str = "second",
    type_: str = "localfs",
    is_active: bool = True,
) -> StorageConnection:
    """A non-default connection under LOCAL_STORAGE_ROOT/<root_path>; the folder is created on
    first use. Use the service's ``set_default`` to make it the default."""
    connection = StorageConnection(
        type=type_, name=name, config={"root_path": root_path}, is_active=is_active
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection


async def make_project(
    db: AsyncSession,
    settings: Settings,
    taxonomy: Taxonomy,
    *,
    owner: User,
    name: str = "Demo Project",
    client_name: str | None = "ACME",
    consent: bool = True,
    connection_id: uuid.UUID | None = None,
    root: str | None = None,
) -> Project:
    """A project with its workspace provisioned (folders, stubs, reports) on the given or
    default connection and, by default, the LLM data-processing confirmation recorded so
    uploads are allowed."""
    project = await create_project(
        db,
        name=name,
        client_name=client_name,
        creator=owner,
        settings=settings,
        taxonomy=taxonomy,
        connection_id=connection_id,
        root=root,
    )
    if consent:
        await record_consent(db, project, actor=owner, confirmed_by_name="Customer Rep")
    await db.refresh(project)
    return project
```

- [ ] **Step 10: Bind projects through the connection**

In `backend/app/services/projects.py` replace the imports block and `create_project` with:

```python
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.slugs import slugify, unique_slug
from app.db.locks import acquire_xact_lock
from app.db.models import Project, ProjectMember, StorageConnection, User
from app.ingestion.taxonomy import Taxonomy
from app.schemas.projects import MemberIn, MemberOut, ProjectSettings
from app.services import audit
from app.services.storage_connections import default_connection, get_connection
from app.services.workspace import ensure_workspace
from app.storage.base import StorageError, StoragePathError, validate_root_segment
from app.storage.select import backend_for, storage_binding


class MemberValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProjectValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def resolve_connection(
    db: AsyncSession, connection_id: uuid.UUID | None
) -> StorageConnection:
    """The connection a new project binds to: the requested one (must exist and be active) or
    the default."""
    if connection_id is None:
        connection = await default_connection(db)
        if connection is None:
            raise StorageError("No default storage connection is configured.")
        return connection
    connection = await get_connection(db, connection_id)
    if connection is None:
        raise ProjectValidationError("Storage connection not found.")
    if not connection.is_active:
        raise ProjectValidationError("Storage connection is not active.")
    return connection


async def create_project(
    db: AsyncSession,
    *,
    name: str,
    client_name: str | None,
    creator: User,
    settings: Settings,
    taxonomy: Taxonomy,
    connection_id: uuid.UUID | None = None,
    root: str | None = None,
) -> Project:
    """Create the project, bind it to a storage connection under ``root`` (default: the slug)
    and provision the workspace (folders, stubs, reports) before committing. A storage failure
    raises ``StorageError`` and nothing is committed; an unknown or inactive connection or a
    bad root raises ``ProjectValidationError``.

    Slug selection and provisioning run under a Postgres advisory transaction lock keyed by the
    base slug, so two concurrent creations of the same name are serialised instead of racing to
    provision the same storage root: the second call blocks until the first commits (or rolls
    back), then sees the first's slug as taken and gets ``<base>-2``. The lock is released
    automatically when the transaction ends.
    """
    connection = await resolve_connection(db, connection_id)
    base = slugify(name)
    await acquire_xact_lock(db, "project-slug", base)
    taken = set((await db.scalars(select(Project.slug).where(Project.slug.startswith(base)))).all())
    slug = unique_slug(base, taken)
    root_folder = root or slug
    try:
        validate_root_segment(root_folder)
    except StoragePathError as exc:
        raise ProjectValidationError(str(exc)) from exc
    project = Project(
        slug=slug,
        name=name,
        client_name=client_name,
        settings=ProjectSettings().model_dump(),
        storage=storage_binding(connection.id, root_folder),
        created_by=creator.id,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=creator.id, role="owner"))
    backend = backend_for(connection, root_folder, settings)
    await ensure_workspace(db, project=project, backend=backend, taxonomy=taxonomy, actor=creator)
    await audit.record(
        db,
        "project.create",
        user_id=creator.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"storage_connection_id": str(connection.id), "root": root_folder},
    )
    await db.commit()
    return project
```

(`list_projects_for`, `replace_members`, `list_members` stay as they are.)

In `backend/app/services/pipeline.py` change the import `from app.storage.select import backend_for` to `from app.storage.select import project_backend` and, in `publish_item_by_id`, the line `backend = backend_for(project.storage, ctx.settings)` to:

```python
            backend = await project_backend(db, project, ctx.settings)
```

In `backend/app/api/routes/documents.py` change the import to `from app.storage.select import project_backend` and, in `download_original`, `backend = backend_for(ctx.project.storage, settings)` to:

```python
        backend = await project_backend(db, ctx.project, settings)
```

In `backend/app/schemas/projects.py` replace `ProjectStorageOut`:

```python
class ProjectStorageOut(BaseModel):
    connection_id: uuid.UUID
    connection_name: str
    type: str
    root: str
```

In `backend/app/api/routes/projects.py`: add `import uuid` and `from collections.abc import Mapping` at the top, extend the models import to `from app.db.models import INTERNAL_ROLES, Project, StorageConnection`, add `from app.services import storage_connections as connections_service`, replace `_out` with:

```python
def _connection_id(project: Project) -> uuid.UUID | None:
    raw = project.storage.get("connection_id")
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def storage_out(
    project: Project, connections: Mapping[uuid.UUID, StorageConnection]
) -> ProjectStorageOut | None:
    """The binding as internal roles see it; None when the connection row is gone."""
    connection_id = _connection_id(project)
    root = project.storage.get("root")
    connection = connections.get(connection_id) if connection_id is not None else None
    if connection is None or not isinstance(root, str):
        return None
    return ProjectStorageOut(
        connection_id=connection.id,
        connection_name=connection.name,
        type=connection.type,
        root=root,
    )


def _out(
    project: Project, role: str, connections: Mapping[uuid.UUID, StorageConnection]
) -> ProjectOut:
    internal = role in INTERNAL_ROLES
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        client_name=project.client_name,
        created_at=project.created_at,
        my_role=role,
        settings=ProjectSettings(**project.settings) if internal else None,
        storage=storage_out(project, connections) if internal else None,
        llm_consent=_consent_out(project),
    )
```

and update the four routes that return `ProjectOut`:

```python
@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DbSession) -> list[ProjectOut]:
    connections = await connections_service.connections_by_id(db)
    return [
        _out(p, role, connections) for p, role in await projects_service.list_projects_for(db, user)
    ]


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
    except projects_service.ProjectValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail="Storage is unavailable; the project was not created."
        ) from exc
    await db.refresh(project)
    return _out(project, "owner", await connections_service.connections_by_id(db))


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(ctx: AnyMember, db: DbSession) -> ProjectOut:
    return _out(ctx.project, ctx.role, await connections_service.connections_by_id(db))
```

and in `update_project` replace the final `return _out(project, ctx.role)` with:

```python
    return _out(project, ctx.role, await connections_service.connections_by_id(db))
```

In `backend/app/main.py` change the session import to `from app.db.session import dispose_engine, get_sessionmaker, init_engine, is_initialised`, add `from app.services.storage_connections import ensure_default_connection`, and in the lifespan insert after the `init_engine` block:

```python
        async with get_sessionmaker()() as db:
            await ensure_default_connection(db)
```

- [ ] **Step 11: Update the consent tests to the new binding**

In `backend/tests/api/test_consent.py` add `import uuid` to the imports, replace `from app.storage.select import backend_for` with `from app.storage.select import project_backend`, replace the line `assert body["storage"] == {"type": "localfs", "root": "du-an-cong-khach-hang"}` with:

```python
    assert body["storage"]["connection_name"] == "Local storage"
    assert body["storage"]["type"] == "localfs"
    assert body["storage"]["root"] == "du-an-cong-khach-hang"
    assert uuid.UUID(body["storage"]["connection_id"])
```

and in `test_ensure_workspace_is_idempotent_and_repairs_missing_stub` replace `backend = backend_for(project.storage, settings)` with `backend = await project_backend(db, project, settings)`.

- [ ] **Step 12: Run everything**

Run: `uv run pytest -q`
Expected: all tests pass (the Plan 2 suite is unchanged in behaviour: projects created through the API or `make_project` land under `LOCAL_STORAGE_ROOT/<slug>` exactly as before because the default connection's `root_path` is `.`).

Run: `uv run alembic upgrade head && uv run alembic check && uv run ruff format . && uv run ruff check . && uv run mypy app`
Expected: `No new upgrade operations detected.`; no lint or type errors.

- [ ] **Step 13: Commit**

```bash
git add backend/app backend/migrations backend/tests
git commit -m "feat(backend): add storage connections and bind projects to a connection"
```

### Task 2: Storage connection API — admin create/update/default/test, non-admin `available`

**Files:**
- Create: `backend/app/schemas/storage.py`, `backend/app/api/routes/storage_connections.py`
- Modify: `backend/app/services/storage_connections.py` (append: errors, `validate_config`, `create_connection`, `update_connection`, `set_default`, `projects_using`, `test_connection`), `backend/app/main.py` (router import and include), `frontend/openapi.json` (re-exported)
- Test: `backend/tests/api/test_storage_connections.py`

**Interfaces:**
- Consumes: `StorageConnection`, `ensure_default_connection`, `list_connections`, `get_connection`, `default_connection`, `connection_backend`, `localfs_root`, factories `make_connection`, `make_project(connection_id=...)` (Task 1); `AdminUser`, `CurrentUser`, `Box` (`SecretBox`), `AppSettings`, `acquire_xact_lock`, `audit.record` (Plan 1/2); `app.openapi_export` (Task 4, for the re-export step).
- Produces:
  - `app.schemas.storage`: `LocalFsConfig(root_path)` (extra forbidden), `StorageConnectionCreate(type, name, config={}, secret=None, is_default=False)`, `StorageConnectionUpdate(name?, config?, secret?, is_active?, is_default?)`, `StorageConnectionOut(id, type, name, config, is_default, is_active, has_secret, created_at, updated_at)`, `StorageConnectionAvailable(id, name, type, is_default)`, `StorageTestResult(ok, detail)`.
  - `app.services.storage_connections`: `StorageConnectionError(message)` (→ 422), `StorageConnectionConflict(message)` (→ 409); `validate_config(type_, config, settings) -> dict`; `async create_connection(db, *, type_, name, config, secret, is_default, actor, box, settings) -> StorageConnection`; `async update_connection(db, connection, *, actor, box, settings, name=None, config=None, secret=None, is_active=None) -> StorageConnection`; `async set_default(db, connection, *, actor) -> None`; `async projects_using(db, connection_id) -> int` (non-archived projects); `async test_connection(db, connection, *, actor, settings) -> HealthStatus`. All commit.
  - Routes under `/api/v1/storage-connections`: `GET ""` (admin), `GET /available` (internal users; customers 403), `POST ""` (admin, 201), `PATCH /{connection_id}` (admin; `is_default: false` → 422; unknown id → 404), `POST /{connection_id}/test` (admin).

- [ ] **Step 1: Write the failing API tests**

`backend/tests/api/test_storage_connections.py`:

```python
"""Admin storage-connection API: create, update, default, deactivation rules, test; and the
``available`` list internal users read when creating a project."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.db.models import AuditLog, StorageConnection, User
from app.ingestion.taxonomy import Taxonomy
from app.services.storage_connections import set_default
from tests.factories import make_connection, make_project, make_session_token, make_user

MakeClient = Callable[..., Awaitable[AsyncClient]]
URL = "/api/v1/storage-connections"


async def _admin(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> tuple[User, AsyncClient]:
    admin = await make_user(
        db, settings, email="root@example.com", display_name="Root", is_admin=True
    )
    return admin, await make_client(await make_session_token(db, settings, admin))


async def _actions(db: AsyncSession) -> list[str]:
    return list((await db.scalars(select(AuditLog.action))).all())


async def test_non_admins_are_forbidden_and_available_is_for_internal_users(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    member = await make_user(db, settings)
    customer = await make_user(db, settings, email="c@client.com", account_type="customer")
    member_c = await make_client(await make_session_token(db, settings, member))
    customer_c = await make_client(await make_session_token(db, settings, customer))
    payload = {"type": "localfs", "name": "X", "config": {"root_path": "x"}}
    assert (await member_c.get(URL)).status_code == 403
    assert (await member_c.post(URL, json=payload)).status_code == 403
    assert (await customer_c.get(f"{URL}/available")).status_code == 403
    inactive = await make_connection(db, name="Old", root_path="old", is_active=False)
    await make_connection(db, name="Archive", root_path="archive")
    available = await member_c.get(f"{URL}/available")
    assert available.status_code == 200
    rows = available.json()
    assert [r["name"] for r in rows] == ["Local storage", "Archive"]  # default first
    assert rows[0]["is_default"] is True and rows[1]["is_default"] is False
    assert set(rows[0]) == {"id", "name", "type", "is_default"}  # no config, no secrets
    assert str(inactive.id) not in {r["id"] for r in rows}


async def test_admin_lists_the_default_connection(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    response = await admin.get(URL)
    assert response.status_code == 200
    (row,) = response.json()
    assert row["name"] == "Local storage" and row["type"] == "localfs"
    assert row["config"] == {"root_path": "."} and row["is_default"] is True
    assert row["is_active"] is True and row["has_secret"] is False
    assert "secret" not in row and "secret_enc" not in row


async def test_create_connection_and_test_it(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    _, admin = await _admin(make_client, db, settings)
    created = await admin.post(
        URL, json={"type": "localfs", "name": "  Archive  2026 ", "config": {"root_path": "archive"}}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Archive 2026" and body["is_default"] is False
    assert body["is_active"] is True and body["has_secret"] is False
    assert body["config"] == {"root_path": "archive"}
    tested = await admin.post(f"{URL}/{body['id']}/test")
    assert tested.status_code == 200
    assert tested.json() == {"ok": True, "detail": "ok"}
    assert (storage_root / "archive").is_dir()  # the health probe created the folder
    actions = await _actions(db)
    assert "storage_connection.created" in actions and "storage_connection.tested" in actions


async def test_secret_is_stored_encrypted_and_never_returned(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    created = await admin.post(
        URL,
        json={
            "type": "localfs",
            "name": "With secret",
            "config": {"root_path": "s"},
            "secret": "super-secret-value",
        },
    )
    assert created.status_code == 201 and created.json()["has_secret"] is True
    assert "super-secret-value" not in created.text
    row = await db.get(StorageConnection, uuid.UUID(created.json()["id"]))
    assert row is not None and row.secret_enc is not None
    assert "super-secret-value" not in row.secret_enc
    box = SecretBox(settings.secret_encryption_key)
    assert box.decrypt(row.secret_enc) == "super-secret-value"
    assert "super-secret-value" not in (await admin.get(URL)).text
    replaced = await admin.patch(f"{URL}/{row.id}", json={"secret": "another-value"})
    assert replaced.status_code == 200 and replaced.json()["has_secret"] is True
    await db.refresh(row)
    assert row.secret_enc is not None and box.decrypt(row.secret_enc) == "another-value"


async def test_root_path_outside_allowlist_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    _, admin = await _admin(make_client, db, settings)
    outside = ("/etc/qc", "../outside", str(storage_root.parent / "elsewhere"))
    for index, root_path in enumerate(outside):
        response = await admin.post(
            URL, json={"type": "localfs", "name": f"Bad {index}", "config": {"root_path": root_path}}
        )
        assert response.status_code == 422, root_path
        assert "inside LOCAL_STORAGE_ROOT" in response.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(StorageConnection)) == 1


async def test_validation_rules(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    cases = {
        "unsupported type": {"type": "sharepoint", "name": "SP", "config": {"site": "x"}},
        "unknown type": {"type": "ftp", "name": "F", "config": {}},
        "extra config key": {
            "type": "localfs",
            "name": "L",
            "config": {"root_path": "x", "bucket": "y"},
        },
        "missing root_path": {"type": "localfs", "name": "M", "config": {}},
        "blank name": {"type": "localfs", "name": "   ", "config": {"root_path": "x"}},
    }
    for name, payload in cases.items():
        assert (await admin.post(URL, json=payload)).status_code == 422, name
    duplicate = {"type": "localfs", "name": "Local storage", "config": {"root_path": "x"}}
    assert (await admin.post(URL, json=duplicate)).status_code == 409
    assert (await admin.patch(f"{URL}/{uuid.uuid4()}", json={"name": "Nope"})).status_code == 404


async def test_set_default_moves_the_flag(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    moved = await admin.patch(f"{URL}/{archive.id}", json={"is_default": True})
    assert moved.status_code == 200 and moved.json()["is_default"] is True
    rows = {r["name"]: r for r in (await admin.get(URL)).json()}
    assert rows["Local storage"]["is_default"] is False and rows["Archive"]["is_default"] is True
    assert "storage_connection.default_changed" in await _actions(db)
    assert (await admin.patch(f"{URL}/{archive.id}", json={"is_default": False})).status_code == 422
    inactive = await make_connection(db, name="Old", root_path="old", is_active=False)
    assert (await admin.patch(f"{URL}/{inactive.id}", json={"is_default": True})).status_code == 409
    available = (await admin.get(f"{URL}/available")).json()
    assert [r["name"] for r in available] == ["Archive", "Local storage"]


async def test_deactivation_rules(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    admin_user, admin = await _admin(make_client, db, settings)
    default_id = (await admin.get(URL)).json()[0]["id"]
    refused = await admin.patch(f"{URL}/{default_id}", json={"is_active": False})
    assert refused.status_code == 409 and "default" in refused.json()["detail"]
    archive = await make_connection(db, name="Archive", root_path="archive")
    project = await make_project(
        db, settings, taxonomy, owner=admin_user, name="On archive", connection_id=archive.id
    )
    in_use = await admin.patch(f"{URL}/{archive.id}", json={"is_active": False})
    assert in_use.status_code == 409 and "1 active project" in in_use.json()["detail"]
    assert (await admin.delete(f"/api/v1/projects/{project.id}")).status_code == 204  # archive it
    deactivated = await admin.patch(f"{URL}/{archive.id}", json={"is_active": False})
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    available_ids = {r["id"] for r in (await admin.get(f"{URL}/available")).json()}
    assert str(archive.id) not in available_ids
    reactivated = await admin.patch(f"{URL}/{archive.id}", json={"is_active": True})
    assert reactivated.status_code == 200 and reactivated.json()["is_active"] is True
    assert (await _actions(db)).count("storage_connection.updated") == 2


async def test_update_name_and_config(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin(make_client, db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    updated = await admin.patch(
        f"{URL}/{archive.id}", json={"name": "Archive 2", "config": {"root_path": "archive-2"}}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Archive 2"
    assert updated.json()["config"] == {"root_path": "archive-2"}
    taken = await admin.patch(f"{URL}/{archive.id}", json={"name": "Local storage"})
    assert taken.status_code == 409
    bad = await admin.patch(f"{URL}/{archive.id}", json={"config": {"root_path": "../x"}})
    assert bad.status_code == 422
    entry = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "storage_connection.updated"))
    ).one()
    assert entry.details == {"fields": ["config", "name"]}


async def test_concurrent_set_default_leaves_exactly_one_default(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with db_sessionmaker() as setup:
        admin = await make_user(setup, settings, email="root@example.com", is_admin=True)
        a = await make_connection(setup, name="A", root_path="a")
        b = await make_connection(setup, name="B", root_path="b")
        admin_id, a_id, b_id = admin.id, a.id, b.id
    async with db_sessionmaker() as db_a, db_sessionmaker() as db_b:
        conn_a = await db_a.get_one(StorageConnection, a_id)
        conn_b = await db_b.get_one(StorageConnection, b_id)
        actor_a = await db_a.get_one(User, admin_id)
        actor_b = await db_b.get_one(User, admin_id)
        await asyncio.gather(
            set_default(db_a, conn_a, actor=actor_a), set_default(db_b, conn_b, actor=actor_b)
        )
    async with db_sessionmaker() as check:
        defaults = (
            await check.scalars(
                select(StorageConnection).where(StorageConnection.is_default.is_(True))
            )
        ).all()
        assert len(defaults) == 1 and defaults[0].name in {"A", "B"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_storage_connections.py -v`
Expected: FAIL with `ImportError: cannot import name 'set_default'`.

- [ ] **Step 3: Schemas**

`backend/app/schemas/storage.py`:

```python
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StorageType = Literal["localfs", "sharepoint", "gdrive"]


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Connection name is required.")
    return cleaned


class LocalFsConfig(BaseModel):
    """Non-secret configuration of a ``localfs`` connection."""

    model_config = ConfigDict(extra="forbid")

    root_path: str = Field(min_length=1, max_length=500)

    @field_validator("root_path")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Root path is required.")
        return cleaned


class StorageConnectionCreate(BaseModel):
    type: StorageType
    name: str = Field(max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = Field(default=None, min_length=1, max_length=20000)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)


class StorageConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, min_length=1, max_length=20000)
    is_active: bool | None = None
    is_default: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class StorageConnectionOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    config: dict[str, Any]
    is_default: bool
    is_active: bool
    has_secret: bool
    created_at: datetime
    updated_at: datetime


class StorageConnectionAvailable(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    is_default: bool


class StorageTestResult(BaseModel):
    ok: bool
    detail: str
```

- [ ] **Step 4: Service rules**

Append to `backend/app/services/storage_connections.py` and extend its imports to:

```python
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.db.locks import acquire_xact_lock
from app.db.models import Project, StorageConnection, User
from app.schemas.storage import LocalFsConfig
from app.services import audit
from app.storage.base import HealthStatus, StorageError
from app.storage.select import connection_backend, localfs_root
```

New code (after `ensure_default_connection`):

```python
class StorageConnectionError(Exception):
    """Invalid input (route → 422)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class StorageConnectionConflict(Exception):
    """The change contradicts the current state (route → 409)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


NAME_TAKEN = "A connection with this name already exists."


def validate_config(type_: str, config: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Validate and normalise the non-secret configuration for a connection type."""
    if type_ not in ACCEPTED_TYPES:
        raise StorageConnectionError(f"Storage type {type_!r} is not available in this version.")
    try:
        parsed = LocalFsConfig.model_validate(config)
    except ValidationError as exc:
        raise StorageConnectionError("; ".join(str(e["msg"]) for e in exc.errors())) from exc
    try:
        localfs_root(parsed.root_path, settings)
    except StorageError as exc:
        raise StorageConnectionError(str(exc)) from exc
    return parsed.model_dump()


async def _name_taken(db: AsyncSession, name: str, *, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(StorageConnection.id).where(StorageConnection.name == name)
    if exclude is not None:
        stmt = stmt.where(StorageConnection.id != exclude)
    return await db.scalar(stmt) is not None


async def _move_default(db: AsyncSession, connection: StorageConnection) -> uuid.UUID | None:
    """Make ``connection`` the only default inside the current transaction and return the
    previous default's id. An advisory lock serialises concurrent changes, and the old flag is
    flushed before the new one so the partial unique index never sees two defaults."""
    await acquire_xact_lock(db, "storage-default", "all")
    previous = await default_connection(db)
    if previous is not None and previous.id != connection.id:
        previous.is_default = False
        await db.flush()
    connection.is_default = True
    await db.flush()
    return None if previous is None else previous.id


async def create_connection(
    db: AsyncSession,
    *,
    type_: str,
    name: str,
    config: dict[str, Any],
    secret: str | None,
    is_default: bool,
    actor: User,
    box: SecretBox,
    settings: Settings,
) -> StorageConnection:
    clean_config = validate_config(type_, config, settings)
    if await _name_taken(db, name):
        raise StorageConnectionConflict(NAME_TAKEN)
    connection = StorageConnection(
        type=type_,
        name=name,
        config=clean_config,
        secret_enc=box.encrypt(secret) if secret else None,
        is_default=False,
        is_active=True,
        created_by=actor.id,
    )
    db.add(connection)
    try:
        await db.flush()
    except IntegrityError as exc:  # a concurrent request took the name
        await db.rollback()
        raise StorageConnectionConflict(NAME_TAKEN) from exc
    await audit.record(
        db,
        "storage_connection.created",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"type": type_, "name": name, "has_secret": secret is not None},
    )
    if is_default:
        previous = await _move_default(db, connection)
        await audit.record(
            db,
            "storage_connection.default_changed",
            user_id=actor.id,
            target_type="storage_connection",
            target_id=str(connection.id),
            details={"previous_id": None if previous is None else str(previous)},
        )
    await db.commit()
    return connection


async def projects_using(db: AsyncSession, connection_id: uuid.UUID) -> int:
    """Non-archived projects bound to the connection."""
    count = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(
            Project.storage.op("->>")("connection_id") == str(connection_id),
            Project.archived_at.is_(None),
        )
    )
    return int(count or 0)


async def update_connection(
    db: AsyncSession,
    connection: StorageConnection,
    *,
    actor: User,
    box: SecretBox,
    settings: Settings,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    secret: str | None = None,
    is_active: bool | None = None,
) -> StorageConnection:
    changes: dict[str, Any] = {}
    if name is not None and name != connection.name:
        if await _name_taken(db, name, exclude=connection.id):
            raise StorageConnectionConflict(NAME_TAKEN)
        connection.name = name
        changes["name"] = name
    if config is not None:
        connection.config = validate_config(connection.type, config, settings)
        changes["config"] = True
    if secret is not None:
        connection.secret_enc = box.encrypt(secret)
        changes["secret"] = True
    if is_active is not None and is_active != connection.is_active:
        if not is_active:
            if connection.is_default:
                raise StorageConnectionConflict(
                    "The default connection cannot be deactivated. "
                    "Set another connection as the default first."
                )
            in_use = await projects_using(db, connection.id)
            if in_use:
                noun = "project" if in_use == 1 else "projects"
                raise StorageConnectionConflict(
                    f"This connection is used by {in_use} active {noun} and cannot be deactivated."
                )
        connection.is_active = is_active
        changes["is_active"] = is_active
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise StorageConnectionConflict(NAME_TAKEN) from exc
    await audit.record(
        db,
        "storage_connection.updated",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"fields": sorted(changes)},
    )
    await db.commit()
    return connection


async def set_default(db: AsyncSession, connection: StorageConnection, *, actor: User) -> None:
    if connection.is_default:
        return
    if not connection.is_active:
        raise StorageConnectionConflict("An inactive connection cannot be the default.")
    previous = await _move_default(db, connection)
    await audit.record(
        db,
        "storage_connection.default_changed",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"previous_id": None if previous is None else str(previous)},
    )
    await db.commit()


async def test_connection(
    db: AsyncSession, connection: StorageConnection, *, actor: User, settings: Settings
) -> HealthStatus:
    """Run the adapter's health check for the connection root; audited either way."""
    try:
        status = await connection_backend(connection, settings).health()
    except StorageError as exc:
        status = HealthStatus(ok=False, detail=str(exc))
    await audit.record(
        db,
        "storage_connection.tested",
        user_id=actor.id,
        target_type="storage_connection",
        target_id=str(connection.id),
        details={"ok": status.ok, "detail": status.detail},
    )
    await db.commit()
    return status
```

- [ ] **Step 5: Routes**

`backend/app/api/routes/storage_connections.py`:

```python
import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import AdminUser, AppSettings, Box, CurrentUser, DbSession
from app.db.models import StorageConnection
from app.schemas.storage import (
    StorageConnectionAvailable,
    StorageConnectionCreate,
    StorageConnectionOut,
    StorageConnectionUpdate,
    StorageTestResult,
)
from app.services import storage_connections as connections_service

router = APIRouter(prefix="/storage-connections", tags=["storage"])


def _out(connection: StorageConnection) -> StorageConnectionOut:
    return StorageConnectionOut(
        id=connection.id,
        type=connection.type,
        name=connection.name,
        config=connection.config,
        is_default=connection.is_default,
        is_active=connection.is_active,
        has_secret=connection.secret_enc is not None,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


async def _get(db: DbSession, connection_id: uuid.UUID) -> StorageConnection:
    connection = await connections_service.get_connection(db, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Storage connection not found.")
    return connection


@router.get("", response_model=list[StorageConnectionOut])
async def list_connections(_: AdminUser, db: DbSession) -> list[StorageConnectionOut]:
    return [_out(c) for c in await connections_service.list_connections(db)]


@router.get("/available", response_model=list[StorageConnectionAvailable])
async def available_connections(
    user: CurrentUser, db: DbSession
) -> list[StorageConnectionAvailable]:
    """Active connections an internal user may pick for a new project, default first."""
    if user.account_type != "internal":
        raise HTTPException(
            status_code=403, detail="Only internal users can list storage connections."
        )
    active = [c for c in await connections_service.list_connections(db) if c.is_active]
    active.sort(key=lambda c: (not c.is_default, c.name))
    return [
        StorageConnectionAvailable(id=c.id, name=c.name, type=c.type, is_default=c.is_default)
        for c in active
    ]


@router.post("", response_model=StorageConnectionOut, status_code=201)
async def create_connection(
    body: StorageConnectionCreate,
    admin: AdminUser,
    db: DbSession,
    box: Box,
    settings: AppSettings,
) -> StorageConnectionOut:
    try:
        connection = await connections_service.create_connection(
            db,
            type_=body.type,
            name=body.name,
            config=body.config,
            secret=body.secret,
            is_default=body.is_default,
            actor=admin,
            box=box,
            settings=settings,
        )
    except connections_service.StorageConnectionError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except connections_service.StorageConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return _out(connection)


@router.patch("/{connection_id}", response_model=StorageConnectionOut)
async def update_connection(
    connection_id: uuid.UUID,
    body: StorageConnectionUpdate,
    admin: AdminUser,
    db: DbSession,
    box: Box,
    settings: AppSettings,
) -> StorageConnectionOut:
    connection = await _get(db, connection_id)
    if body.is_default is False:
        raise HTTPException(
            status_code=422, detail="Set another connection as the default instead."
        )
    try:
        if body.is_default:
            await connections_service.set_default(db, connection, actor=admin)
        if body.model_fields_set & {"name", "config", "secret", "is_active"}:
            await connections_service.update_connection(
                db,
                connection,
                actor=admin,
                box=box,
                settings=settings,
                name=body.name,
                config=body.config,
                secret=body.secret,
                is_active=body.is_active,
            )
    except connections_service.StorageConnectionError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except connections_service.StorageConnectionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return _out(connection)


@router.post("/{connection_id}/test", response_model=StorageTestResult)
async def test_connection(
    connection_id: uuid.UUID, admin: AdminUser, db: DbSession, settings: AppSettings
) -> StorageTestResult:
    connection = await _get(db, connection_id)
    status = await connections_service.test_connection(
        db, connection, actor=admin, settings=settings
    )
    return StorageTestResult(ok=status.ok, detail=status.detail)
```

In `backend/app/main.py` extend the routes import to

```python
from app.api.routes import (
    auth,
    documents,
    health,
    projects,
    storage_connections,
    uploads,
    users,
)
```

and add, after the `users.router` include:

```python
    app.include_router(storage_connections.router, prefix=API_PREFIX)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/api/test_storage_connections.py -v`
Expected: 10 passed.

- [ ] **Step 7: Re-export the OpenAPI document, run the gates**

```bash
uv run python -m app.openapi_export ../frontend/openapi.json
uv run pytest -q
uv run ruff format . && uv run ruff check . && uv run mypy app
```

Expected: `Wrote ../frontend/openapi.json`; all tests pass (including `test_committed_frontend_document_is_current`); no lint or type errors. `git diff --stat ../frontend/openapi.json` shows the new `/api/v1/storage-connections` paths.

- [ ] **Step 8: Commit**

```bash
git add backend/app backend/tests ../frontend/openapi.json
git commit -m "feat(backend): add storage connection admin API with default and test actions"
```

### Task 3: Project creation with a chosen connection and root, root uniqueness, user directory

**Files:**
- Modify: `backend/app/schemas/projects.py` (`ProjectCreate`), `backend/app/services/projects.py` (`root_in_use`, lock + check in `create_project`), `backend/app/api/routes/projects.py` (pass the two fields), `backend/app/schemas/users.py` (`UserDirectoryEntry`), `backend/app/api/routes/users.py` (`GET /users/directory`), `frontend/openapi.json` (re-exported)
- Test: `backend/tests/api/test_projects.py` (append + one line in `test_role_matrix`), `backend/tests/api/test_users.py` (append)

**Interfaces:**
- Consumes: `validate_root_segment` (`app.storage.base`), `create_project(connection_id, root)`, `ProjectValidationError`, `make_connection` (Task 1); `CurrentUser`.
- Produces: `ProjectCreate(name, client_name=None, storage_connection_id: uuid.UUID | None = None, storage_root: str | None = None)` (blank root → None; invalid root → 422 with `ROOT_SEGMENT_MESSAGE`); `app.services.projects.root_in_use(db, connection_id, root) -> bool`; duplicate root on the same connection → `ProjectValidationError("This root folder is already used by another project on the selected connection.")`; `app.schemas.users.UserDirectoryEntry(id, email, display_name, account_type)`; `GET /api/v1/users/directory` → active users ordered by display name, for internal accounts (customers 403).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/test_projects.py` (add `import uuid` and `from pathlib import Path` to the imports, and `make_connection` to the `tests.factories` import):

```python
async def test_create_project_on_a_chosen_connection_with_a_custom_root(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    user = await make_user(db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    c = await _client_for(make_client, db, settings, user)
    response = await c.post(
        "/api/v1/projects",
        json={
            "name": "Customer Portal",
            "storage_connection_id": str(archive.id),
            "storage_root": "cp-2026",
        },
    )
    assert response.status_code == 201
    assert response.json()["storage"] == {
        "connection_id": str(archive.id),
        "connection_name": "Archive",
        "type": "localfs",
        "root": "cp-2026",
    }
    assert (storage_root / "archive" / "cp-2026" / "project.yaml").exists()
    assert not (storage_root / "customer-portal").exists()


async def test_create_project_defaults_to_the_default_connection_and_slug(
    make_client: MakeClient, db: AsyncSession, settings: Settings, storage_root: Path
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    response = await c.post("/api/v1/projects", json={"name": "Plain", "storage_root": "  "})
    assert response.status_code == 201
    storage = response.json()["storage"]
    assert storage["connection_name"] == "Local storage" and storage["root"] == "plain"
    assert (storage_root / "plain" / "project.yaml").exists()


async def test_unknown_or_inactive_connection_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    unknown = await c.post(
        "/api/v1/projects", json={"name": "X", "storage_connection_id": str(uuid.uuid4())}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "Storage connection not found."
    inactive = await make_connection(db, name="Old", root_path="old", is_active=False)
    response = await c.post(
        "/api/v1/projects", json={"name": "Y", "storage_connection_id": str(inactive.id)}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Storage connection is not active."
    assert (await db.scalars(select(Project))).all() == []


async def test_invalid_root_folders_are_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    for root in ("../x", "a/b", ".hidden", "x y", "/abs", "a" * 81, ".trash", "-dash"):
        response = await c.post("/api/v1/projects", json={"name": "X", "storage_root": root})
        assert response.status_code == 422, root
    assert (await db.scalars(select(Project))).all() == []


async def test_duplicate_root_on_same_connection_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    archive = await make_connection(db, name="Archive", root_path="archive")
    c = await _client_for(make_client, db, settings, user)
    first = await c.post("/api/v1/projects", json={"name": "First", "storage_root": "shared"})
    assert first.status_code == 201
    second = await c.post("/api/v1/projects", json={"name": "Second", "storage_root": "shared"})
    assert second.status_code == 422 and "already used" in second.json()["detail"]
    # the same root on another connection is a different folder
    elsewhere = await c.post(
        "/api/v1/projects",
        json={"name": "Third", "storage_connection_id": str(archive.id), "storage_root": "shared"},
    )
    assert elsewhere.status_code == 201
    # a custom root equal to a project's default root (its slug) is refused as well
    assert (await c.post("/api/v1/projects", json={"name": "Plain"})).status_code == 201
    clash = await c.post("/api/v1/projects", json={"name": "Clash", "storage_root": "plain"})
    assert clash.status_code == 422
    names = sorted(p.name for p in (await db.scalars(select(Project))).all())
    assert names == ["First", "Plain", "Third"]
```

In `test_role_matrix`, after the line asserting the client's `settings` is `None`, add:

```python
    assert (await ctx["client"].get(url)).json()["storage"] is None  # type: ignore[attr-defined]
```

Append to `backend/tests/api/test_users.py`:

```python
async def test_user_directory_lists_active_users_for_internal_accounts(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    alice = await make_user(db, settings)
    await make_user(db, settings, email="bob@example.com", display_name="Bob")
    await make_user(db, settings, email="gone@example.com", display_name="Gone", is_active=False)
    customer = await make_user(
        db, settings, email="c@client.com", display_name="Cara", account_type="customer"
    )
    alice_c = await make_client(await make_session_token(db, settings, alice))
    response = await alice_c.get("/api/v1/users/directory")
    assert response.status_code == 200
    rows = response.json()
    assert [r["display_name"] for r in rows] == ["Alice", "Bob", "Cara"]
    assert set(rows[0]) == {"id", "email", "display_name", "account_type"}
    assert rows[0]["id"] == str(alice.id) and rows[2]["account_type"] == "customer"
    customer_c = await make_client(await make_session_token(db, settings, customer))
    assert (await customer_c.get("/api/v1/users/directory")).status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_projects.py tests/api/test_users.py -v`
Expected: the new project tests fail (the API ignores the two fields, so storage shows `Local storage`/the slug, or 201 where 422 is expected); the directory test fails with 404.

- [ ] **Step 3: Schema fields**

In `backend/app/schemas/projects.py` add the imports

```python
from app.storage.base import StoragePathError, validate_root_segment
```

and replace `ProjectCreate`:

```python
class ProjectCreate(BaseModel):
    name: str = Field(max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    storage_connection_id: uuid.UUID | None = None  # default: the default connection
    storage_root: str | None = Field(default=None, max_length=80)  # default: the slug

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("storage_root")
    @classmethod
    def _root(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return validate_root_segment(value.strip())
        except StoragePathError as exc:
            raise ValueError(str(exc)) from exc
```

In `backend/app/schemas/users.py` append:

```python
class UserDirectoryEntry(BaseModel):
    """What an internal user sees when picking project members."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    account_type: str
```

- [ ] **Step 4: Root uniqueness and the directory route**

In `backend/app/services/projects.py` add after `resolve_connection`:

```python
async def root_in_use(db: AsyncSession, connection_id: uuid.UUID, root: str) -> bool:
    """True when any project, archived ones included (their files still exist), uses ``root``
    on the connection."""
    found = await db.scalar(
        select(Project.id).where(
            Project.storage.op("->>")("connection_id") == str(connection_id),
            Project.storage.op("->>")("root") == root,
        )
    )
    return found is not None
```

and in `create_project`, directly after the `validate_root_segment` try/except block, insert:

```python
    # Serialise on (connection, root) too: two different names may ask for the same folder.
    await acquire_xact_lock(db, "project-root", f"{connection.id}:{root_folder}")
    if await root_in_use(db, connection.id, root_folder):
        raise ProjectValidationError(
            "This root folder is already used by another project on the selected connection."
        )
```

In `backend/app/api/routes/projects.py`, in `create_project`, pass the fields:

```python
        project = await projects_service.create_project(
            db,
            name=body.name,
            client_name=body.client_name,
            creator=user,
            settings=settings,
            taxonomy=taxonomy,
            connection_id=body.storage_connection_id,
            root=body.storage_root,
        )
```

In `backend/app/api/routes/users.py` extend the deps import to `from app.api.deps import AdminUser, CurrentUser, DbSession`, add `UserDirectoryEntry` to the schemas import, and add **before** the `PATCH /{user_id}` route:

```python
@router.get("/directory", response_model=list[UserDirectoryEntry])
async def user_directory(user: CurrentUser, db: DbSession) -> list[UserDirectoryEntry]:
    """Active users an internal user may add to a project; customers cannot browse users."""
    if user.account_type != "internal":
        raise HTTPException(status_code=403, detail="Only internal users can list users.")
    users = (
        await db.scalars(
            select(User).where(User.is_active.is_(True)).order_by(User.display_name, User.email)
        )
    ).all()
    return [UserDirectoryEntry.model_validate(u) for u in users]
```

- [ ] **Step 5: Run the tests, re-export, gates**

```bash
uv run pytest tests/api/test_projects.py tests/api/test_users.py -v
uv run python -m app.openapi_export ../frontend/openapi.json
uv run pytest -q
uv run ruff format . && uv run ruff check . && uv run mypy app
```

Expected: all pass; `frontend/openapi.json` now documents `storage_connection_id`, `storage_root` on `ProjectCreate` and `/api/v1/users/directory`.

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests ../frontend/openapi.json
git commit -m "feat(backend): choose the storage connection and root at project creation; user directory"
```

### Task 4: OpenAPI export module and drift test

**Files:**
- Create: `backend/app/openapi_export.py`, `backend/tests/api/test_openapi_export.py`, `frontend/openapi.json` (generated)

**Interfaces:**
- Consumes: `create_app`, `Settings`.
- Produces: `app.openapi_export.export_settings() -> Settings`, `build_document() -> dict[str, Any]`, `render(document) -> str` (2-space indent, sorted keys, trailing newline), `main(argv) -> int`; command `uv run python -m app.openapi_export ../frontend/openapi.json`; the committed `frontend/openapi.json` that Task 6 generates types from; pytest fails when the committed file is stale.

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_openapi_export.py`:

```python
"""The OpenAPI export the frontend generates its client from, and the drift check that keeps
``frontend/openapi.json`` current."""

import json
from pathlib import Path

import pytest

from app.openapi_export import build_document, main, render

REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / "frontend" / "openapi.json"
HINT = "run `uv run python -m app.openapi_export ../frontend/openapi.json` from backend/ and commit"


def test_export_writes_the_document(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "openapi.json"
    assert main([str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "QC-Agent"
    for path in ("/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/projects", "/api/v1/users"):
        assert path in document["paths"], path
    assert "LoginRequest" in document["components"]["schemas"]
    assert out.read_text(encoding="utf-8").endswith("}\n")


def test_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err


def test_render_is_deterministic() -> None:
    assert render(build_document()) == render(build_document())


def test_committed_frontend_document_is_current() -> None:
    assert COMMITTED.exists(), f"frontend/openapi.json is missing: {HINT}"
    assert COMMITTED.read_text(encoding="utf-8") == render(build_document()), (
        f"frontend/openapi.json is stale: {HINT}"
    )
```

Run: `uv run pytest tests/api/test_openapi_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.openapi_export'`.

- [ ] **Step 2: The export module**

`backend/app/openapi_export.py`:

```python
"""Write the API's OpenAPI document as JSON for the frontend's generated client.

    uv run python -m app.openapi_export ../frontend/openapi.json

The app is built with placeholder settings: ``create_app`` connects to nothing until its
lifespan runs, and ``app.openapi()`` never runs it, so the export needs no database or ``.env``.
"""

import json
import sys
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from app.core.config import Settings
from app.main import create_app

USAGE = "usage: python -m app.openapi_export <output.json>"


def export_settings() -> Settings:
    """Placeholder values that satisfy validation; nothing here ever serves a request."""
    return Settings(
        database_url="postgresql+asyncpg://export:export@localhost/export",
        session_secret="openapi-export-placeholder-not-a-real-secret",  # noqa: S106
        secret_encryption_key=Fernet.generate_key().decode(),
        expose_docs=False,
    )


def build_document() -> dict[str, Any]:
    return create_app(export_settings()).openapi()


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    output = Path(args[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(build_document()), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Export, run the tests and gates**

```bash
uv run python -m app.openapi_export ../frontend/openapi.json
uv run pytest tests/api/test_openapi_export.py -v
uv run ruff format . && uv run ruff check . && uv run mypy app
```

Expected: `Wrote ../frontend/openapi.json`; 4 passed; no lint or type errors. `head -3 ../frontend/openapi.json` shows `{` and `"components": {`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/openapi_export.py backend/tests/api/test_openapi_export.py ../frontend/openapi.json
git commit -m "feat(backend): export the OpenAPI document for the frontend client"
```

### Task 5: Frontend scaffold, tooling, UI primitives and the messages module

**Files:**
- Create (by `create-next-app`, then edited): `frontend/package.json`, `frontend/pnpm-lock.yaml`, `frontend/pnpm-workspace.yaml`, `frontend/tsconfig.json`, `frontend/next.config.ts`, `frontend/postcss.config.mjs`, `frontend/eslint.config.mjs`, `frontend/.gitignore`, `frontend/README.md`, `frontend/AGENTS.md`, `frontend/CLAUDE.md`, `frontend/src/app/{layout.tsx,page.tsx,globals.css,favicon.ico}`
- Create: `frontend/.prettierrc`, `frontend/.prettierignore`, `frontend/vitest.config.mts`, `frontend/vitest.setup.ts`, `frontend/src/app/not-found.tsx`, `frontend/src/messages.ts`, `frontend/src/lib/cx.ts`, `frontend/src/test/fetch-mock.ts`, `frontend/src/components/ui/{Button,Field,Select,Checkbox,Dialog,Alert,Badge,Table,PageHeader}.tsx`
- Test: `frontend/src/components/ui/{Button,Field,Dialog}.test.tsx`
- Delete: `frontend/public/*.svg`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - Scripts (from `frontend/`): `pnpm dev`, `pnpm build`, `pnpm start`, `pnpm lint`, `pnpm format`, `pnpm format:write`, `pnpm typecheck`, `pnpm test`, `pnpm test:watch`. Installed dependencies for every later frontend task: `openapi-fetch`, `qrcode`; dev: `openapi-typescript`, `@types/qrcode`, `vitest`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/{react,dom,jest-dom,user-event}`, `prettier`, `@playwright/test`, `otplib`.
  - `next.config.ts` rewrite `/api/:path*` → `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*`.
  - `src/messages.ts`: `m` (all UI strings, grouped `app`, `common`, `nav`, `roles`, `auth`, `projects`, `users`, `storage`) and `roleName(role: string): string`.
  - `src/lib/cx.ts`: `cx(...parts: Array<string | false | null | undefined>): string`.
  - UI primitives: `Button({ variant?: "primary" | "secondary" | "danger"; busy?: boolean; ...button props })` (defaults to `type="button"`, disabled while `busy`), `Field({ label; hint?; error?; ...input props })` (label/hint/error wired with `htmlFor`/`aria-describedby`/`aria-invalid`; `inputClass` exported), `Select({ label; hint?; error?; children; ...select props })`, `Checkbox({ label; ...input props })`, `Dialog({ open; title; onClose; children; footer? })` (native `<dialog>`, `showModal()`), `Alert({ kind: "error" | "success" | "info"; children })` (`role="alert"` for errors, `role="status"` otherwise), `Badge({ tone?: "neutral" | "success" | "warning" | "danger"; children })`, `Table({ children; caption? })`, `Th`, `Td`, `PageHeader({ title; actions? })`.
  - `src/test/fetch-mock.ts`: `mockFetch(routes: Route[]) -> { fn, calls, body(index) }` where `Route = { method?: string; path: string; status?: number; body?: unknown; handler?: (request: Request) => unknown | Promise<unknown> }`; it stubs `globalThis.fetch` and records every `Request`.
  - `vitest.setup.ts` polyfills `HTMLDialogElement.prototype.showModal/close` for jsdom, registers jest-dom matchers, calls `cleanup()` and `vi.unstubAllGlobals()` after each test.

- [ ] **Step 1: Scaffold with create-next-app and install the dependencies**

From the repository root:

```bash
pnpm dlx create-next-app@16 frontend --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm --disable-git --yes
cd frontend
rm public/file.svg public/globe.svg public/next.svg public/vercel.svg public/window.svg
pnpm add openapi-fetch qrcode
pnpm add -D openapi-typescript @types/qrcode vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/dom @testing-library/jest-dom @testing-library/user-event prettier @playwright/test otplib
```

Expected: `frontend/` with `src/app/{layout.tsx,page.tsx,globals.css,favicon.ico}`, `next.config.ts`, `eslint.config.mjs`, `tsconfig.json`, `pnpm-lock.yaml`; `package.json` lists `next 16.3.x`, `react 19.2.x`, `typescript ^5`, `"packageManager": "pnpm@11.x"`. Keep the generated `AGENTS.md` and `CLAUDE.md` (`next dev` recreates them when missing).

- [ ] **Step 2: Package scripts, Prettier, ESLint ignores, git ignores**

In `frontend/package.json` set `"name": "qc-agent-frontend"` and replace the `scripts` block with:

```json
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "format": "prettier --check .",
    "format:write": "prettier --write .",
    "typecheck": "next typegen && tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  },
```

`frontend/.prettierrc`:

```json
{ "printWidth": 100 }
```

`frontend/.prettierignore`:

```
.next
node_modules
pnpm-lock.yaml
openapi.json
src/lib/api/schema.d.ts
playwright-report
test-results
next-env.d.ts
AGENTS.md
CLAUDE.md
e2e/.state
```

Replace `frontend/eslint.config.mjs`:

```js
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "coverage/**",
    "playwright-report/**",
    "test-results/**",
    "next-env.d.ts",
    "src/lib/api/schema.d.ts", // generated by openapi-typescript
  ]),
]);

export default eslintConfig;
```

Append to `frontend/.gitignore`:

```gitignore

# tests
/playwright-report/
/test-results/
/e2e/.state/
```

- [ ] **Step 3: Next config, root layout, redirect, not-found, styles**

`frontend/next.config.ts`:

```ts
import type { NextConfig } from "next";

// Same-origin API: the browser calls /api/... on this host and Next proxies it to the backend,
// so the HttpOnly session cookie is a first-party cookie. Read at BUILD time.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
```

`frontend/src/app/globals.css`:

```css
@import "tailwindcss";

:root {
  --bg: #f8fafc;
  --surface: #ffffff;
  --fg: #0f172a;
  --muted: #64748b;
  --border: #e2e8f0;
  --brand: #1d4ed8;
  --brand-fg: #ffffff;
  --danger: #b91c1c;
  --success: #15803d;
  --warning: #b45309;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b1220;
    --surface: #111a2e;
    --fg: #e5e7eb;
    --muted: #94a3b8;
    --border: #1f2a44;
    --brand: #60a5fa;
    --brand-fg: #0b1220;
    --danger: #f87171;
    --success: #4ade80;
    --warning: #fbbf24;
  }
}

@theme inline {
  --color-bg: var(--bg);
  --color-surface: var(--surface);
  --color-fg: var(--fg);
  --color-muted: var(--muted);
  --color-border: var(--border);
  --color-brand: var(--brand);
  --color-brand-fg: var(--brand-fg);
  --color-danger: var(--danger);
  --color-success: var(--success);
  --color-warning: var(--warning);
}

body {
  background: var(--bg);
  color: var(--fg);
  font-family:
    ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
    sans-serif;
}
```

`frontend/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "QC-Agent",
  description: "Project document knowledge base",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
```

`frontend/src/app/page.tsx`:

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/projects");
}
```

`frontend/src/app/not-found.tsx`:

```tsx
import Link from "next/link";
import { m } from "@/messages";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-lg p-8 text-center">
      <h1 className="text-2xl font-semibold">{m.app.notFoundTitle}</h1>
      <p className="mt-2 text-muted">{m.app.notFoundBody}</p>
      <Link href="/projects" className="mt-6 inline-block text-brand underline">
        {m.app.backToProjects}
      </Link>
    </main>
  );
}
```

- [ ] **Step 4: Messages**

`frontend/src/messages.ts` (every string the plan's screens use; later tasks only read it):

```ts
/** Every user-facing string (spec 12: English UI, one messages file). */
export const m = {
  app: {
    name: "QC-Agent",
    loading: "Loading…",
    notFoundTitle: "Page not found",
    notFoundBody: "The page does not exist or you do not have access to it.",
    backToProjects: "Back to projects",
  },
  common: {
    save: "Save",
    cancel: "Cancel",
    close: "Close",
    create: "Create",
    copy: "Copy",
    copied: "Copied",
    retry: "Retry",
    actions: "Actions",
    none: "None",
    yes: "Yes",
    no: "No",
    loadFailed: "Could not load data. Try again.",
    requestFailed: "The request failed. Try again.",
  },
  nav: {
    main: "Main",
    projects: "Projects",
    admin: "Admin",
    adminSections: "Admin sections",
    users: "Users",
    storage: "Storage",
    logout: "Log out",
    changePassword: "Change password",
  },
  roles: {
    admin: "Administrator",
    internal: "Team member",
    customer: "Customer",
    owner: "Owner",
    editor: "Editor",
    viewer: "Viewer",
    client: "Client",
  },
  auth: {
    loginTitle: "Sign in",
    email: "E-mail",
    password: "Password",
    signIn: "Sign in",
    loginFailed: "Invalid e-mail or password.",
    mfaTitle: "Two-factor authentication",
    enrolIntro:
      "Scan the QR code with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, …), then enter the 6-digit code it shows.",
    qrAlt: "QR code for your authenticator app",
    setupKey: "Setup key (if you cannot scan)",
    code: "Authentication code",
    confirm: "Confirm",
    invalidCode: "Invalid code.",
    verifyIntro: "Enter the 6-digit code from your authenticator app, or one of your recovery codes.",
    codeOrRecovery: "Authentication or recovery code",
    verify: "Verify",
    recoveryTitle: "Recovery codes",
    recoveryIntro:
      "Store these codes somewhere safe. Each code signs you in once if you lose your authenticator. They are shown only now.",
    recoveryAck: "I have saved my recovery codes",
    continue: "Continue",
    copyCodes: "Copy codes",
    downloadCodes: "Download as text file",
    changePasswordTitle: "Change your password",
    changePasswordIntro:
      "Choose a new password of at least 12 characters. If an administrator gave you a temporary password, you must change it before continuing.",
    currentPassword: "Current password",
    newPassword: "New password",
    confirmPassword: "Confirm new password",
    passwordsDiffer: "The new passwords do not match.",
    changePasswordAction: "Change password",
  },
  projects: {
    title: "Projects",
    empty: "You are not a member of any project yet.",
    newProject: "New project",
    name: "Project name",
    clientName: "Client name",
    storageConnection: "Storage connection",
    rootFolder: "Root folder (optional)",
    rootFolderHint: "Letters, digits, '.', '_' or '-'; defaults to the project slug.",
    consentLink: "What is the LLM data-processing confirmation?",
    consentExplain:
      "Before anyone can upload documents, a project owner records that the customer agreed that converted document text may be sent to the Claude API for type checks and normalisation. The confirmation is stored in the audit log with the confirming person's name.",
    createAction: "Create project",
    created: "Created",
    client: "Client",
    myRole: "My role",
    overview: "Overview",
    members: "Members",
    settings: "Settings",
    storage: "Storage",
    connection: "Connection",
    type: "Type",
    root: "Root folder",
    consentStatus: "LLM data processing",
    consentRecorded: (name: string, date: string) => `Confirmed by ${name} on ${date}.`,
    consentMissing:
      "Not confirmed yet. Uploads are blocked until an owner records the customer's confirmation.",
    confirmedByName: "Name of the confirming person",
    recordConsent: "Record customer confirmation",
    consentDone: "Confirmation recorded.",
    memberName: "Name",
    memberEmail: "E-mail",
    memberType: "Account",
    memberRole: "Role",
    selectUser: "User",
    addMember: "Add member",
    remove: "Remove",
    noMembers: "No members yet.",
    saveMembers: "Save members",
    membersSaved: "Members saved.",
    model: "Model",
    checkBudget: "Type-check budget (USD)",
    normalizeBudget: "Normalisation budget (USD)",
    saveSettings: "Save settings",
    settingsSaved: "Settings saved.",
    notFound: "Project not found.",
  },
  users: {
    title: "Users",
    newUser: "Create user",
    email: "E-mail",
    displayName: "Display name",
    accountType: "Account type",
    internal: "Internal",
    customer: "Customer",
    isAdmin: "Administrator",
    status: "Status",
    active: "Active",
    inactive: "Inactive",
    mfa: "MFA",
    enrolled: "Enrolled",
    notEnrolled: "Not enrolled",
    locked: "Locked",
    mustChange: "Must change password",
    deactivate: "Deactivate",
    reactivate: "Reactivate",
    resetPassword: "Reset password",
    resetMfa: "Reset MFA",
    mfaReset: "MFA reset. The user enrols again at the next sign-in.",
    created: "User created.",
    tempPasswordTitle: "Temporary password",
    tempPasswordIntro:
      "Give this password to the user through a secure channel. It is shown only once; the user must change it at the first sign-in.",
    tempPasswordFor: (email: string) => `Temporary password for ${email}`,
    confirmDeactivate: "Deactivate this user? Their sessions end immediately.",
    confirmResetPassword: "Reset this user's password? Their sessions end immediately.",
    confirmResetMfa: "Reset this user's MFA? Their sessions end immediately.",
  },
  storage: {
    title: "Storage connections",
    newConnection: "New connection",
    createTitle: "New storage connection",
    editTitle: "Edit connection",
    edit: "Edit",
    name: "Name",
    type: "Type",
    default: "Default",
    active: "Active",
    inactive: "Inactive",
    secret: "Secret",
    hasSecret: "Stored",
    noSecret: "None",
    setDefault: "Set as default",
    deactivate: "Deactivate",
    reactivate: "Reactivate",
    test: "Test connection",
    testing: "Testing…",
    testOk: "Connection OK",
    testFailed: "Connection failed",
    rootPath: "Root path",
    rootPathHint:
      "Folder for this connection, relative to LOCAL_STORAGE_ROOT on the server ('.' is the storage root itself).",
    secretField: "Secret (write-only)",
    secretHint: "Stored encrypted and never shown again. Leave empty to keep the current secret.",
    typeLabels: {
      localfs: "Local filesystem",
      sharepoint: "SharePoint / OneDrive (not available yet)",
      gdrive: "Google Drive (not available yet)",
    } as Record<string, string>,
    saved: "Connection saved.",
    defaultChanged: "Default connection changed.",
  },
} as const;

const ROLE_NAMES: Record<string, string> = {
  owner: m.roles.owner,
  editor: m.roles.editor,
  viewer: m.roles.viewer,
  client: m.roles.client,
};

export function roleName(role: string): string {
  return ROLE_NAMES[role] ?? role;
}
```

- [ ] **Step 5: Vitest configuration and the fetch mock**

`frontend/vitest.config.mts`:

```ts
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

`frontend/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom 30 has no <dialog> methods; browsers provide the focus trap and Escape handling.
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
```

`frontend/src/test/fetch-mock.ts`:

```ts
import { vi } from "vitest";

export type Route = {
  method?: string;
  path: string;
  status?: number;
  body?: unknown;
  handler?: (request: Request) => unknown | Promise<unknown>;
};

/** Stub global fetch with routes matched on method + pathname; records every Request. */
export function mockFetch(routes: Route[]) {
  const calls: Request[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    calls.push(request.clone());
    const url = new URL(request.url);
    const route = routes.find(
      (r) => (r.method ?? "GET") === request.method && r.path === url.pathname,
    );
    if (!route) {
      return new Response(
        JSON.stringify({ detail: `No mock for ${request.method} ${url.pathname}` }),
        { status: 500, headers: { "content-type": "application/json" } },
      );
    }
    const status = route.status ?? 200;
    const body = route.handler ? await route.handler(request) : route.body;
    if (status === 204) return new Response(null, { status });
    return new Response(JSON.stringify(body ?? {}), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return {
    fn,
    calls,
    /** JSON body of the n-th recorded request. */
    body: async (index: number): Promise<unknown> => JSON.parse(await calls[index].text()),
    /** The n-th recorded request matching method + path, if any. */
    find: (method: string, path: string) =>
      calls.find((c) => c.method === method && new URL(c.url).pathname === path),
  };
}
```

- [ ] **Step 6: Write the failing primitive tests**

`frontend/src/components/ui/Button.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Button } from "./Button";

it("defaults to type=button and is disabled while busy", () => {
  render(<Button busy>Save</Button>);
  const button = screen.getByRole("button", { name: "Save" });
  expect(button).toHaveAttribute("type", "button");
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "true");
});
```

`frontend/src/components/ui/Field.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Field } from "./Field";

it("associates the label, hint and error with the input", () => {
  render(<Field label="E-mail" hint="Work address" error="Required" />);
  const input = screen.getByLabelText("E-mail");
  expect(input).toHaveAccessibleDescription("Work address Required");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("alert")).toHaveTextContent("Required");
});
```

`frontend/src/components/ui/Dialog.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";

it("opens as a modal with an accessible name and reports close", async () => {
  const onClose = vi.fn();
  render(
    <Dialog open title="Create project" onClose={onClose}>
      <input aria-label="Name" />
    </Dialog>,
  );
  const dialog = screen.getByRole("dialog", { name: "Create project" });
  expect(dialog).toBeVisible();
  expect((dialog as HTMLDialogElement).open).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(1);
});
```

Run: `pnpm test`
Expected: FAIL — the three test files cannot resolve `./Button`, `./Field`, `./Dialog`.

- [ ] **Step 7: UI primitives**

`frontend/src/lib/cx.ts`:

```ts
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
```

`frontend/src/components/ui/Button.tsx`:

```tsx
import type { ButtonHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

type Variant = "primary" | "secondary" | "danger";
type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean };

const variants: Record<Variant, string> = {
  primary: "bg-brand text-brand-fg hover:opacity-90",
  secondary: "border border-border bg-surface text-fg hover:bg-bg",
  danger: "bg-danger text-white hover:opacity-90",
};

export function Button({
  variant = "primary",
  busy = false,
  disabled,
  className,
  type = "button",
  children,
  ...rest
}: Props) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
        "disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
```

`frontend/src/components/ui/Field.tsx`:

```tsx
import { useId, type InputHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  hint?: string;
  error?: string | null;
};

export const inputClass =
  "block w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-60";

export function Field({ label, hint, error, className, ...input }: Props) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={describedBy || undefined}
        aria-invalid={error ? true : undefined}
        className={cx(inputClass, className)}
        {...input}
      />
      {hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
```

`frontend/src/components/ui/Select.tsx`:

```tsx
import { useId, type ReactNode, type SelectHTMLAttributes } from "react";
import { cx } from "@/lib/cx";
import { inputClass } from "./Field";

type Props = Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> & {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
};

export function Select({ label, hint, error, className, children, ...select }: Props) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <select
        id={id}
        aria-describedby={describedBy || undefined}
        aria-invalid={error ? true : undefined}
        className={cx(inputClass, className)}
        {...select}
      >
        {children}
      </select>
      {hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
```

`frontend/src/components/ui/Checkbox.tsx`:

```tsx
import { useId, type InputHTMLAttributes } from "react";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type"> & { label: string };

export function Checkbox({ label, ...input }: Props) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <input id={id} type="checkbox" className="h-4 w-4 accent-brand" {...input} />
      <label htmlFor={id} className="text-sm">
        {label}
      </label>
    </div>
  );
}
```

`frontend/src/components/ui/Dialog.tsx`:

```tsx
"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { m } from "@/messages";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
};

/** Native <dialog> opened with showModal(): the browser traps focus and closes on Escape,
 * which fires `close`, so the parent only has to flip `open` in `onClose`. */
export function Dialog({ open, title, onClose, children, footer }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    else if (!open && element.open) element.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      className="m-auto w-full max-w-lg rounded-lg border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/40"
    >
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={m.common.close}
          className="rounded px-2 text-xl leading-none text-muted hover:text-fg"
        >
          ×
        </button>
      </div>
      <div className="px-5 py-4">{children}</div>
      {footer ? (
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>
      ) : null}
    </dialog>
  );
}
```

`frontend/src/components/ui/Alert.tsx`:

```tsx
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

type Kind = "error" | "success" | "info";

const styles: Record<Kind, string> = {
  error: "border-danger/40 bg-danger/10 text-danger",
  success: "border-success/40 bg-success/10 text-success",
  info: "border-border bg-bg text-fg",
};

export function Alert({
  kind,
  children,
  className,
}: {
  kind: Kind;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={cx("rounded-md border px-3 py-2 text-sm", styles[kind], className)}
    >
      {children}
    </div>
  );
}
```

`frontend/src/components/ui/Badge.tsx`:

```tsx
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

type Tone = "neutral" | "success" | "warning" | "danger";

const tones: Record<Tone, string> = {
  neutral: "border-border bg-bg text-muted",
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-danger/40 bg-danger/10 text-danger",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}
```

`frontend/src/components/ui/Table.tsx`:

```tsx
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

export function Table({ children, caption }: { children: ReactNode; caption?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        {children}
      </table>
    </div>
  );
}

export function Th({ children }: { children?: ReactNode }) {
  return (
    <th scope="col" className="border-b border-border bg-bg px-3 py-2 font-medium text-muted">
      {children}
    </th>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cx("border-b border-border px-3 py-2 align-middle", className)}>{children}</td>;
}
```

`frontend/src/components/ui/PageHeader.tsx`:

```tsx
import type { ReactNode } from "react";

export function PageHeader({ title, actions }: { title: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex items-center justify-between gap-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {actions ? <div className="flex gap-2">{actions}</div> : null}
    </div>
  );
}
```

- [ ] **Step 8: README stub**

Replace `frontend/README.md` (Task 11 writes the full version):

````markdown
# QC-Agent frontend

Next.js (App Router, TypeScript, Tailwind CSS) web application for QC-Agent. See the repository README for running backend and frontend together.

```bash
pnpm install
pnpm dev          # http://localhost:3000, proxies /api to BACKEND_URL (default http://localhost:8000)
pnpm test         # Vitest + Testing Library
pnpm lint && pnpm format && pnpm typecheck && pnpm build
```
````

- [ ] **Step 9: Run every gate**

```bash
pnpm format:write
pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm build
```

Expected: no lint errors (warnings are acceptable); Prettier reports all files formatted; `tsc` clean; `3 passed`; `next build` lists `/` (dynamic, redirects) and `/_not-found`.

- [ ] **Step 10: Commit**

```bash
cd ..
git add frontend
git commit -m "feat(frontend): scaffold the Next.js app with tooling, UI primitives and messages"
```

### Task 6: Typed API client, session provider, application shell and route guards

**Files:**
- Create: `frontend/src/lib/api/schema.d.ts` (generated), `frontend/src/lib/api/client.ts`, `frontend/src/lib/api/errors.ts`, `frontend/src/lib/session/next-route.ts`, `frontend/src/lib/session/SessionProvider.tsx`, `frontend/src/lib/hooks/useLoad.ts`, `frontend/src/components/shell/AppShell.tsx`, `frontend/src/app/(app)/layout.tsx`, `frontend/src/app/(app)/admin/layout.tsx`, `frontend/src/app/(auth)/layout.tsx`, `frontend/src/test/session.tsx`
- Modify: `frontend/package.json` (two scripts)
- Test: `frontend/src/lib/api/client.test.ts`, `frontend/src/lib/api/errors.test.ts`, `frontend/src/lib/session/next-route.test.ts`, `frontend/src/lib/session/SessionProvider.test.tsx`, `frontend/src/lib/hooks/useLoad.test.tsx`, `frontend/src/components/shell/AppShell.test.tsx`, `frontend/src/app/(app)/admin/layout.test.tsx`

**Interfaces:**
- Consumes: `frontend/openapi.json` (Task 4), UI primitives, `m`, `mockFetch` (Task 5).
- Produces:
  - Scripts `pnpm api:generate` (openapi-typescript → `src/lib/api/schema.d.ts`) and `pnpm api:check` (regenerate + `git diff --exit-code`).
  - `src/lib/api/client.ts`: `api` (openapi-fetch client typed with `paths`; adds `X-QC-Agent: 1` to every non-GET/HEAD request; calls the unauthorized handler on a 401 from any path outside `/api/v1/auth/`), `makeClient(fetchImpl?)`, `setUnauthorizedHandler(handler | null)`, `CSRF_HEADER`.
  - `src/lib/api/errors.ts`: `apiErrorMessage(error: unknown, fallback: string): string` (string `detail`, list of strings, or pydantic `{msg}` items), `unwrap<T>(result: { data?: T; error?: unknown }, fallback?): T` (throws `Error(apiErrorMessage(...))` when `data` is undefined — for GET loaders only, never for 204 responses).
  - `src/lib/session/next-route.ts`: `type Me = components["schemas"]["MeResponse"]`, `nextRoute(me): "/mfa" | "/change-password" | "/projects"`, `roleLabel(me): string`.
  - `src/lib/session/SessionProvider.tsx`: `SessionProvider` (loads `/auth/me` once; 401 → `/login`; `nextRoute(me) !== "/projects"` → that route; otherwise renders children), `useSession(): { me, refresh, logout }`, `SessionContext`, `type Session`.
  - `src/lib/hooks/useLoad.ts`: `useLoad<T>(load: () => Promise<T>, deps: readonly unknown[]): { data: T | undefined; error: string | null; loading: boolean; reload(): void }`.
  - `src/components/shell/AppShell.tsx`: header (app name, nav Projects / Admin for admins, display name, role badge, Change password link, Log out) + `<main>`.
  - Layouts: `(app)/layout.tsx` = `SessionProvider` + `AppShell`; `(app)/admin/layout.tsx` = `notFound()` for non-admins + tabs Users / Storage; `(auth)/layout.tsx` = centred card.
  - `src/test/session.tsx`: `adminMe`, `memberMe`, `customerMe` fixtures and `withSession(ui, me?, overrides?) -> { element, session }`.

- [ ] **Step 1: Generate the client types**

Add to `scripts` in `frontend/package.json`:

```json
    "api:generate": "openapi-typescript openapi.json -o src/lib/api/schema.d.ts",
    "api:check": "pnpm api:generate && git diff --exit-code -- src/lib/api/schema.d.ts"
```

Run: `pnpm api:generate`
Expected: `🚀 openapi.json → src/lib/api/schema.d.ts`; the file exports `paths`, `components`, `operations`. Commit it with the task (it is regenerated after every wave merge).

- [ ] **Step 2: Write the failing client, error and route tests**

`frontend/src/lib/api/client.test.ts`:

```ts
import { afterEach, expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { api, setUnauthorizedHandler } from "./client";

afterEach(() => setUnauthorizedHandler(null));

it("adds the CSRF header to non-GET requests only and sends JSON", async () => {
  const f = mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      body: { mfa_enrolled: false, must_change_password: true },
    },
    { path: "/api/v1/projects", body: [] },
  ]);
  const { data } = await api.POST("/api/v1/auth/login", {
    body: { email: "a@example.com", password: "pw" },
  });
  await api.GET("/api/v1/projects");
  expect(data?.must_change_password).toBe(true);
  expect(f.calls[0].headers.get("X-QC-Agent")).toBe("1");
  expect(f.calls[0].headers.get("content-type")).toBe("application/json");
  expect(f.calls[0].url).toBe("http://localhost:3000/api/v1/auth/login");
  expect(f.calls[1].headers.get("X-QC-Agent")).toBeNull();
});

it("fills path parameters", async () => {
  const f = mockFetch([{ path: "/api/v1/projects/abc", body: {} }]);
  await api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: "abc" } } });
  expect(new URL(f.calls[0].url).pathname).toBe("/api/v1/projects/abc");
});

it("test_401_outside_auth_calls_the_unauthorized_handler", async () => {
  mockFetch([{ path: "/api/v1/projects", status: 401, body: { detail: "Not authenticated." } }]);
  const handler = vi.fn();
  setUnauthorizedHandler(handler);
  const { data, response } = await api.GET("/api/v1/projects");
  expect(response.status).toBe(401);
  expect(data).toBeUndefined();
  expect(handler).toHaveBeenCalledTimes(1);
});

it("test_401_from_auth_endpoints_does_not_redirect", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      status: 401,
      body: { detail: "Invalid e-mail or password." },
    },
  ]);
  const handler = vi.fn();
  setUnauthorizedHandler(handler);
  const { error } = await api.POST("/api/v1/auth/login", {
    body: { email: "a@example.com", password: "wrong" },
  });
  expect((error as unknown as { detail: string }).detail).toBe("Invalid e-mail or password.");
  expect(handler).not.toHaveBeenCalled();
});

it("returns undefined data for 204 responses", async () => {
  mockFetch([{ method: "POST", path: "/api/v1/auth/logout", status: 204 }]);
  const { data, error, response } = await api.POST("/api/v1/auth/logout");
  expect(response.status).toBe(204);
  expect(data).toBeUndefined();
  expect(error).toBeUndefined();
});
```

`frontend/src/lib/api/errors.test.ts`:

```ts
import { expect, it } from "vitest";
import { apiErrorMessage, unwrap } from "./errors";

it("reads string, list and pydantic details, else the fallback", () => {
  expect(apiErrorMessage({ detail: "Too many attempts. Try again later." }, "x")).toBe(
    "Too many attempts. Try again later.",
  );
  expect(apiErrorMessage({ detail: ["Too short.", "Add a digit."] }, "x")).toBe(
    "Too short. Add a digit.",
  );
  expect(
    apiErrorMessage(
      { detail: [{ loc: ["body", "name"], msg: "Value error, Project name is required." }] },
      "x",
    ),
  ).toBe("Value error, Project name is required.");
  expect(apiErrorMessage(undefined, "Fallback")).toBe("Fallback");
  expect(apiErrorMessage({ detail: [] }, "Fallback")).toBe("Fallback");
  expect(apiErrorMessage("boom", "Fallback")).toBe("Fallback");
});

it("unwrap returns data or throws the API message", () => {
  expect(unwrap({ data: [1], error: undefined })).toEqual([1]);
  expect(() => unwrap({ data: undefined, error: { detail: "Project not found." } })).toThrow(
    "Project not found.",
  );
  expect(() => unwrap({ data: undefined, error: undefined }, "Nope")).toThrow("Nope");
});
```

`frontend/src/lib/session/next-route.test.ts`:

```ts
import { expect, it } from "vitest";
import { adminMe, customerMe, memberMe } from "@/test/session";
import { nextRoute, roleLabel } from "./next-route";

it("sends unverified sessions to MFA, then to the password change, then to projects", () => {
  expect(nextRoute({ ...memberMe, mfa_verified: false })).toBe("/mfa");
  expect(nextRoute({ ...memberMe, mfa_verified: false, must_change_password: true })).toBe("/mfa");
  expect(nextRoute({ ...memberMe, must_change_password: true })).toBe("/change-password");
  expect(nextRoute(memberMe)).toBe("/projects");
});

it("labels roles", () => {
  expect(roleLabel(adminMe)).toBe("Administrator");
  expect(roleLabel(memberMe)).toBe("Team member");
  expect(roleLabel(customerMe)).toBe("Customer");
});
```

Run: `pnpm test`
Expected: FAIL — `./client`, `./errors`, `./next-route`, `@/test/session` cannot be resolved.

- [ ] **Step 3: Client, errors, routes, test fixtures**

`frontend/src/lib/api/client.ts`:

```ts
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export const CSRF_HEADER = "X-QC-Agent";
const AUTH_PREFIX = "/api/v1/auth/";

let unauthorizedHandler: (() => void) | null = null;

/** Registered by the session provider: a 401 outside /auth/* means the session is gone. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

const csrf: Middleware = {
  onRequest({ request }) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      request.headers.set(CSRF_HEADER, "1");
    }
    return request;
  },
};

const unauthorized: Middleware = {
  onResponse({ request, response }) {
    if (response.status === 401 && !new URL(request.url).pathname.startsWith(AUTH_PREFIX)) {
      unauthorizedHandler?.();
    }
    return response;
  },
};

// Client components also render on the server, where window is undefined; nothing is fetched
// there. In the browser (and jsdom) requests go same-origin through the Next rewrite.
const baseUrl = typeof window === "undefined" ? "http://localhost" : window.location.origin;

export function makeClient(
  fetchImpl: (request: Request) => Promise<Response> = (request) => globalThis.fetch(request),
) {
  const client = createClient<paths>({ baseUrl, fetch: fetchImpl, credentials: "same-origin" });
  client.use(csrf, unauthorized);
  return client;
}

export const api = makeClient();
```

`frontend/src/lib/api/errors.ts`:

```ts
import { m } from "@/messages";

/** Message from a FastAPI error body: `{"detail": "..."}`, `{"detail": ["...", ...]}` or the
 * 422 shape `{"detail": [{"msg": "...", ...}]}`. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return "";
        })
        .filter((part) => part.length > 0);
      if (parts.length > 0) return parts.join(" ");
    }
  }
  return fallback;
}

/** For loaders: the response data, or an Error carrying the API message. */
export function unwrap<T>(
  result: { data?: T; error?: unknown },
  fallback: string = m.common.loadFailed,
): T {
  if (result.data === undefined) throw new Error(apiErrorMessage(result.error, fallback));
  return result.data;
}
```

`frontend/src/lib/session/next-route.ts`:

```ts
import type { components } from "@/lib/api/schema";
import { m } from "@/messages";

export type Me = components["schemas"]["MeResponse"];
export type NextRoute = "/mfa" | "/change-password" | "/projects";

/** Where a signed-in user must go next (spec 13: MFA first, then the forced password change). */
export function nextRoute(me: Me): NextRoute {
  if (!me.mfa_verified) return "/mfa";
  if (me.must_change_password) return "/change-password";
  return "/projects";
}

export function roleLabel(me: Me): string {
  if (me.is_admin) return m.roles.admin;
  return me.account_type === "customer" ? m.roles.customer : m.roles.internal;
}
```

`frontend/src/test/session.tsx`:

```tsx
import type { ReactNode } from "react";
import { vi } from "vitest";
import { SessionContext, type Session } from "@/lib/session/SessionProvider";
import type { Me } from "@/lib/session/next-route";

export const adminMe: Me = {
  id: "00000000-0000-0000-0000-00000000000a",
  email: "root@example.com",
  display_name: "Root",
  account_type: "internal",
  is_admin: true,
  mfa_enabled: true,
  mfa_verified: true,
  must_change_password: false,
};

export const memberMe: Me = {
  ...adminMe,
  id: "00000000-0000-0000-0000-00000000000b",
  email: "alice@example.com",
  display_name: "Alice",
  is_admin: false,
};

export const customerMe: Me = {
  ...memberMe,
  id: "00000000-0000-0000-0000-00000000000c",
  email: "c@client.com",
  display_name: "Cara",
  account_type: "customer",
};

/** Render `ui` inside a ready session without hitting /auth/me. */
export function withSession(ui: ReactNode, me: Me = memberMe, overrides: Partial<Session> = {}) {
  const session: Session = {
    me,
    refresh: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    ...overrides,
  };
  return {
    session,
    element: <SessionContext.Provider value={session}>{ui}</SessionContext.Provider>,
  };
}
```

- [ ] **Step 4: Write the failing provider, hook, shell and admin-guard tests**

`frontend/src/lib/session/SessionProvider.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { adminMe } from "@/test/session";
import { SessionProvider, useSession } from "./SessionProvider";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/projects",
}));

function WhoAmI() {
  const { me } = useSession();
  return <p>Signed in as {me.display_name}</p>;
}

it("renders children once /auth/me reports a complete session", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: adminMe }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  expect(await screen.findByText("Signed in as Root")).toBeInTheDocument();
  expect(replace).not.toHaveBeenCalled();
});

it("sends anonymous users to /login", async () => {
  mockFetch([{ path: "/api/v1/auth/me", status: 401, body: { detail: "Not authenticated." } }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByText(/Signed in/)).not.toBeInTheDocument();
});

it("sends MFA-pending sessions to /mfa and password changes to /change-password", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: { ...adminMe, mfa_verified: false } }]);
  const first = render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/mfa"));
  first.unmount();
  mockFetch([{ path: "/api/v1/auth/me", body: { ...adminMe, must_change_password: true } }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/change-password"));
});

it("shows a retry when /auth/me fails for another reason", async () => {
  mockFetch([{ path: "/api/v1/auth/me", status: 503, body: { detail: "down" } }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load data. Try again.");
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
```

`frontend/src/lib/hooks/useLoad.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { mockFetch } from "@/test/fetch-mock";
import { useLoad } from "./useLoad";

function Probe() {
  const projects = useLoad(() => api.GET("/api/v1/projects").then((r) => unwrap(r)), []);
  if (projects.loading) return <p role="status">loading</p>;
  if (projects.error) return <p role="alert">{projects.error}</p>;
  return <p>{projects.data?.length ?? 0} projects</p>;
}

it("exposes loading, then data", async () => {
  mockFetch([{ path: "/api/v1/projects", body: [{ id: "p1" }] }]);
  render(<Probe />);
  expect(screen.getByRole("status")).toHaveTextContent("loading");
  expect(await screen.findByText("1 projects")).toBeInTheDocument();
});

it("exposes the API error message", async () => {
  mockFetch([{ path: "/api/v1/projects", status: 503, body: { detail: "Storage is unavailable." } }]);
  render(<Probe />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Storage is unavailable.");
});
```

`frontend/src/components/shell/AppShell.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { adminMe, memberMe } from "@/test/session";
import { SessionProvider } from "@/lib/session/SessionProvider";
import { AppShell } from "./AppShell";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/projects",
}));

function renderShell() {
  return render(
    <SessionProvider>
      <AppShell>
        <p>Page content</p>
      </AppShell>
    </SessionProvider>,
  );
}

it("shows the user, the role badge and the admin link for administrators", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: adminMe }]);
  renderShell();
  expect(await screen.findByText("Page content")).toBeInTheDocument();
  expect(screen.getByText("Root")).toBeInTheDocument();
  expect(screen.getByText("Administrator")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin/users");
  expect(screen.getByRole("link", { name: "Projects" })).toHaveAttribute("aria-current", "page");
});

it("hides the admin link from team members and logs out", async () => {
  const f = mockFetch([
    { path: "/api/v1/auth/me", body: memberMe },
    { method: "POST", path: "/api/v1/auth/logout", status: 204 },
  ]);
  renderShell();
  expect(await screen.findByText("Team member")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Log out" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(f.find("POST", "/api/v1/auth/logout")).toBeDefined();
});
```

`frontend/src/app/(app)/admin/layout.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { adminMe, memberMe, withSession } from "@/test/session";
import AdminLayout from "./layout";

const { notFound } = vi.hoisted(() => ({ notFound: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound,
  usePathname: () => "/admin/users",
}));

it("renders the admin tabs for administrators", () => {
  render(withSession(<AdminLayout>child</AdminLayout>, adminMe).element);
  expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/admin/users");
  expect(screen.getByRole("link", { name: "Storage" })).toHaveAttribute("href", "/admin/storage");
  expect(notFound).not.toHaveBeenCalled();
});

it("shows the not-found page to everyone else", () => {
  render(withSession(<AdminLayout>child</AdminLayout>, memberMe).element);
  expect(notFound).toHaveBeenCalled();
});
```

Run: `pnpm test`
Expected: the new files fail to resolve `./SessionProvider`, `./useLoad`, `./AppShell`, `./layout`.

- [ ] **Step 5: Provider, hook, shell and layouts**

`frontend/src/lib/session/SessionProvider.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { api, setUnauthorizedHandler } from "@/lib/api/client";
import { m } from "@/messages";
import { nextRoute, type Me } from "./next-route";

export type Session = { me: Me; refresh: () => Promise<void>; logout: () => Promise<void> };

export const SessionContext = createContext<Session | null>(null);

/** Route guard for the signed-in area: loads /auth/me once and renders children only for a
 * complete session (MFA verified, no forced password change); otherwise redirects. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { data, response } = await api.GET("/api/v1/auth/me");
      if (!data) {
        if (response.status === 401) router.replace("/login");
        else setError(m.common.loadFailed);
        return;
      }
      const next = nextRoute(data);
      if (next !== "/projects") {
        router.replace(next);
        return;
      }
      setError(null);
      setMe(data);
    } catch {
      setError(m.common.loadFailed);
    }
  }, [router]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setUnauthorizedHandler(() => router.replace("/login"));
    return () => setUnauthorizedHandler(null);
  }, [router]);

  const logout = useCallback(async () => {
    await api.POST("/api/v1/auth/logout");
    router.replace("/login");
  }, [router]);

  if (error) {
    return (
      <div className="p-6">
        <Alert kind="error">
          {error}{" "}
          <Button variant="secondary" onClick={() => void refresh()}>
            {m.common.retry}
          </Button>
        </Alert>
      </div>
    );
  }
  if (!me) {
    return (
      <p role="status" className="p-6 text-muted">
        {m.app.loading}
      </p>
    );
  }
  return (
    <SessionContext.Provider value={{ me, refresh, logout }}>{children}</SessionContext.Provider>
  );
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
```

`frontend/src/lib/hooks/useLoad.ts`:

```ts
"use client";

import { useCallback, useEffect, useState } from "react";
import { m } from "@/messages";

type State<T> = { data: T | undefined; error: string | null; loading: boolean };

/** Run an async loader when `deps` change; loaders throw an Error with the message to show. */
export function useLoad<T>(
  load: () => Promise<T>,
  deps: readonly unknown[],
): State<T> & { reload: () => void } {
  const [state, setState] = useState<State<T>>({ data: undefined, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    load().then(
      (data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      },
      (reason: unknown) => {
        if (cancelled) return;
        const message = reason instanceof Error && reason.message ? reason.message : m.common.loadFailed;
        setState((s) => ({ ...s, error: message, loading: false }));
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `deps` is the caller's dependency list
  }, [...deps, tick]);
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    setTick((t) => t + 1);
  }, []);
  return { ...state, reload };
}
```

`frontend/src/components/shell/AppShell.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cx } from "@/lib/cx";
import { roleLabel } from "@/lib/session/next-route";
import { useSession } from "@/lib/session/SessionProvider";
import { m } from "@/messages";

type NavLink = { href: string; label: string; match: string };

export function AppShell({ children }: { children: ReactNode }) {
  const { me, logout } = useSession();
  const pathname = usePathname();
  const links: NavLink[] = [{ href: "/projects", label: m.nav.projects, match: "/projects" }];
  if (me.is_admin) links.push({ href: "/admin/users", label: m.nav.admin, match: "/admin" });
  return (
    <div className="min-h-full">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <nav aria-label={m.nav.main} className="flex items-center gap-5">
            <Link href="/projects" className="font-semibold">
              {m.app.name}
            </Link>
            {links.map((link) => {
              const current = pathname.startsWith(link.match);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={current ? "page" : undefined}
                  className={cx(
                    "text-sm",
                    current ? "font-semibold text-brand" : "text-muted hover:text-fg",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-3 text-sm">
            <span>{me.display_name}</span>
            <Badge>{roleLabel(me)}</Badge>
            <Link href="/change-password" className="text-muted hover:text-fg">
              {m.nav.changePassword}
            </Link>
            <Button variant="secondary" onClick={() => void logout()}>
              {m.nav.logout}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
```

`frontend/src/app/(app)/layout.tsx`:

```tsx
import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { SessionProvider } from "@/lib/session/SessionProvider";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
```

`frontend/src/app/(app)/admin/layout.tsx`:

```tsx
"use client";

import Link from "next/link";
import { notFound, usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { useSession } from "@/lib/session/SessionProvider";
import { m } from "@/messages";

const tabs = [
  { href: "/admin/users", label: m.nav.users },
  { href: "/admin/storage", label: m.nav.storage },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { me } = useSession();
  const pathname = usePathname();
  if (!me.is_admin) notFound(); // non-admins see the not-found page, not a hint that /admin exists
  return (
    <div>
      <nav aria-label={m.nav.adminSections} className="mb-6 flex gap-4 border-b border-border">
        {tabs.map((tab) => {
          const current = pathname.startsWith(tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={current ? "page" : undefined}
              className={cx(
                "-mb-px border-b-2 px-1 pb-2 text-sm",
                current
                  ? "border-brand font-semibold text-brand"
                  : "border-transparent text-muted hover:text-fg",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
```

`frontend/src/app/(auth)/layout.tsx`:

```tsx
import type { ReactNode } from "react";
import { m } from "@/messages";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 shadow-sm">
        <p className="mb-4 text-sm font-semibold text-muted">{m.app.name}</p>
        {children}
      </div>
    </main>
  );
}
```

- [ ] **Step 6: Run every gate**

```bash
pnpm format:write
pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build
```

Expected: all tests pass (3 from Task 5 + 15 new); `api:check` prints nothing after the generation line (no diff); the build lists `/`, `/_not-found` (no pages exist yet under the groups, so the layouts compile but render nothing).

- [ ] **Step 7: Commit**

```bash
cd ..
git add frontend
git commit -m "feat(frontend): typed API client, session provider, app shell and route guards"
```

### Task 7: Login, MFA enrolment and verification, forced password change

**Files:**
- Create: `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/app/(auth)/mfa/page.tsx`, `frontend/src/app/(auth)/change-password/page.tsx`, `frontend/src/features/auth/LoginForm.tsx`, `frontend/src/features/auth/MfaPage.tsx`, `frontend/src/features/auth/MfaEnrol.tsx`, `frontend/src/features/auth/RecoveryCodes.tsx`, `frontend/src/features/auth/MfaVerify.tsx`, `frontend/src/features/auth/ChangePasswordPage.tsx`, `frontend/src/features/auth/ChangePasswordForm.tsx`
- Test: `frontend/src/features/auth/LoginForm.test.tsx`, `frontend/src/features/auth/MfaEnrol.test.tsx`, `frontend/src/features/auth/MfaVerify.test.tsx`, `frontend/src/features/auth/MfaPage.test.tsx`, `frontend/src/features/auth/ChangePasswordForm.test.tsx`

**Interfaces:**
- Consumes: `api`, `apiErrorMessage`, `nextRoute`, `Me`, UI primitives, `m`, `mockFetch`, `adminMe`/`memberMe` fixtures (Tasks 5, 6); backend `POST /auth/login`, `GET /auth/me`, `POST /auth/mfa/enroll|confirm|verify`, `POST /auth/change-password` (Plan 1).
- Produces: routes `/login`, `/mfa`, `/change-password`; `LoginForm` (success → `router.replace("/mfa")`), `MfaPage` (decides enrolment vs verification from `/auth/me`; verified sessions → `nextRoute(me)`), `MfaEnrol({ onDone(me) })`, `RecoveryCodes({ codes, onAcknowledged })`, `MfaVerify({ onVerified(me) })`, `ChangePasswordPage` (→ `/projects` after success), `ChangePasswordForm({ onChanged })`. Labels the end-to-end suite relies on: "E-mail", "Password", "Sign in", "Setup key (if you cannot scan)", "Authentication code", "Confirm", "Recovery codes" heading with 10 list items, "I have saved my recovery codes", "Continue", "Current password", "New password", "Confirm new password", "Change password".

- [ ] **Step 1: Write the failing tests**

`frontend/src/features/auth/LoginForm.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { LoginForm } from "./LoginForm";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

async function fillAndSubmit(email: string, password: string) {
  await userEvent.type(screen.getByLabelText("E-mail"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it("posts the credentials and continues to the MFA step", async () => {
  const f = mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      body: { mfa_enrolled: false, must_change_password: true },
    },
  ]);
  render(<LoginForm />);
  await fillAndSubmit("alice@example.com", "correct-horse-battery-staple");
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/mfa"));
  expect(await f.body(0)).toEqual({
    email: "alice@example.com",
    password: "correct-horse-battery-staple",
  });
});

it("shows the backend's message for wrong credentials and for rate limiting", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      status: 401,
      body: { detail: "Invalid e-mail or password." },
    },
  ]);
  render(<LoginForm />);
  await fillAndSubmit("alice@example.com", "wrong");
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid e-mail or password.");
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      status: 429,
      body: { detail: "Too many attempts. Try again later." },
    },
  ]);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Try again later.");
  expect(replace).not.toHaveBeenCalled();
});
```

`frontend/src/features/auth/MfaEnrol.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { adminMe } from "@/test/session";
import { MfaEnrol } from "./MfaEnrol";

vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,QR") },
}));

const CODES = Array.from({ length: 10 }, (_, i) => `0000000${i}-abcdef0${i}`);

function routes(confirmStatus = 200) {
  return mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/mfa/enroll",
      body: {
        secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        otpauth_uri: "otpauth://totp/QC-Agent:a%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=QC-Agent",
      },
    },
    {
      method: "POST",
      path: "/api/v1/auth/mfa/confirm",
      status: confirmStatus,
      body: confirmStatus === 200 ? { recovery_codes: CODES } : { detail: "Invalid code." },
    },
    { path: "/api/v1/auth/me", body: adminMe },
  ]);
}

it("shows the QR code and setup key, confirms the code and reveals the recovery codes once", async () => {
  const f = routes();
  const onDone = vi.fn();
  render(<MfaEnrol onDone={onDone} />);
  expect(await screen.findByAltText("QR code for your authenticator app")).toHaveAttribute(
    "src",
    "data:image/png;base64,QR",
  );
  expect(screen.getByLabelText("Setup key (if you cannot scan)")).toHaveValue(
    "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
  );
  await userEvent.type(screen.getByLabelText("Authentication code"), "123456");
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("heading", { name: "Recovery codes" })).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(10);
  expect(await f.body(1)).toEqual({ code: "123456" });
  // test_continue_is_disabled_until_the_codes_are_acknowledged
  const next = screen.getByRole("button", { name: "Continue" });
  expect(next).toBeDisabled();
  await userEvent.click(screen.getByLabelText("I have saved my recovery codes"));
  expect(next).toBeEnabled();
  await userEvent.click(next);
  expect(onDone).toHaveBeenCalledWith(adminMe);
});

it("shows the backend message for a wrong code and stays on the scan step", async () => {
  routes(400);
  render(<MfaEnrol onDone={vi.fn()} />);
  await userEvent.type(await screen.findByLabelText("Authentication code"), "000000");
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid code.");
  expect(screen.queryByRole("heading", { name: "Recovery codes" })).not.toBeInTheDocument();
});
```

`frontend/src/features/auth/MfaVerify.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { memberMe } from "@/test/session";
import { MfaVerify } from "./MfaVerify";

it("rejects a wrong code, then verifies a right one", async () => {
  mockFetch([
    { method: "POST", path: "/api/v1/auth/mfa/verify", status: 401, body: { detail: "Invalid code." } },
  ]);
  const onVerified = vi.fn();
  render(<MfaVerify onVerified={onVerified} />);
  const input = screen.getByLabelText("Authentication or recovery code");
  await userEvent.type(input, "000000");
  await userEvent.click(screen.getByRole("button", { name: "Verify" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid code.");
  expect(onVerified).not.toHaveBeenCalled();
  const f = mockFetch([{ method: "POST", path: "/api/v1/auth/mfa/verify", body: memberMe }]);
  await userEvent.clear(input);
  await userEvent.type(input, "1a2b3c4d-5e6f7a8b");
  await userEvent.click(screen.getByRole("button", { name: "Verify" }));
  expect(await f.body(0)).toEqual({ code: "1a2b3c4d-5e6f7a8b" });
  expect(onVerified).toHaveBeenCalledWith(memberMe);
});
```

`frontend/src/features/auth/MfaPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { memberMe } from "@/test/session";
import { MfaPage } from "./MfaPage";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn().mockResolvedValue("data:,qr") } }));

it("offers enrolment when MFA is not enabled yet", async () => {
  mockFetch([
    { path: "/api/v1/auth/me", body: { ...memberMe, mfa_enabled: false, mfa_verified: false } },
    { method: "POST", path: "/api/v1/auth/mfa/enroll", body: { secret: "S", otpauth_uri: "otpauth://x" } },
  ]);
  render(<MfaPage />);
  expect(await screen.findByLabelText("Setup key (if you cannot scan)")).toHaveValue("S");
});

it("asks for a code when MFA is enabled", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: { ...memberMe, mfa_verified: false } }]);
  render(<MfaPage />);
  expect(await screen.findByLabelText("Authentication or recovery code")).toBeInTheDocument();
});

it("skips ahead when the session is already verified, and to /login when anonymous", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: { ...memberMe, must_change_password: true } }]);
  const first = render(<MfaPage />);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/change-password"));
  first.unmount();
  mockFetch([{ path: "/api/v1/auth/me", status: 401, body: { detail: "Not authenticated." } }]);
  render(<MfaPage />);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
});
```

`frontend/src/features/auth/ChangePasswordForm.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { ChangePasswordForm } from "./ChangePasswordForm";

async function fill(current: string, next: string, confirm: string) {
  await userEvent.type(screen.getByLabelText("Current password"), current);
  await userEvent.type(screen.getByLabelText("New password"), next);
  await userEvent.type(screen.getByLabelText("Confirm new password"), confirm);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
}

it("refuses mismatching passwords without calling the API", async () => {
  const f = mockFetch([]);
  render(<ChangePasswordForm onChanged={vi.fn()} />);
  await fill("temp-password-123", "new-password-abcdef", "new-password-abcdeg");
  expect(await screen.findByRole("alert")).toHaveTextContent("The new passwords do not match.");
  expect(f.fn).not.toHaveBeenCalled();
});

it("submits and reports success, or shows every policy message", async () => {
  const f = mockFetch([{ method: "POST", path: "/api/v1/auth/change-password", status: 204 }]);
  const onChanged = vi.fn();
  render(<ChangePasswordForm onChanged={onChanged} />);
  await fill("temp-password-123", "new-password-abcdef", "new-password-abcdef");
  expect(await f.body(0)).toEqual({
    current_password: "temp-password-123",
    new_password: "new-password-abcdef",
  });
  expect(onChanged).toHaveBeenCalled();
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/change-password",
      status: 400,
      body: { detail: ["Use at least 12 characters.", "Current password is incorrect."] },
    },
  ]);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Use at least 12 characters. Current password is incorrect.",
  );
});
```

Run: `pnpm test src/features/auth`
Expected: FAIL — the five component modules do not exist.

- [ ] **Step 2: Components**

`frontend/src/features/auth/LoginForm.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/login", {
        body: { email, password },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.auth.loginFailed));
        return;
      }
      router.replace("/mfa"); // enrolment or verification: the MFA page decides
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <h1 className="text-lg font-semibold">{m.auth.loginTitle}</h1>
      {error ? <Alert kind="error">{error}</Alert> : null}
      <Field
        label={m.auth.email}
        type="email"
        autoComplete="username"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Field
        label={m.auth.password}
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Button type="submit" busy={busy} className="w-full">
        {m.auth.signIn}
      </Button>
    </form>
  );
}
```

`frontend/src/features/auth/MfaPage.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { api } from "@/lib/api/client";
import { nextRoute, type Me } from "@/lib/session/next-route";
import { m } from "@/messages";
import { MfaEnrol } from "./MfaEnrol";
import { MfaVerify } from "./MfaVerify";

/** Second step after the password: enrol (first sign-in) or verify, then continue. */
export function MfaPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.GET("/api/v1/auth/me").then(
      ({ data, response }) => {
        if (cancelled) return;
        if (!data) {
          if (response.status === 401) router.replace("/login");
          else setError(m.common.loadFailed);
          return;
        }
        if (data.mfa_verified) {
          router.replace(nextRoute(data));
          return;
        }
        setMe(data);
      },
      () => {
        if (!cancelled) setError(m.common.loadFailed);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [router]);

  const done = (verified: Me) => router.replace(nextRoute(verified));

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!me) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">{m.auth.mfaTitle}</h1>
      {me.mfa_enabled ? <MfaVerify onVerified={done} /> : <MfaEnrol onDone={done} />}
    </div>
  );
}
```

`frontend/src/features/auth/MfaEnrol.tsx`:

```tsx
"use client";

import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { Me } from "@/lib/session/next-route";
import { m } from "@/messages";
import { RecoveryCodes } from "./RecoveryCodes";

type Step =
  | { kind: "loading" }
  | { kind: "scan"; secret: string; qr: string | null }
  | { kind: "codes"; codes: string[] };

export function MfaEnrol({ onDone }: { onDone: (me: Me) => void }) {
  const [step, setStep] = useState<Step>({ kind: "loading" });
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      const { data, error: apiError } = await api.POST("/api/v1/auth/mfa/enroll");
      if (cancelled) return;
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      let qr: string | null = null;
      try {
        qr = await QRCode.toDataURL(data.otpauth_uri, { width: 192, margin: 1 });
      } catch {
        qr = null; // the setup key below still works
      }
      if (!cancelled) setStep({ kind: "scan", secret: data.secret, qr });
    }
    start().catch(() => {
      if (!cancelled) setError(m.common.requestFailed);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/mfa/confirm", {
        body: { code },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.auth.invalidCode));
        return;
      }
      setStep({ kind: "codes", codes: data.recovery_codes });
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    const { data } = await api.GET("/api/v1/auth/me");
    if (data) onDone(data);
  }

  if (step.kind === "codes") {
    return <RecoveryCodes codes={step.codes} onAcknowledged={() => void finish()} />;
  }
  return (
    <form onSubmit={(event) => void confirm(event)} className="space-y-4">
      <p className="text-sm text-muted">{m.auth.enrolIntro}</p>
      {error ? <Alert kind="error">{error}</Alert> : null}
      {step.kind === "loading" ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : (
        <>
          {step.qr ? (
            // eslint-disable-next-line @next/next/no-img-element -- a data URL; next/image adds nothing
            <img
              src={step.qr}
              alt={m.auth.qrAlt}
              width={192}
              height={192}
              className="rounded border border-border bg-white p-2"
            />
          ) : null}
          <Field
            label={m.auth.setupKey}
            readOnly
            value={step.secret}
            className="font-mono"
            onFocus={(event) => event.currentTarget.select()}
          />
          <Field
            label={m.auth.code}
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <Button type="submit" busy={busy} className="w-full">
            {m.auth.confirm}
          </Button>
        </>
      )}
    </form>
  );
}
```

`frontend/src/features/auth/RecoveryCodes.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { m } from "@/messages";

/** Shown exactly once, right after enrolment; nothing is persisted on the client. */
export function RecoveryCodes({
  codes,
  onAcknowledged,
}: {
  codes: string[];
  onAcknowledged: () => void;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n") + "\n";

  async function copy() {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(text);
    setCopied(true);
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "qc-agent-recovery-codes.txt";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold">{m.auth.recoveryTitle}</h2>
      <p className="text-sm text-muted">{m.auth.recoveryIntro}</p>
      <ul className="grid grid-cols-2 gap-1 rounded-md border border-border bg-bg p-3 font-mono text-sm">
        {codes.map((recoveryCode) => (
          <li key={recoveryCode}>{recoveryCode}</li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button variant="secondary" onClick={() => void copy()}>
          {copied ? m.common.copied : m.auth.copyCodes}
        </Button>
        <Button variant="secondary" onClick={download}>
          {m.auth.downloadCodes}
        </Button>
      </div>
      <Checkbox
        label={m.auth.recoveryAck}
        checked={acknowledged}
        onChange={(event) => setAcknowledged(event.target.checked)}
      />
      <Button className="w-full" disabled={!acknowledged} onClick={onAcknowledged}>
        {m.auth.continue}
      </Button>
    </div>
  );
}
```

`frontend/src/features/auth/MfaVerify.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { Me } from "@/lib/session/next-route";
import { m } from "@/messages";

export function MfaVerify({ onVerified }: { onVerified: (me: Me) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/mfa/verify", {
        body: { code },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.auth.invalidCode));
        return;
      }
      onVerified(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <p className="text-sm text-muted">{m.auth.verifyIntro}</p>
      {error ? <Alert kind="error">{error}</Alert> : null}
      <Field
        label={m.auth.codeOrRecovery}
        autoComplete="one-time-code"
        required
        value={code}
        onChange={(event) => setCode(event.target.value)}
      />
      <Button type="submit" busy={busy} className="w-full">
        {m.auth.verify}
      </Button>
    </form>
  );
}
```

`frontend/src/features/auth/ChangePasswordPage.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { api } from "@/lib/api/client";
import { m } from "@/messages";
import { ChangePasswordForm } from "./ChangePasswordForm";

/** Reachable after MFA; the forced change (must_change_password) lands here through the
 * session provider, voluntary changes through the header link. */
export function ChangePasswordPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.GET("/api/v1/auth/me").then(
      ({ data, response }) => {
        if (cancelled) return;
        if (!data) {
          if (response.status === 401) router.replace("/login");
          else setError(m.common.loadFailed);
          return;
        }
        if (!data.mfa_verified) {
          router.replace("/mfa");
          return;
        }
        setReady(true);
      },
      () => {
        if (!cancelled) setError(m.common.loadFailed);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!ready) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  return <ChangePasswordForm onChanged={() => router.replace("/projects")} />;
}
```

`frontend/src/features/auth/ChangePasswordForm.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";

export function ChangePasswordForm({ onChanged }: { onChanged: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (next !== confirm) {
      setError(m.auth.passwordsDiffer);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { response, error: apiError } = await api.POST("/api/v1/auth/change-password", {
        body: { current_password: current, new_password: next },
      });
      if (!response.ok) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onChanged();
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <h1 className="text-lg font-semibold">{m.auth.changePasswordTitle}</h1>
      <p className="text-sm text-muted">{m.auth.changePasswordIntro}</p>
      {error ? <Alert kind="error">{error}</Alert> : null}
      <Field
        label={m.auth.currentPassword}
        type="password"
        autoComplete="current-password"
        required
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
      />
      <Field
        label={m.auth.newPassword}
        type="password"
        autoComplete="new-password"
        required
        minLength={12}
        value={next}
        onChange={(event) => setNext(event.target.value)}
      />
      <Field
        label={m.auth.confirmPassword}
        type="password"
        autoComplete="new-password"
        required
        minLength={12}
        value={confirm}
        onChange={(event) => setConfirm(event.target.value)}
      />
      <Button type="submit" busy={busy} className="w-full">
        {m.auth.changePasswordAction}
      </Button>
    </form>
  );
}
```

Pages — `frontend/src/app/(auth)/login/page.tsx`:

```tsx
import { LoginForm } from "@/features/auth/LoginForm";

export default function LoginPage() {
  return <LoginForm />;
}
```

`frontend/src/app/(auth)/mfa/page.tsx`:

```tsx
import { MfaPage } from "@/features/auth/MfaPage";

export default function Page() {
  return <MfaPage />;
}
```

`frontend/src/app/(auth)/change-password/page.tsx`:

```tsx
import { ChangePasswordPage } from "@/features/auth/ChangePasswordPage";

export default function Page() {
  return <ChangePasswordPage />;
}
```

- [ ] **Step 3: Run every gate**

```bash
pnpm format:write
pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build
```

Expected: all tests pass (8 new); the build lists `/login`, `/mfa`, `/change-password` as static routes.

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend
git commit -m "feat(frontend): login, MFA enrolment and verification, password change screens"
```

### Task 8: Projects list, create-project dialog, project overview with members, settings and consent

**Files:**
- Create: `frontend/src/app/(app)/projects/page.tsx`, `frontend/src/app/(app)/projects/[projectId]/page.tsx`, `frontend/src/features/projects/types.ts`, `frontend/src/features/projects/ProjectsPage.tsx`, `frontend/src/features/projects/CreateProjectDialog.tsx`, `frontend/src/features/projects/ProjectPage.tsx`, `frontend/src/features/projects/ConsentForm.tsx`, `frontend/src/features/projects/MembersPanel.tsx`, `frontend/src/features/projects/SettingsPanel.tsx`
- Test: `frontend/src/features/projects/ProjectsPage.test.tsx`, `frontend/src/features/projects/CreateProjectDialog.test.tsx`, `frontend/src/features/projects/ProjectPage.test.tsx`, `frontend/src/features/projects/MembersPanel.test.tsx`, `frontend/src/features/projects/SettingsPanel.test.tsx`

**Interfaces:**
- Consumes: `api`, `unwrap`, `apiErrorMessage`, `useLoad`, `useSession`, UI primitives, `m`, `roleName`, `mockFetch`, `withSession` + fixtures (Tasks 5, 6); backend `GET/POST /projects`, `GET/PATCH /projects/{id}`, `GET/PUT /projects/{id}/members`, `POST /projects/{id}/llm-consent`, `GET /storage-connections/available`, `GET /users/directory` (Tasks 2, 3; regenerated `schema.d.ts`).
- Produces: routes `/projects`, `/projects/[projectId]`; `types.ts` exporting `Project`, `Member`, `Role`, `AvailableConnection`, `DirectoryEntry`, `INTERNAL_ROLES`; `ProjectsPage`, `CreateProjectDialog({ onClose, onCreated(project) })`, `ProjectPage({ projectId })`, `ConsentForm({ projectId, onRecorded })`, `MembersPanel({ projectId, canEdit })`, `SettingsPanel({ project, onUpdated(project) })`. Labels the end-to-end suite relies on: "New project", "Project name", "Client name", "Storage connection", "Root folder (optional)", "Create project", tabs "Overview" / "Members" / "Settings", "Name of the confirming person", "Record customer confirmation", "User", "Role", "Add member", "Save members", status "Members saved.".

- [ ] **Step 1: Shared types**

`frontend/src/features/projects/types.ts`:

```ts
import type { components } from "@/lib/api/schema";

export type Project = components["schemas"]["ProjectOut"];
export type Member = components["schemas"]["MemberOut"];
export type Role = components["schemas"]["MemberIn"]["role"];
export type AvailableConnection = components["schemas"]["StorageConnectionAvailable"];
export type DirectoryEntry = components["schemas"]["UserDirectoryEntry"];

export const INTERNAL_ROLES = ["owner", "editor", "viewer"] as const;
export const ROLES: Role[] = ["owner", "editor", "viewer", "client"];
```

- [ ] **Step 2: Write the failing tests**

`frontend/src/features/projects/ProjectsPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { customerMe, memberMe, withSession } from "@/test/session";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const project = {
  id: "11111111-1111-1111-1111-111111111111",
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: "owner",
  settings: null,
  storage: null,
  llm_consent: null,
};

it("lists projects with a link and offers creation to internal users", async () => {
  mockFetch([{ path: "/api/v1/projects", body: [project] }]);
  render(withSession(<ProjectsPage />, memberMe).element);
  expect(await screen.findByRole("link", { name: "Demo" })).toHaveAttribute(
    "href",
    "/projects/11111111-1111-1111-1111-111111111111",
  );
  expect(screen.getByText("ACME")).toBeInTheDocument();
  expect(screen.getByText("Owner")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New project" })).toBeInTheDocument();
});

it("shows an empty state and no create button to customers", async () => {
  mockFetch([{ path: "/api/v1/projects", body: [] }]);
  render(withSession(<ProjectsPage />, customerMe).element);
  expect(await screen.findByText("You are not a member of any project yet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "New project" })).not.toBeInTheDocument();
});
```

`frontend/src/features/projects/CreateProjectDialog.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { CreateProjectDialog } from "./CreateProjectDialog";

const connections = [
  { id: "c-archive", name: "Archive", type: "localfs", is_default: false },
  { id: "c-default", name: "Local storage", type: "localfs", is_default: true },
];

it("preselects the default connection and posts the chosen values", async () => {
  const f = mockFetch([
    { path: "/api/v1/storage-connections/available", body: connections },
    { method: "POST", path: "/api/v1/projects", status: 201, body: { id: "p1", name: "Portal" } },
  ]);
  const onCreated = vi.fn();
  render(<CreateProjectDialog onClose={vi.fn()} onCreated={onCreated} />);
  const select = await screen.findByLabelText("Storage connection");
  expect(select).toHaveValue("c-default");
  await userEvent.type(screen.getByLabelText("Project name"), "Portal");
  await userEvent.type(screen.getByLabelText("Client name"), "ACME");
  await userEvent.selectOptions(select, "c-archive");
  await userEvent.type(screen.getByLabelText("Root folder (optional)"), "portal-2026");
  await userEvent.click(screen.getByRole("button", { name: "Create project" }));
  expect(await f.body(1)).toEqual({
    name: "Portal",
    client_name: "ACME",
    storage_connection_id: "c-archive",
    storage_root: "portal-2026",
  });
  expect(onCreated).toHaveBeenCalledWith({ id: "p1", name: "Portal" });
});

it("shows the backend's validation message", async () => {
  mockFetch([
    { path: "/api/v1/storage-connections/available", body: connections },
    {
      method: "POST",
      path: "/api/v1/projects",
      status: 422,
      body: { detail: "This root folder is already used by another project on the selected connection." },
    },
  ]);
  render(<CreateProjectDialog onClose={vi.fn()} onCreated={vi.fn()} />);
  await userEvent.type(await screen.findByLabelText("Project name"), "Portal");
  await userEvent.click(screen.getByRole("button", { name: "Create project" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already used by another project");
  expect(screen.getByText("What is the LLM data-processing confirmation?")).toBeInTheDocument();
});
```

`frontend/src/features/projects/ProjectPage.test.tsx`:

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

it("shows storage to internal roles and lets an owner record the consent", async () => {
  const consent = { confirmed_by_name: "Customer Rep", confirmed_at: "2026-10-01T11:00:00+00:00" };
  let recorded = false; // the page reloads the project after recording
  const f = mockFetch([
    { path: `/api/v1/projects/${PID}`, handler: () => ({ ...base, llm_consent: recorded ? consent : null }) },
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
  expect(screen.getByText("Archive")).toBeInTheDocument();
  expect(screen.getByText("localfs")).toBeInTheDocument();
  expect(screen.getByText("demo")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Members" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Settings" })).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Name of the confirming person"), "Customer Rep");
  await userEvent.click(screen.getByRole("button", { name: "Record customer confirmation" }));
  expect(await screen.findByText(/Confirmed by Customer Rep on/)).toBeInTheDocument();
  expect(await f.body(1)).toEqual({ confirmed_by_name: "Customer Rep" });
});

it("hides storage, members and settings from clients and viewers see no settings tab", async () => {
  mockFetch([
    {
      path: `/api/v1/projects/${PID}`,
      body: { ...base, my_role: "client", settings: null, storage: null },
    },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, customerMe).element);
  expect(await screen.findByRole("heading", { name: "Demo" })).toBeInTheDocument();
  expect(screen.queryByText("Archive")).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Members" })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Settings" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Name of the confirming person")).not.toBeInTheDocument();
  expect(screen.getByText(/Not confirmed yet/)).toBeInTheDocument();
});

it("reports an unknown project", async () => {
  mockFetch([{ path: `/api/v1/projects/${PID}`, status: 404, body: { detail: "Project not found." } }]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Project not found.");
});
```

`frontend/src/features/projects/MembersPanel.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { MembersPanel } from "./MembersPanel";

const PID = "11111111-1111-1111-1111-111111111111";
const owner = {
  user_id: "u-owner",
  email: "owner@example.com",
  display_name: "Owner",
  account_type: "internal",
  role: "owner",
};
const directory = [
  { id: "u-owner", email: "owner@example.com", display_name: "Owner", account_type: "internal" },
  { id: "u-ed", email: "editor@example.com", display_name: "Editor", account_type: "internal" },
  { id: "u-cara", email: "c@client.com", display_name: "Cara", account_type: "customer" },
];

it("adds a member, forces customers to the client role and saves the full list", async () => {
  const f = mockFetch([
    { path: `/api/v1/projects/${PID}/members`, body: [owner] },
    { path: "/api/v1/users/directory", body: directory },
    {
      method: "PUT",
      path: `/api/v1/projects/${PID}/members`,
      body: [owner, { ...directory[2], user_id: "u-cara", role: "client" }],
    },
  ]);
  render(<MembersPanel projectId={PID} canEdit />);
  expect(await screen.findByRole("cell", { name: "Owner" })).toBeInTheDocument();
  const picker = screen.getByLabelText("User");
  expect(within(picker).queryByRole("option", { name: /owner@example.com/ })).toBeNull();
  await userEvent.selectOptions(picker, "u-cara");
  const roleSelect = screen.getByLabelText("Role");
  expect(roleSelect).toHaveValue("client");
  expect(roleSelect).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Add member" }));
  expect(screen.getByRole("cell", { name: "Cara" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Save members" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Members saved.");
  expect(await f.body(2)).toEqual([
    { user_id: "u-owner", role: "owner" },
    { user_id: "u-cara", role: "client" },
  ]);
});

it("is read-only for non-owners and surfaces a 422", async () => {
  mockFetch([
    { path: `/api/v1/projects/${PID}/members`, body: [owner] },
    { path: "/api/v1/users/directory", body: directory },
    {
      method: "PUT",
      path: `/api/v1/projects/${PID}/members`,
      status: 422,
      body: { detail: "A project needs at least one owner." },
    },
  ]);
  const readOnly = render(<MembersPanel projectId={PID} canEdit={false} />);
  expect(await screen.findByRole("cell", { name: "Owner" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save members" })).not.toBeInTheDocument();
  readOnly.unmount();
  render(<MembersPanel projectId={PID} canEdit />);
  await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
  await userEvent.click(screen.getByRole("button", { name: "Save members" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("A project needs at least one owner.");
});
```

`frontend/src/features/projects/SettingsPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { SettingsPanel } from "./SettingsPanel";

const PID = "11111111-1111-1111-1111-111111111111";
const project = {
  id: PID,
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: "owner",
  settings: { model: "claude-opus-5", check_budget_usd: 1, normalize_budget_usd: 2 },
  storage: null,
  llm_consent: null,
};

it("patches name, client and settings", async () => {
  const updated = { ...project, name: "Demo 2", settings: { ...project.settings, check_budget_usd: 0.5 } };
  const f = mockFetch([{ method: "PATCH", path: `/api/v1/projects/${PID}`, body: updated }]);
  const onUpdated = vi.fn();
  render(<SettingsPanel project={project} onUpdated={onUpdated} />);
  const name = screen.getByLabelText("Project name");
  await userEvent.clear(name);
  await userEvent.type(name, "Demo 2");
  const budget = screen.getByLabelText("Type-check budget (USD)");
  await userEvent.clear(budget);
  await userEvent.type(budget, "0.5");
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Settings saved.");
  expect(await f.body(0)).toEqual({
    name: "Demo 2",
    client_name: "ACME",
    settings: { model: "claude-opus-5", check_budget_usd: 0.5, normalize_budget_usd: 2 },
  });
  expect(onUpdated).toHaveBeenCalledWith(updated);
});
```

Run: `pnpm test src/features/projects`
Expected: FAIL — the component modules do not exist.

- [ ] **Step 3: Components**

`frontend/src/features/projects/ProjectsPage.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { useSession } from "@/lib/session/SessionProvider";
import { m, roleName } from "@/messages";
import { CreateProjectDialog } from "./CreateProjectDialog";

export function ProjectsPage() {
  const { me } = useSession();
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const projects = useLoad(() => api.GET("/api/v1/projects").then((r) => unwrap(r)), []);

  return (
    <>
      <PageHeader
        title={m.projects.title}
        actions={
          me.account_type === "internal" ? (
            <Button onClick={() => setCreating(true)}>{m.projects.newProject}</Button>
          ) : null
        }
      />
      {projects.error ? (
        <Alert kind="error">
          {projects.error}{" "}
          <Button variant="secondary" onClick={projects.reload}>
            {m.common.retry}
          </Button>
        </Alert>
      ) : null}
      {projects.loading ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : projects.data && projects.data.length === 0 ? (
        <p className="text-muted">{m.projects.empty}</p>
      ) : projects.data ? (
        <Table caption={m.projects.title}>
          <thead>
            <tr>
              <Th>{m.projects.name}</Th>
              <Th>{m.projects.client}</Th>
              <Th>{m.projects.myRole}</Th>
              <Th>{m.projects.created}</Th>
            </tr>
          </thead>
          <tbody>
            {projects.data.map((project) => (
              <tr key={project.id}>
                <Td>
                  <Link href={`/projects/${project.id}`} className="font-medium text-brand">
                    {project.name}
                  </Link>
                </Td>
                <Td>{project.client_name ?? m.common.none}</Td>
                <Td>{roleName(project.my_role)}</Td>
                <Td>{new Date(project.created_at).toLocaleDateString("en-GB")}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      {creating ? (
        <CreateProjectDialog
          onClose={() => setCreating(false)}
          onCreated={(project) => router.push(`/projects/${project.id}`)}
        />
      ) : null}
    </>
  );
}
```

`frontend/src/features/projects/CreateProjectDialog.tsx`:

```tsx
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { AvailableConnection, Project } from "./types";

type Props = { onClose: () => void; onCreated: (project: Project) => void };

export function CreateProjectDialog({ onClose, onCreated }: Props) {
  const [connections, setConnections] = useState<AvailableConnection[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [name, setName] = useState("");
  const [clientName, setClientName] = useState("");
  const [root, setRoot] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.GET("/api/v1/storage-connections/available").then(
      ({ data, error: apiError }) => {
        if (cancelled) return;
        if (!data) {
          setError(apiErrorMessage(apiError, m.common.loadFailed));
          return;
        }
        setConnections(data);
        setConnectionId(data.find((c) => c.is_default)?.id ?? data[0]?.id ?? "");
      },
      () => {
        if (!cancelled) setError(m.common.loadFailed);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/projects", {
        body: {
          name,
          client_name: clientName.trim() || null,
          storage_connection_id: connectionId || null,
          storage_root: root.trim() || null,
        },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onCreated(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={m.projects.newProject} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <Field
          label={m.projects.name}
          required
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Field
          label={m.projects.clientName}
          maxLength={200}
          value={clientName}
          onChange={(event) => setClientName(event.target.value)}
        />
        <Select
          label={m.projects.storageConnection}
          required
          value={connectionId}
          onChange={(event) => setConnectionId(event.target.value)}
        >
          {connections.map((connection) => (
            <option key={connection.id} value={connection.id}>
              {connection.name} ({m.storage.typeLabels[connection.type] ?? connection.type})
            </option>
          ))}
        </Select>
        <Field
          label={m.projects.rootFolder}
          hint={m.projects.rootFolderHint}
          maxLength={80}
          pattern="[A-Za-z0-9][A-Za-z0-9._-]*"
          value={root}
          onChange={(event) => setRoot(event.target.value)}
        />
        <details className="text-sm">
          <summary className="cursor-pointer text-brand">{m.projects.consentLink}</summary>
          <p className="mt-2 text-muted">{m.projects.consentExplain}</p>
        </details>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button type="submit" busy={busy}>
            {m.projects.createAction}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
```

`frontend/src/features/projects/ProjectPage.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { cx } from "@/lib/cx";
import { useLoad } from "@/lib/hooks/useLoad";
import { m, roleName } from "@/messages";
import { ConsentForm } from "./ConsentForm";
import { MembersPanel } from "./MembersPanel";
import { SettingsPanel } from "./SettingsPanel";
import { INTERNAL_ROLES, type Project } from "./types";

type Tab = "overview" | "members" | "settings";

export function ProjectPage({ projectId }: { projectId: string }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [override, setOverride] = useState<Project | null>(null);
  const loaded = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}", { params: { path: { project_id: projectId } } })
        .then((r) => unwrap(r, m.projects.notFound)),
    [projectId],
  );
  const project = override ?? loaded.data;

  if (loaded.error) {
    return (
      <Alert kind="error">
        {loaded.error}{" "}
        <Button variant="secondary" onClick={loaded.reload}>
          {m.common.retry}
        </Button>
      </Alert>
    );
  }
  if (!project) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }

  const internal = (INTERNAL_ROLES as readonly string[]).includes(project.my_role);
  const owner = project.my_role === "owner";
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "overview", label: m.projects.overview, show: true },
    { id: "members", label: m.projects.members, show: internal },
    { id: "settings", label: m.projects.settings, show: owner },
  ];
  const refresh = () => {
    setOverride(null);
    loaded.reload();
  };

  return (
    <>
      <PageHeader title={project.name} />
      <div role="tablist" aria-label={project.name} className="mb-6 flex gap-4 border-b border-border">
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cx(
                "-mb-px border-b-2 px-1 pb-2 text-sm",
                tab === t.id
                  ? "border-brand font-semibold text-brand"
                  : "border-transparent text-muted hover:text-fg",
              )}
            >
              {t.label}
            </button>
          ))}
      </div>
      {tab === "overview" ? (
        <dl className="grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-sm text-muted">{m.projects.client}</dt>
            <dd>{project.client_name ?? m.common.none}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted">{m.projects.myRole}</dt>
            <dd>
              <Badge>{roleName(project.my_role)}</Badge>
            </dd>
          </div>
          {project.storage ? (
            <div className="sm:col-span-2">
              <dt className="text-sm text-muted">{m.projects.storage}</dt>
              <dd className="mt-1 grid grid-cols-3 gap-2 rounded-md border border-border p-3 text-sm">
                <span className="text-muted">{m.projects.connection}</span>
                <span className="text-muted">{m.projects.type}</span>
                <span className="text-muted">{m.projects.root}</span>
                <span>{project.storage.connection_name}</span>
                <span>{project.storage.type}</span>
                <span className="font-mono">{project.storage.root}</span>
              </dd>
            </div>
          ) : null}
          <div className="sm:col-span-2">
            <dt className="text-sm text-muted">{m.projects.consentStatus}</dt>
            <dd className="mt-1 space-y-3">
              {project.llm_consent ? (
                <Alert kind="success">
                  {m.projects.consentRecorded(
                    project.llm_consent.confirmed_by_name,
                    new Date(project.llm_consent.confirmed_at).toLocaleDateString("en-GB"),
                  )}
                </Alert>
              ) : (
                <>
                  <Alert kind="info">{m.projects.consentMissing}</Alert>
                  {owner ? <ConsentForm projectId={project.id} onRecorded={refresh} /> : null}
                </>
              )}
            </dd>
          </div>
        </dl>
      ) : null}
      {tab === "members" ? <MembersPanel projectId={project.id} canEdit={owner} /> : null}
      {tab === "settings" ? <SettingsPanel project={project} onUpdated={setOverride} /> : null}
    </>
  );
}
```

`frontend/src/features/projects/ConsentForm.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";

export function ConsentForm({ projectId, onRecorded }: { projectId: string; onRecorded: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/projects/{project_id}/llm-consent", {
        params: { path: { project_id: projectId } },
        body: { confirmed_by_name: name },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onRecorded();
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="flex max-w-lg items-end gap-2">
      {error ? <Alert kind="error">{error}</Alert> : null}
      <div className="grow">
        <Field
          label={m.projects.confirmedByName}
          required
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <Button type="submit" busy={busy}>
        {m.projects.recordConsent}
      </Button>
    </form>
  );
}
```

`frontend/src/features/projects/MembersPanel.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { apiErrorMessage, unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { m, roleName } from "@/messages";
import { ROLES, type DirectoryEntry, type Member, type Role } from "./types";

type Props = { projectId: string; canEdit: boolean };

export function MembersPanel({ projectId, canEdit }: Props) {
  const members = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}/members", { params: { path: { project_id: projectId } } })
        .then((r) => unwrap(r)),
    [projectId],
  );
  const directory = useLoad(
    () =>
      canEdit
        ? api.GET("/api/v1/users/directory").then((r) => unwrap(r))
        : Promise.resolve([] as DirectoryEntry[]),
    [canEdit],
  );
  const [draft, setDraft] = useState<Member[] | null>(null);
  const [pickedUser, setPickedUser] = useState("");
  const [pickedRole, setPickedRole] = useState<Role>("editor");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const rows = draft ?? members.data ?? [];
  const candidates = (directory.data ?? []).filter((u) => !rows.some((r) => r.user_id === u.id));
  const picked = candidates.find((u) => u.id === pickedUser);
  const pickedIsCustomer = picked?.account_type === "customer";

  function setRole(userId: string, role: Role) {
    setDraft(rows.map((r) => (r.user_id === userId ? { ...r, role } : r)));
    setSaved(false);
  }

  function remove(userId: string) {
    setDraft(rows.filter((r) => r.user_id !== userId));
    setSaved(false);
  }

  function add() {
    if (!picked) return;
    const role: Role = picked.account_type === "customer" ? "client" : pickedRole;
    setDraft([...rows, { ...picked, user_id: picked.id, role }]);
    setPickedUser("");
    setSaved(false);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.PUT("/api/v1/projects/{project_id}/members", {
        params: { path: { project_id: projectId } },
        body: rows.map((r) => ({ user_id: r.user_id, role: r.role as Role })),
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      setDraft(null);
      members.reload();
      setSaved(true);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  if (members.error) return <Alert kind="error">{members.error}</Alert>;
  if (members.loading && !draft) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {saved ? <Alert kind="success">{m.projects.membersSaved}</Alert> : null}
      {rows.length === 0 ? <p className="text-muted">{m.projects.noMembers}</p> : null}
      <Table caption={m.projects.members}>
        <thead>
          <tr>
            <Th>{m.projects.memberName}</Th>
            <Th>{m.projects.memberEmail}</Th>
            <Th>{m.projects.memberType}</Th>
            <Th>{m.projects.memberRole}</Th>
            {canEdit ? <Th>{m.common.actions}</Th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((member) => (
            <tr key={member.user_id}>
              <Td>{member.display_name}</Td>
              <Td>{member.email}</Td>
              <Td>{member.account_type === "customer" ? m.roles.customer : m.roles.internal}</Td>
              <Td>
                {canEdit && member.account_type !== "customer" ? (
                  <select
                    aria-label={`${m.projects.memberRole}: ${member.display_name}`}
                    value={member.role}
                    onChange={(event) => setRole(member.user_id, event.target.value as Role)}
                    className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
                  >
                    {ROLES.filter((r) => r !== "client").map((r) => (
                      <option key={r} value={r}>
                        {roleName(r)}
                      </option>
                    ))}
                  </select>
                ) : (
                  roleName(member.role)
                )}
              </Td>
              {canEdit ? (
                <Td>
                  <Button variant="danger" onClick={() => remove(member.user_id)}>
                    {m.projects.remove}
                  </Button>
                </Td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </Table>
      {canEdit ? (
        <div className="flex flex-wrap items-end gap-2 rounded-md border border-border p-3">
          <div className="min-w-64 grow">
            <Select
              label={m.projects.selectUser}
              value={pickedUser}
              onChange={(event) => setPickedUser(event.target.value)}
            >
              <option value="">—</option>
              {candidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} ({u.email})
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-40">
            <Select
              label={m.projects.memberRole}
              value={pickedIsCustomer ? "client" : pickedRole}
              disabled={pickedIsCustomer}
              onChange={(event) => setPickedRole(event.target.value as Role)}
            >
              {ROLES.filter((r) => (pickedIsCustomer ? r === "client" : r !== "client")).map((r) => (
                <option key={r} value={r}>
                  {roleName(r)}
                </option>
              ))}
            </Select>
          </div>
          <Button variant="secondary" onClick={add} disabled={!picked}>
            {m.projects.addMember}
          </Button>
          <Button onClick={() => void save()} busy={busy} disabled={draft === null}>
            {m.projects.saveMembers}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
```

`frontend/src/features/projects/SettingsPanel.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { Project } from "./types";

type Props = { project: Project; onUpdated: (project: Project) => void };

export function SettingsPanel({ project, onUpdated }: Props) {
  const [name, setName] = useState(project.name);
  const [clientName, setClientName] = useState(project.client_name ?? "");
  const [model, setModel] = useState(project.settings?.model ?? "");
  const [checkBudget, setCheckBudget] = useState(String(project.settings?.check_budget_usd ?? ""));
  const [normalizeBudget, setNormalizeBudget] = useState(
    String(project.settings?.normalize_budget_usd ?? ""),
  );
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/projects/{project_id}", {
        params: { path: { project_id: project.id } },
        body: {
          name,
          client_name: clientName.trim() || null,
          settings: {
            model,
            check_budget_usd: Number(checkBudget),
            normalize_budget_usd: Number(normalizeBudget),
          },
        },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      setSaved(true);
      onUpdated(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="max-w-lg space-y-4">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {saved ? <Alert kind="success">{m.projects.settingsSaved}</Alert> : null}
      <Field
        label={m.projects.name}
        required
        maxLength={200}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <Field
        label={m.projects.clientName}
        maxLength={200}
        value={clientName}
        onChange={(event) => setClientName(event.target.value)}
      />
      <Field
        label={m.projects.model}
        required
        maxLength={100}
        value={model}
        onChange={(event) => setModel(event.target.value)}
      />
      <Field
        label={m.projects.checkBudget}
        type="number"
        step="0.1"
        min="0.1"
        max="50"
        required
        value={checkBudget}
        onChange={(event) => setCheckBudget(event.target.value)}
      />
      <Field
        label={m.projects.normalizeBudget}
        type="number"
        step="0.1"
        min="0.1"
        max="50"
        required
        value={normalizeBudget}
        onChange={(event) => setNormalizeBudget(event.target.value)}
      />
      <Button type="submit" busy={busy}>
        {m.projects.saveSettings}
      </Button>
    </form>
  );
}
```

Pages — `frontend/src/app/(app)/projects/page.tsx`:

```tsx
import { ProjectsPage } from "@/features/projects/ProjectsPage";

export default function Page() {
  return <ProjectsPage />;
}
```

`frontend/src/app/(app)/projects/[projectId]/page.tsx`:

```tsx
import { ProjectPage } from "@/features/projects/ProjectPage";

export default async function Page({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  return <ProjectPage projectId={projectId} />;
}
```

- [ ] **Step 4: Run every gate**

```bash
pnpm format:write
pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build
```

Expected: all tests pass (8 new); the build lists `/projects` (static) and `/projects/[projectId]` (dynamic).

- [ ] **Step 5: Commit**

```bash
cd ..
git add frontend
git commit -m "feat(frontend): projects list, create project with storage choice, project overview"
```

### Task 9: Admin pages — users and storage connections

**Files:**
- Create: `frontend/src/app/(app)/admin/users/page.tsx`, `frontend/src/app/(app)/admin/storage/page.tsx`, `frontend/src/features/admin/types.ts`, `frontend/src/features/admin/UsersAdmin.tsx`, `frontend/src/features/admin/CreateUserDialog.tsx`, `frontend/src/features/admin/TemporaryPasswordDialog.tsx`, `frontend/src/features/admin/StorageAdmin.tsx`, `frontend/src/features/admin/ConnectionDialog.tsx`
- Test: `frontend/src/features/admin/UsersAdmin.test.tsx`, `frontend/src/features/admin/StorageAdmin.test.tsx`

**Interfaces:**
- Consumes: `api`, `unwrap`, `apiErrorMessage`, `useLoad`, UI primitives, `m`, `mockFetch` (Tasks 5, 6); backend `GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/reset-password|reset-mfa` (Plan 1), `GET/POST /storage-connections`, `PATCH /storage-connections/{id}`, `POST /storage-connections/{id}/test` (Task 2).
- Produces: routes `/admin/users`, `/admin/storage`; `UsersAdmin`, `CreateUserDialog({ onClose, onCreated(user, temporaryPassword) })`, `TemporaryPasswordDialog({ email, password, onClose })`, `StorageAdmin`, `ConnectionDialog({ connection?, onClose, onSaved(connection) })`. Destructive user actions ask `window.confirm`. Labels the end-to-end suite relies on: "Create user", "E-mail", "Display name", "Account type", "Create", dialog "Temporary password", "Close", "New connection", "Name", "Type", "Root path", "Save", "Test connection", status text "Connection OK".

- [ ] **Step 1: Shared types**

`frontend/src/features/admin/types.ts`:

```ts
import type { components } from "@/lib/api/schema";

export type User = components["schemas"]["UserOut"];
export type Connection = components["schemas"]["StorageConnectionOut"];
export type ConnectionType = components["schemas"]["StorageConnectionCreate"]["type"];

export const CONNECTION_TYPES: ConnectionType[] = ["localfs", "sharepoint", "gdrive"];
export const AVAILABLE_TYPES: ConnectionType[] = ["localfs"]; // Plan 3b adds the others
```

- [ ] **Step 2: Write the failing tests**

`frontend/src/features/admin/UsersAdmin.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { UsersAdmin } from "./UsersAdmin";

const alice = {
  id: "u-alice",
  email: "alice@example.com",
  display_name: "Alice",
  account_type: "internal",
  is_admin: false,
  is_active: true,
  mfa_enabled: true,
  must_change_password: false,
  locked_until: null,
};

it("test_create_user_shows_the_temporary_password_once", async () => {
  const f = mockFetch([
    { path: "/api/v1/users", body: [alice] },
    {
      method: "POST",
      path: "/api/v1/users",
      status: 201,
      body: {
        user: { ...alice, id: "u-bob", email: "bob@example.com", display_name: "Bob" },
        temporary_password: "example-temporary-password",
      },
    },
  ]);
  render(<UsersAdmin />);
  expect(await screen.findByRole("cell", { name: "alice@example.com" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Create user" }));
  await userEvent.type(screen.getByLabelText("E-mail"), "bob@example.com");
  await userEvent.type(screen.getByLabelText("Display name"), "Bob");
  await userEvent.selectOptions(screen.getByLabelText("Account type"), "customer");
  expect(screen.getByLabelText("Administrator")).toBeDisabled(); // customers cannot be admins
  await userEvent.selectOptions(screen.getByLabelText("Account type"), "internal");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  const dialog = await screen.findByRole("dialog", { name: "Temporary password" });
  expect(within(dialog).getByText("example-temporary-password")).toBeInTheDocument();
  expect(await f.body(1)).toEqual({
    email: "bob@example.com",
    display_name: "Bob",
    account_type: "internal",
    is_admin: false,
  });
  await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.queryByText("example-temporary-password")).not.toBeInTheDocument();
  expect(f.find("GET", "/api/v1/users")).toBeDefined();
});

it("deactivates after confirmation and resets MFA", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const f = mockFetch([
    { path: "/api/v1/users", body: [alice] },
    { method: "PATCH", path: "/api/v1/users/u-alice", body: { ...alice, is_active: false } },
    { method: "POST", path: "/api/v1/users/u-alice/reset-mfa", status: 204 },
  ]);
  render(<UsersAdmin />);
  const row = (await screen.findByRole("cell", { name: "alice@example.com" })).closest("tr")!;
  await userEvent.click(within(row).getByRole("button", { name: "Deactivate" }));
  expect(await f.body(1)).toEqual({ is_active: false });
  await userEvent.click(within(row).getByRole("button", { name: "Reset MFA" }));
  expect(await screen.findByRole("status")).toHaveTextContent("MFA reset.");
  expect(f.find("POST", "/api/v1/users/u-alice/reset-mfa")).toBeDefined();
});
```

`frontend/src/features/admin/StorageAdmin.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { StorageAdmin } from "./StorageAdmin";

const local = {
  id: "c-local",
  type: "localfs",
  name: "Local storage",
  config: { root_path: "." },
  is_default: true,
  is_active: true,
  has_secret: false,
  created_at: "2026-10-01T10:00:00+00:00",
  updated_at: "2026-10-01T10:00:00+00:00",
};
const archive = { ...local, id: "c-archive", name: "Archive", config: { root_path: "archive" }, is_default: false };

it("lists connections, creates a localfs connection and tests it", async () => {
  const f = mockFetch([
    { path: "/api/v1/storage-connections", body: [archive, local] },
    { method: "POST", path: "/api/v1/storage-connections", status: 201, body: { ...archive, id: "c-new", name: "E2E" } },
    { method: "POST", path: "/api/v1/storage-connections/c-archive/test", body: { ok: true, detail: "ok" } },
  ]);
  render(<StorageAdmin />);
  const localRow = (await screen.findByRole("cell", { name: "Local storage" })).closest("tr")!;
  expect(within(localRow).getByText("Default")).toBeInTheDocument();
  expect(within(localRow).queryByRole("button", { name: "Set as default" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "New connection" }));
  await userEvent.type(screen.getByLabelText("Name"), "E2E");
  expect(screen.queryByLabelText("Secret (write-only)")).toBeNull(); // hidden for localfs
  const rootPath = screen.getByLabelText("Root path");
  await userEvent.clear(rootPath);
  await userEvent.type(rootPath, "e2e");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await f.body(1)).toEqual({ type: "localfs", name: "E2E", config: { root_path: "e2e" } });
  expect(await screen.findByRole("status")).toHaveTextContent("Connection saved.");
  const archiveRow = screen.getByRole("cell", { name: "Archive" }).closest("tr")!;
  await userEvent.click(within(archiveRow).getByRole("button", { name: "Test connection" }));
  expect(await within(archiveRow).findByRole("status")).toHaveTextContent("Connection OK");
});

it("sets a default and shows a 409 when deactivation is refused", async () => {
  const f = mockFetch([
    { path: "/api/v1/storage-connections", body: [archive, local] },
    {
      method: "PATCH",
      path: "/api/v1/storage-connections/c-archive",
      body: { ...archive, is_default: true },
    },
    {
      method: "PATCH",
      path: "/api/v1/storage-connections/c-local",
      status: 409,
      body: { detail: "The default connection cannot be deactivated. Set another connection as the default first." },
    },
  ]);
  render(<StorageAdmin />);
  const archiveRow = (await screen.findByRole("cell", { name: "Archive" })).closest("tr")!;
  await userEvent.click(within(archiveRow).getByRole("button", { name: "Set as default" }));
  expect(await f.body(1)).toEqual({ is_default: true });
  const localRow = screen.getByRole("cell", { name: "Local storage" }).closest("tr")!;
  await userEvent.click(within(localRow).getByRole("button", { name: "Deactivate" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("cannot be deactivated");
});
```

Run: `pnpm test src/features/admin`
Expected: FAIL — the component modules do not exist.

- [ ] **Step 3: Users components**

`frontend/src/features/admin/TemporaryPasswordDialog.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { m } from "@/messages";

type Props = { email: string; password: string; onClose: () => void };

/** The only place a temporary password is ever shown; nothing is kept once it closes. */
export function TemporaryPasswordDialog({ email, password, onClose }: Props) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(password);
    setCopied(true);
  }
  return (
    <Dialog
      open
      title={m.users.tempPasswordTitle}
      onClose={onClose}
      footer={<Button onClick={onClose}>{m.common.close}</Button>}
    >
      <p className="text-sm text-muted">{m.users.tempPasswordIntro}</p>
      <p className="mt-3 text-sm font-medium">{m.users.tempPasswordFor(email)}</p>
      <div className="mt-1 flex items-center gap-2">
        <code className="rounded-md border border-border bg-bg px-3 py-2 font-mono text-base">
          {password}
        </code>
        <Button variant="secondary" onClick={() => void copy()}>
          {copied ? m.common.copied : m.common.copy}
        </Button>
      </div>
    </Dialog>
  );
}
```

`frontend/src/features/admin/CreateUserDialog.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { User } from "./types";

type Props = { onClose: () => void; onCreated: (user: User, temporaryPassword: string) => void };

export function CreateUserDialog({ onClose, onCreated }: Props) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [accountType, setAccountType] = useState<"internal" | "customer">("internal");
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const customer = accountType === "customer";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/users", {
        body: {
          email,
          display_name: displayName,
          account_type: accountType,
          is_admin: customer ? false : isAdmin,
        },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onCreated(data.user, data.temporary_password);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={m.users.newUser} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <Field
          label={m.users.email}
          type="email"
          required
          maxLength={320}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Field
          label={m.users.displayName}
          required
          maxLength={200}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />
        <Select
          label={m.users.accountType}
          value={accountType}
          onChange={(event) => setAccountType(event.target.value as "internal" | "customer")}
        >
          <option value="internal">{m.users.internal}</option>
          <option value="customer">{m.users.customer}</option>
        </Select>
        <Checkbox
          label={m.users.isAdmin}
          checked={customer ? false : isAdmin}
          disabled={customer}
          onChange={(event) => setIsAdmin(event.target.checked)}
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button type="submit" busy={busy}>
            {m.common.create}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
```

`frontend/src/features/admin/UsersAdmin.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { apiErrorMessage, unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { CreateUserDialog } from "./CreateUserDialog";
import { TemporaryPasswordDialog } from "./TemporaryPasswordDialog";
import type { User } from "./types";

type Shown = { email: string; password: string } | null;

export function UsersAdmin() {
  const users = useLoad(() => api.GET("/api/v1/users").then((r) => unwrap(r)), []);
  const [creating, setCreating] = useState(false);
  const [shown, setShown] = useState<Shown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<{ error?: unknown; response: Response }>, done?: string) {
    setError(null);
    setNotice(null);
    try {
      const { error: apiError, response } = await action();
      if (!response.ok) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      if (done) setNotice(done);
      users.reload();
    } catch {
      setError(m.common.requestFailed);
    }
  }

  function setActive(user: User, active: boolean) {
    if (!active && !window.confirm(m.users.confirmDeactivate)) return;
    void run(() =>
      api.PATCH("/api/v1/users/{user_id}", {
        params: { path: { user_id: user.id } },
        body: { is_active: active },
      }),
    );
  }

  async function resetPassword(user: User) {
    if (!window.confirm(m.users.confirmResetPassword)) return;
    setError(null);
    const { data, error: apiError } = await api.POST("/api/v1/users/{user_id}/reset-password", {
      params: { path: { user_id: user.id } },
    });
    if (!data) {
      setError(apiErrorMessage(apiError, m.common.requestFailed));
      return;
    }
    setShown({ email: user.email, password: data.temporary_password });
    users.reload();
  }

  function resetMfa(user: User) {
    if (!window.confirm(m.users.confirmResetMfa)) return;
    void run(
      () =>
        api.POST("/api/v1/users/{user_id}/reset-mfa", { params: { path: { user_id: user.id } } }),
      m.users.mfaReset,
    );
  }

  return (
    <>
      <PageHeader
        title={m.users.title}
        actions={<Button onClick={() => setCreating(true)}>{m.users.newUser}</Button>}
      />
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}
      {users.error ? <Alert kind="error">{users.error}</Alert> : null}
      {users.loading ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : null}
      {users.data ? (
        <Table caption={m.users.title}>
          <thead>
            <tr>
              <Th>{m.users.email}</Th>
              <Th>{m.users.displayName}</Th>
              <Th>{m.users.accountType}</Th>
              <Th>{m.users.status}</Th>
              <Th>{m.users.mfa}</Th>
              <Th>{m.common.actions}</Th>
            </tr>
          </thead>
          <tbody>
            {users.data.map((user) => (
              <tr key={user.id}>
                <Td>{user.email}</Td>
                <Td>{user.display_name}</Td>
                <Td>
                  {user.account_type === "customer" ? m.users.customer : m.users.internal}
                  {user.is_admin ? (
                    <>
                      {" "}
                      <Badge tone="warning">{m.users.isAdmin}</Badge>
                    </>
                  ) : null}
                </Td>
                <Td>
                  <span className="flex flex-wrap gap-1">
                    <Badge tone={user.is_active ? "success" : "danger"}>
                      {user.is_active ? m.users.active : m.users.inactive}
                    </Badge>
                    {user.locked_until && new Date(user.locked_until) > new Date() ? (
                      <Badge tone="danger">{m.users.locked}</Badge>
                    ) : null}
                    {user.must_change_password ? <Badge>{m.users.mustChange}</Badge> : null}
                  </span>
                </Td>
                <Td>{user.mfa_enabled ? m.users.enrolled : m.users.notEnrolled}</Td>
                <Td>
                  <span className="flex flex-wrap gap-1">
                    <Button
                      variant={user.is_active ? "danger" : "secondary"}
                      onClick={() => setActive(user, !user.is_active)}
                    >
                      {user.is_active ? m.users.deactivate : m.users.reactivate}
                    </Button>
                    <Button variant="secondary" onClick={() => void resetPassword(user)}>
                      {m.users.resetPassword}
                    </Button>
                    <Button variant="secondary" onClick={() => resetMfa(user)}>
                      {m.users.resetMfa}
                    </Button>
                  </span>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      {creating ? (
        <CreateUserDialog
          onClose={() => setCreating(false)}
          onCreated={(user, password) => {
            setCreating(false);
            setShown({ email: user.email, password });
            users.reload();
          }}
        />
      ) : null}
      {shown ? (
        <TemporaryPasswordDialog
          email={shown.email}
          password={shown.password}
          onClose={() => setShown(null)}
        />
      ) : null}
    </>
  );
}
```

- [ ] **Step 4: Storage components**

`frontend/src/features/admin/ConnectionDialog.tsx`:

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
import { AVAILABLE_TYPES, CONNECTION_TYPES, type Connection, type ConnectionType } from "./types";

type Props = { connection?: Connection; onClose: () => void; onSaved: (connection: Connection) => void };

/** Create (no `connection`) or edit the non-secret settings and replace the secret. */
export function ConnectionDialog({ connection, onClose, onSaved }: Props) {
  const [name, setName] = useState(connection?.name ?? "");
  const [type, setType] = useState<ConnectionType>((connection?.type as ConnectionType) ?? "localfs");
  const [rootPath, setRootPath] = useState(String(connection?.config.root_path ?? "."));
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hasSecret = type !== "localfs";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const config = { root_path: rootPath.trim() };
      const result = connection
        ? await api.PATCH("/api/v1/storage-connections/{connection_id}", {
            params: { path: { connection_id: connection.id } },
            body: { name, config, ...(hasSecret && secret ? { secret } : {}) },
          })
        : await api.POST("/api/v1/storage-connections", {
            body: { type, name, config, ...(hasSecret && secret ? { secret } : {}) },
          });
      if (!result.data) {
        setError(apiErrorMessage(result.error, m.common.requestFailed));
        return;
      }
      onSaved(result.data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={connection ? m.storage.editTitle : m.storage.createTitle} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <Field
          label={m.storage.name}
          required
          maxLength={100}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Select
          label={m.storage.type}
          value={type}
          disabled={connection !== undefined}
          onChange={(event) => setType(event.target.value as ConnectionType)}
        >
          {CONNECTION_TYPES.map((t) => (
            <option key={t} value={t} disabled={!AVAILABLE_TYPES.includes(t)}>
              {m.storage.typeLabels[t] ?? t}
            </option>
          ))}
        </Select>
        <Field
          label={m.storage.rootPath}
          hint={m.storage.rootPathHint}
          required
          maxLength={500}
          value={rootPath}
          onChange={(event) => setRootPath(event.target.value)}
        />
        {hasSecret ? (
          <Field
            label={m.storage.secretField}
            hint={m.storage.secretHint}
            type="password"
            autoComplete="off"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
          />
        ) : null}
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

`frontend/src/features/admin/StorageAdmin.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { apiErrorMessage, unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { ConnectionDialog } from "./ConnectionDialog";
import type { Connection } from "./types";

type TestState = { ok: boolean; detail: string } | "running";

export function StorageAdmin() {
  const connections = useLoad(
    () => api.GET("/api/v1/storage-connections").then((r) => unwrap(r)),
    [],
  );
  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function patch(
    connection: Connection,
    body: { is_default?: boolean; is_active?: boolean },
    done: string | null,
  ) {
    setError(null);
    setNotice(null);
    try {
      const { data, error: apiError } = await api.PATCH(
        "/api/v1/storage-connections/{connection_id}",
        { params: { path: { connection_id: connection.id } }, body },
      );
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      if (done) setNotice(done);
      connections.reload();
    } catch {
      setError(m.common.requestFailed);
    }
  }

  async function test(connection: Connection) {
    setTests((t) => ({ ...t, [connection.id]: "running" }));
    try {
      const { data, error: apiError } = await api.POST(
        "/api/v1/storage-connections/{connection_id}/test",
        { params: { path: { connection_id: connection.id } } },
      );
      setTests((t) => ({
        ...t,
        [connection.id]: data ?? {
          ok: false,
          detail: apiErrorMessage(apiError, m.common.requestFailed),
        },
      }));
    } catch {
      setTests((t) => ({ ...t, [connection.id]: { ok: false, detail: m.common.requestFailed } }));
    }
  }

  return (
    <>
      <PageHeader
        title={m.storage.title}
        actions={<Button onClick={() => setEditing("new")}>{m.storage.newConnection}</Button>}
      />
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}
      {connections.error ? <Alert kind="error">{connections.error}</Alert> : null}
      {connections.loading ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : null}
      {connections.data ? (
        <Table caption={m.storage.title}>
          <thead>
            <tr>
              <Th>{m.storage.name}</Th>
              <Th>{m.storage.type}</Th>
              <Th>{m.storage.rootPath}</Th>
              <Th>{m.storage.active}</Th>
              <Th>{m.storage.secret}</Th>
              <Th>{m.common.actions}</Th>
            </tr>
          </thead>
          <tbody>
            {connections.data.map((connection) => {
              const result = tests[connection.id];
              return (
                <tr key={connection.id}>
                  <Td>
                    {connection.name}
                    {connection.is_default ? (
                      <>
                        {" "}
                        <Badge tone="success">{m.storage.default}</Badge>
                      </>
                    ) : null}
                  </Td>
                  <Td>{m.storage.typeLabels[connection.type] ?? connection.type}</Td>
                  <Td className="font-mono">{String(connection.config.root_path ?? "")}</Td>
                  <Td>
                    <Badge tone={connection.is_active ? "success" : "danger"}>
                      {connection.is_active ? m.storage.active : m.storage.inactive}
                    </Badge>
                  </Td>
                  <Td>{connection.has_secret ? m.storage.hasSecret : m.storage.noSecret}</Td>
                  <Td>
                    <span className="flex flex-wrap items-center gap-1">
                      <Button variant="secondary" onClick={() => setEditing(connection)}>
                        {m.storage.edit}
                      </Button>
                      {connection.is_active && !connection.is_default ? (
                        <Button
                          variant="secondary"
                          onClick={() =>
                            void patch(connection, { is_default: true }, m.storage.defaultChanged)
                          }
                        >
                          {m.storage.setDefault}
                        </Button>
                      ) : null}
                      <Button
                        variant={connection.is_active ? "danger" : "secondary"}
                        onClick={() =>
                          void patch(connection, { is_active: !connection.is_active }, null)
                        }
                      >
                        {connection.is_active ? m.storage.deactivate : m.storage.reactivate}
                      </Button>
                      <Button
                        variant="secondary"
                        busy={result === "running"}
                        onClick={() => void test(connection)}
                      >
                        {m.storage.test}
                      </Button>
                      {result && result !== "running" ? (
                        <span role="status" className={result.ok ? "text-success" : "text-danger"}>
                          {result.ok ? m.storage.testOk : `${m.storage.testFailed}: ${result.detail}`}
                        </span>
                      ) : null}
                    </span>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      ) : null}
      {editing ? (
        <ConnectionDialog
          connection={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            setNotice(m.storage.saved);
            connections.reload();
          }}
        />
      ) : null}
    </>
  );
}
```

Pages — `frontend/src/app/(app)/admin/users/page.tsx`:

```tsx
import { UsersAdmin } from "@/features/admin/UsersAdmin";

export default function Page() {
  return <UsersAdmin />;
}
```

`frontend/src/app/(app)/admin/storage/page.tsx`:

```tsx
import { StorageAdmin } from "@/features/admin/StorageAdmin";

export default function Page() {
  return <StorageAdmin />;
}
```

- [ ] **Step 5: Run every gate**

```bash
pnpm format:write
pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build
```

Expected: all tests pass (4 new); the build lists `/admin/users` and `/admin/storage`.

- [ ] **Step 6: Commit**

```bash
cd ..
git add frontend
git commit -m "feat(frontend): admin pages for users and storage connections"
```

### Task 10: Playwright end-to-end suite against the real backend and PostgreSQL

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/env.ts`, `frontend/e2e/backend.sh`, `frontend/e2e/global-setup.ts`, `frontend/e2e/first-run.spec.ts`, `frontend/e2e/guards.spec.ts`
- Modify: `frontend/package.json` (one script)

**Interfaces:**
- Consumes: every screen (Tasks 7–9), backend CLI `uv run qc-agent create-admin --email … --name …` (prints `Temporary password (shown once): <password>`), `alembic upgrade head`, `uvicorn --factory app.main:create_app` (Plans 1–2), asyncpg (backend dependency).
- Produces: `pnpm e2e` (= `BACKEND_URL=http://localhost:8001 next build && playwright test`); `e2e/env.ts` exporting `FRONTEND_URL = "http://localhost:3001"`, `BACKEND_URL = "http://localhost:8001"`, `DATABASE_URL` (env `QC_E2E_DATABASE_URL`, default `postgresql+asyncpg://qc:qc@localhost:5434/qc_agent_e2e`) and `backendEnv` (random per-run `SESSION_SECRET` / `SECRET_ENCRYPTION_KEY`, temp `LOCAL_STORAGE_ROOT` / `STAGING_ROOT`, `COOKIE_SECURE=false`); `e2e/backend.sh` recreates the e2e database, migrates and runs the API on 8001; `global-setup.ts` creates the admin and writes `e2e/.state/admin.json` (git-ignored). Task 11's CI job runs `pnpm exec playwright install --with-deps chromium`, `BACKEND_URL=http://localhost:8001 pnpm build`, `pnpm exec playwright test` with `QC_E2E_DATABASE_URL` pointing at the service container.

- [ ] **Step 1: Environment and servers**

Add to `scripts` in `frontend/package.json`:

```json
    "e2e": "BACKEND_URL=http://localhost:8001 next build && playwright test"
```

`frontend/e2e/env.ts`:

```ts
import { randomBytes } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Ports differ from the dev servers (3000/8000) so the suite never collides with them.
export const FRONTEND_URL = "http://localhost:3001";
export const BACKEND_URL = "http://localhost:8001";
export const DATABASE_URL =
  process.env.QC_E2E_DATABASE_URL ?? "postgresql+asyncpg://qc:qc@localhost:5434/qc_agent_e2e";

const dataRoot = mkdtempSync(path.join(tmpdir(), "qc-agent-e2e-"));

/** Environment for the backend process and the CLI: a disposable database, temporary data
 * folders and random per-run secrets (a Fernet key is 32 random bytes in base64). */
export const backendEnv: Record<string, string> = {
  DATABASE_URL,
  SESSION_SECRET: randomBytes(32).toString("hex"),
  SECRET_ENCRYPTION_KEY: randomBytes(32).toString("base64"),
  COOKIE_SECURE: "false",
  EXPOSE_DOCS: "false",
  LOCAL_STORAGE_ROOT: path.join(dataRoot, "workspace"),
  STAGING_ROOT: path.join(dataRoot, "staging"),
};

export const ADMIN_EMAIL = "e2e-admin@example.com";
export const STATE_FILE = path.join(__dirname, ".state", "admin.json");
```

`frontend/e2e/backend.sh` (make it executable: `chmod +x frontend/e2e/backend.sh`):

```bash
#!/usr/bin/env bash
# Started by Playwright's webServer with the e2e environment (see env.ts): recreate the e2e
# database, apply the migrations, run the API. Playwright waits for /api/v1/health.
set -euo pipefail
cd "$(dirname "$0")/../../backend"
uv run python - <<'PY'
import asyncio
import os

import asyncpg

url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
server, name = url.rsplit("/", 1)


async def main() -> None:
    conn = await asyncpg.connect(f"{server}/postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


asyncio.run(main())
PY
uv run alembic upgrade head
exec uv run uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8001
```

`frontend/e2e/global-setup.ts`:

```ts
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { ADMIN_EMAIL, STATE_FILE, backendEnv } from "./env";

/** Runs after the web servers are up (Playwright starts them first): the database is migrated,
 * so the CLI can create the first administrator. */
export default function globalSetup(): void {
  const output = execFileSync(
    "uv",
    ["run", "--directory", path.join(__dirname, "..", "..", "backend"), "qc-agent",
      "create-admin", "--email", ADMIN_EMAIL, "--name", "E2E Admin"],
    { encoding: "utf8", env: { ...process.env, ...backendEnv } },
  );
  const match = /Temporary password \(shown once\): (\S+)/.exec(output);
  if (!match) throw new Error(`create-admin did not print a temporary password:\n${output}`);
  mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  writeFileSync(STATE_FILE, JSON.stringify({ email: ADMIN_EMAIL, password: match[1] }));
}
```

`frontend/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";
import { BACKEND_URL, FRONTEND_URL, backendEnv } from "./e2e/env";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: FRONTEND_URL, trace: "retain-on-failure" },
  webServer: [
    {
      name: "backend",
      command: "bash e2e/backend.sh",
      url: `${BACKEND_URL}/api/v1/health`,
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      name: "frontend",
      command: "pnpm exec next start -p 3001", // built by `pnpm e2e` with BACKEND_URL=…:8001
      url: FRONTEND_URL,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
```

- [ ] **Step 2: The specs**

`frontend/e2e/guards.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("anonymous visitors are sent to the login page", async ({ page }) => {
  await page.goto("/projects");
  await page.waitForURL("**/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/admin/storage");
  await page.waitForURL("**/login");
});

test("the API proxy keeps the CSRF guard", async ({ request }) => {
  const health = await request.get("/api/v1/health");
  expect(health.status()).toBe(200);
  const noHeader = await request.post("/api/v1/auth/login", {
    data: { email: "nobody@example.com", password: "x" },
  });
  expect(noHeader.status()).toBe(403);
});
```

`frontend/e2e/first-run.spec.ts`:

```ts
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { generate } from "otplib";
import { STATE_FILE } from "./env";

const NEW_PASSWORD = "e2e-very-long-password-2026";

async function signIn(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("first run: admin signs in, enrols MFA, changes the password, sets up storage, a project and a member", async ({
  page,
}) => {
  const admin = JSON.parse(readFileSync(STATE_FILE, "utf8")) as { email: string; password: string };

  await test.step("login and MFA enrolment with recovery codes", async () => {
    await signIn(page, admin.email, admin.password);
    await expect(page.getByRole("heading", { name: "Two-factor authentication" })).toBeVisible();
    const secret = await page.getByLabel("Setup key (if you cannot scan)").inputValue();
    await expect(page.getByAltText("QR code for your authenticator app")).toBeVisible();
    await page.getByLabel("Authentication code").fill(await generate({ secret }));
    await page.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByRole("heading", { name: "Recovery codes" })).toBeVisible();
    await expect(page.getByRole("listitem")).toHaveCount(10);
    const next = page.getByRole("button", { name: "Continue" });
    await expect(next).toBeDisabled();
    await page.getByLabel("I have saved my recovery codes").check();
    await next.click();
  });

  await test.step("forced password change", async () => {
    await expect(page.getByRole("heading", { name: "Change your password" })).toBeVisible();
    await page.getByLabel("Current password").fill(admin.password);
    await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
    await page.getByLabel("Confirm new password").fill(NEW_PASSWORD);
    await page.getByRole("button", { name: "Change password" }).click();
    await page.waitForURL("**/projects");
    await expect(page.getByText("Administrator")).toBeVisible();
  });

  await test.step("admin creates and tests a storage connection", async () => {
    await page.getByRole("link", { name: "Admin" }).click();
    await page.getByRole("link", { name: "Storage" }).click();
    await expect(page.getByRole("cell", { name: /Local storage/ })).toBeVisible();
    await page.getByRole("button", { name: "New connection" }).click();
    await page.getByLabel("Name", { exact: true }).fill("E2E storage");
    await page.getByLabel("Root path").fill("e2e");
    await page.getByRole("button", { name: "Save" }).click();
    const row = page.getByRole("row", { name: /E2E storage/ });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Test connection" }).click();
    await expect(row.getByRole("status")).toHaveText("Connection OK");
  });

  await test.step("owner creates a project on that connection and records the consent", async () => {
    await page.getByRole("link", { name: "Projects" }).click();
    await page.getByRole("button", { name: "New project" }).click();
    await page.getByLabel("Project name").fill("E2E Project");
    await page.getByLabel("Client name").fill("ACME");
    await page.getByLabel("Storage connection").selectOption({ label: "E2E storage (Local filesystem)" });
    await page.getByLabel("Root folder (optional)").fill("e2e-project");
    await page.getByRole("button", { name: "Create project" }).click();
    await page.waitForURL(/\/projects\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: "E2E Project" })).toBeVisible();
    await expect(page.getByText("E2E storage")).toBeVisible();
    await expect(page.getByText("e2e-project")).toBeVisible();
    await page.getByLabel("Name of the confirming person").fill("Customer Rep");
    await page.getByRole("button", { name: "Record customer confirmation" }).click();
    await expect(page.getByText(/Confirmed by Customer Rep on/)).toBeVisible();
  });

  const projectUrl = page.url();

  await test.step("admin creates an editor account and sees the temporary password once", async () => {
    await page.getByRole("link", { name: "Admin" }).click();
    await page.getByRole("button", { name: "Create user" }).click();
    await page.getByLabel("E-mail").fill("editor@example.com");
    await page.getByLabel("Display name").fill("Editor");
    await page.getByRole("button", { name: "Create" }).click();
    const dialog = page.getByRole("dialog", { name: "Temporary password" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("code")).toHaveText(/\S{12,}/);
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("cell", { name: "editor@example.com" })).toBeVisible();
  });

  await test.step("owner adds the editor as a project member", async () => {
    await page.goto(projectUrl);
    await page.getByRole("tab", { name: "Members" }).click();
    await page.getByLabel("User", { exact: true }).selectOption({ label: "Editor (editor@example.com)" });
    await page.getByLabel("Role", { exact: true }).selectOption("editor");
    await page.getByRole("button", { name: "Add member" }).click();
    await page.getByRole("button", { name: "Save members" }).click();
    await expect(page.getByRole("status")).toHaveText("Members saved.");
    await expect(page.getByRole("cell", { name: "Editor" })).toBeVisible();
  });

  await test.step("logout", async () => {
    await page.getByRole("button", { name: "Log out" }).click();
    await page.waitForURL("**/login");
  });
});
```

- [ ] **Step 3: Run the suite locally**

PostgreSQL from `deploy/dev/docker-compose.yml` must be running (the script creates `qc_agent_e2e` itself).

```bash
pnpm exec playwright install chromium
pnpm e2e
```

Expected: `next build` with the 8001 rewrite, then Playwright starts the backend (database recreated, `alembic upgrade head`, uvicorn on 8001) and `next start -p 3001`, runs the global setup, and reports `3 passed`. On failure, `pnpm exec playwright show-report` opens the trace.

Then the usual gates (the `e2e/` files are type-checked and linted too):

```bash
pnpm format:write
pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check
```

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/playwright.config.ts frontend/e2e frontend/package.json
git commit -m "test(frontend): Playwright first-run flow against the real backend"
```

### Task 11: CI jobs for the frontend and end-to-end suite, README, roadmap and pending items

**Files:**
- Modify: `.github/workflows/ci.yml` (two jobs appended; existing jobs unchanged), `.pre-commit-config.yaml` (one hook), `README.md` (replace), `frontend/README.md` (replace), `docs/superpowers/plans/2026-10-01-phase1-roadmap.md` (replace), `docs/PENDING.md` (listed lines)

**Interfaces:**
- Consumes: frontend scripts (Task 5, 6, 10), `e2e/env.ts` reading `QC_E2E_DATABASE_URL` (Task 10), the backend job's PostgreSQL service pattern (existing).
- Produces: CI jobs `frontend` and `e2e`; documentation matching the shipped behaviour; the roadmap with the 3a/3b/3c split.

- [ ] **Step 1: CI jobs**

Append to `.github/workflows/ci.yml` (after the `secrets` job, same indentation as the other jobs):

```yaml
  frontend:
    name: Frontend (lint, format, types, unit tests, build)
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v6 # version from package.json "packageManager"
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm format
      - run: pnpm typecheck
      - run: pnpm test
      - name: Generated API types match the committed OpenAPI document
        run: pnpm api:check
      - run: pnpm build

  e2e:
    name: End-to-end (Playwright, real backend)
    runs-on: ubuntu-latest
    timeout-minutes: 25
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: qc
          POSTGRES_PASSWORD: qc  # CI-only throwaway database
          POSTGRES_DB: qc_agent
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U qc -d qc_agent"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      QC_E2E_DATABASE_URL: postgresql+asyncpg://qc:qc@localhost:5432/qc_agent_e2e
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: backend/uv.lock
      - name: Install backend dependencies
        run: uv sync --locked
        working-directory: backend
      - uses: pnpm/action-setup@v6
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
        working-directory: frontend
      - name: Cache Playwright browsers
        uses: actions/cache@v4
        with:
          path: ~/.cache/ms-playwright
          key: playwright-${{ runner.os }}-${{ hashFiles('frontend/pnpm-lock.yaml') }}
      - run: pnpm exec playwright install --with-deps chromium
        working-directory: frontend
      - name: Build the frontend against the e2e backend port
        run: BACKEND_URL=http://localhost:8001 pnpm build
        working-directory: frontend
      - name: Run the end-to-end suite
        run: pnpm exec playwright test
        working-directory: frontend
        env:
          CI: "true"
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: frontend/playwright-report
          retention-days: 7
```

Append to `.pre-commit-config.yaml` under the `local` repo's `hooks`:

```yaml
      - id: frontend
        name: frontend lint and format
        entry: bash -c 'cd frontend && pnpm lint && pnpm format'
        language: system
        pass_filenames: false
        files: ^frontend/
```

- [ ] **Step 2: Root README**

Replace `README.md`:

````markdown
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

CI (`.github/workflows/ci.yml`) runs the backend gates, the frontend gates, the end-to-end suite and a gitleaks scan on every pull request.
````

- [ ] **Step 3: Frontend README**

Replace `frontend/README.md`:

````markdown
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
````

- [ ] **Step 4: Roadmap**

Replace `docs/superpowers/plans/2026-10-01-phase1-roadmap.md`:

```markdown
# QC-Agent Phase 1 — Implementation Roadmap

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` (v2.1, 2026-10-01)

Phase 1 spans six subsystems. Each plan below produces working, tested software on its own and is executed and reviewed before the next one is written, so later plans can use real results (spike measurements, actual interfaces).

Re-sequenced on 2026-10-01 after the stakeholder chose upload on local storage first and cloud storage later. Plan 3 was then split (spec v2.1, storage configured in the UI): **3a** UI shell and storage settings, **3b** cloud adapters (blocked on IT test sites), **3c** storage change with migration.

| # | Plan | Delivers | Spec sections | Entry criteria | Status |
|---|---|---|---|---|---|
| 0 | Spikes | Measured answers: Agent SDK isolation, tool restriction, concurrency, cost; SharePoint and Google Drive upload + version behaviour | 7.3, 8.2, 8.3, 15 | Anthropic API key; a test SharePoint site with `Sites.Selected` grant; a test Shared Drive with service account | Written: `2026-10-01-plan-0-spikes.md` |
| 1 | Backend foundation | FastAPI app, PostgreSQL schema + Alembic, local accounts, mandatory TOTP MFA, sessions, lockout, rate limit, CSRF, admin user management, CLI, projects, members, roles | 9, 10, 11 (auth, admin, projects), 13 | Docker (or local PostgreSQL 16), uv | Done (merged PR #2) |
| 2 | Local ingestion | Taxonomy + templates as data, `StorageBackend` interface + local FS adapter + contract suite, project storage binding + workspace provisioning, per-project LLM consent, upload API, zip safety, converters, `Analyzer` interface, per-item state machine with re-queue, deterministic publish, versions, stubs, gap report, documents API | 5, 6, 7.1, 8.1, 8.4, 9, 10, 11, 13, 14 | Plan 1 merged | Done (merged PR #3) |
| 3a | UI shell and storage settings | `storage_connections` (localfs; encrypted write-only secrets; one default), projects bound to a connection + root, admin connection API with "Test connection", OpenAPI export; Next.js frontend: login, MFA enrolment/verification, forced password change, app shell and route guards, projects (list, create with storage choice, overview, members, settings, consent), admin users, admin storage; Vitest + Playwright; CI | 8.5, 10 (`storage_connections`), 11 (storage-connections), 12 (screens 1, 2, 9, 10, 11), 13, 15 | Plan 2 merged | Written: `2026-10-01-plan-3a-ui-storage-settings.md` |
| 3b | Cloud storage adapters | SharePoint adapter (Graph, `Sites.Selected`, upload sessions, `driveItem/versions`), Google Drive adapter (service account, resumable uploads, revisions), connection forms for both types, contract suite on live storage behind `QC_AGENT_LIVE_STORAGE=1`, retry/backoff and health | 8.2, 8.3, 8.6, 14 (storage errors), 16 (`/health` connections) | Plan 3a merged; Plan 0 storage spike; IT test site and Shared Drive | To write |
| 3c | Storage change with migration | `storage_migrations`, read-only `migrating` state, background copy of every version with SHA-256 verification, atomic switch, rollback, "Change storage" UI with progress | 8.5 (migration), 10 (`storage_migrations`), 12 (screen 9) | Plan 3a merged (3b optional) | To write |
| 4 | Agent layer | Claude Agent SDK runner, check and normalise sessions, custom tools, prompts, budgets, timeouts, telemetry, normalising item states, `normalized_drafts`, `agent_runs`, draft endpoints, `*.normalized.md` publish, repository-structure document, opt-in live tests | 5.4, 5.6, 6.2, 6.3 (steps 3, 6, 7), 7, 10, 11 (drafts), 15 | Plan 2 merged; Plan 0 agent spike | To write |
| 5 | Frontend (rest) | Upload wizard, document browser and document page, type confirmation, draft review, gap report, My tasks; Server-Sent Events endpoint + `events` table with `Last-Event-ID` replay | 12 (screens 3–8), 11 (SSE), 10 (`events`), 17 | Plans 3a and 4 merged | To write |
| 6 | Deployment & operations | Docker Compose for the cloud VM, Caddy with public TLS, proxy headers, backups, runbook, `/health` extensions, staging cleanup job, expired-session cleanup, full end-to-end suite | 16, 15, 19 | Plans 1–5 merged; cloud VM and DNS | To write |

Plan 0 has no dependency on Plans 1–3a; its storage spike feeds Plan 3b and its agent spike feeds Plan 4. Plans 3b, 3c and 4 are independent of each other once Plan 3a is merged.
```

- [ ] **Step 5: Pending items**

In `docs/PENDING.md`:

- Section 1: change the line `- [ ] Lưu trữ của dự án không đổi được sau khi tạo (mục 8.5).` to `- [x] Lưu trữ của dự án không đổi được sau khi tạo (mục 8.5) — spec v2.1: đổi được qua migration (Plan 3c).`
- Section 4: change `- [ ] Thực thi Plan 2 (owner: Claude; review: Connor).` to `- [x] Thực thi Plan 2 (owner: Claude; review: Connor) — merged PR #3.` and add after it:

```markdown
- [x] Lập kế hoạch Plan 3a (UI shell + storage settings): `docs/superpowers/plans/2026-10-01-plan-3a-ui-storage-settings.md`; Plan 3 tách thành 3a/3b/3c.
- [ ] Thực thi Plan 3a (owner: Claude; review: Connor).
- [ ] Lập kế hoạch Plan 3b (SharePoint + Google Drive; cần site test của IT) và Plan 3c (đổi lưu trữ có migration).
```

- Section 5: change the line beginning `- [ ] Plan 3: chính sách version cho gap report` to begin `- [ ] Plan 3b: chính sách version cho gap report` (rest unchanged).

- [ ] **Step 6: Verify the whole branch**

```bash
(cd backend && uv run alembic upgrade head && uv run alembic check && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app)
(cd frontend && pnpm lint && pnpm format && pnpm typecheck && pnpm test && pnpm api:check && pnpm build && pnpm e2e)
pre-commit run --all-files
```

Expected: `No new upgrade operations detected.`; every suite green; `pnpm e2e` reports `3 passed`; pre-commit hooks pass. Push the branch and confirm the four CI jobs (`backend`, `secrets`, `frontend`, `e2e`) are green on the pull request.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml .pre-commit-config.yaml README.md frontend/README.md docs/superpowers/plans/2026-10-01-phase1-roadmap.md docs/PENDING.md
git commit -m "docs: CI for frontend and e2e, READMEs, roadmap 3a/3b/3c split, pending items"
```
