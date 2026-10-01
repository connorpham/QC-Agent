# Plan 1 — Backend Foundation: Accounts, MFA, Projects, Roles

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI backend with PostgreSQL where admins create internal and customer accounts, every user signs in with password plus mandatory TOTP MFA, and internal users create projects and assign per-project roles.

**Architecture:** FastAPI app factory (`create_app(settings)`), async SQLAlchemy 2 on PostgreSQL 16 with Alembic migrations, thin routers over small service modules, security primitives as pure functions with unit tests. Server-side sessions in an `auth_sessions` table referenced by an opaque HttpOnly cookie. Authorisation through FastAPI dependencies layered `session_context → mfa_context → current_user → require_admin / require_project_role`.

**Tech Stack:** Python 3.12 (uv), FastAPI, Uvicorn, SQLAlchemy 2 (asyncio) + asyncpg, Alembic, pydantic-settings, argon2-cffi, pyotp, cryptography (Fernet), pytest + pytest-asyncio + httpx, ruff, mypy, pre-commit + gitleaks.

**Spec:** `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` — sections 9 (roles), 10 (`users`, `auth_sessions`, `projects`, `project_members`, `audit_log`), 11 (Auth, Admin users, Projects endpoints), 13 (authentication, sessions, authorisation, secrets, logging).

## Global Constraints

- Python `>=3.12,<3.13`, managed with uv; run every command from `backend/` unless stated.
- PostgreSQL 16. Tests run against a real PostgreSQL database (`TEST_DATABASE_URL`), never SQLite.
- API prefix `/api/v1`. All UI-facing copy and error messages in English.
- Passwords hashed with Argon2id (`argon2-cffi` defaults). Minimum new password length 12.
- MFA (TOTP, 6 digits, 30 s, issuer `QC-Agent`) is mandatory for every account; 10 one-time recovery codes.
- Lockout: 5 consecutive failures (password or MFA) → locked 15 minutes. Auth endpoints rate-limited per client IP: 20 requests per 5 minutes.
- Session cookie `qc_session`: opaque token, `HttpOnly`, `Secure` (configurable off only for localhost), `SameSite=Lax`, 8 h lifetime; token stored only as an HMAC-SHA256 hash.
- Every state-changing `/api/` request must carry header `X-QC-Agent: 1` (CSRF guard).
- Accounts are created by admins only; customer accounts (`account_type="customer"`) can never be admins and can only hold the project role `client`; internal accounts can never hold `client`.
- Admins act as `owner` on every project. Non-members get 404 for a project (no existence leak).
- Secrets only in `.env` (git-ignored); `.env.example` committed. MFA secrets encrypted at rest with Fernet (`SECRET_ENCRYPTION_KEY`). Never log passwords, tokens, MFA secrets or codes.
- Audit log rows for: login, logout, MFA enrol/verify/fail, recovery code use, password change, user create/update/reset, project create/update/archive, member changes.

## Review Focus

1. E-mail entered with different case or surrounding spaces (`" Alice@Example.COM "`) must log in the same account and must collide on creation → tests in Task 4 (login) and Task 7 (create user).
2. A TOTP code that was already used once must be rejected when replayed in the same 30-second window from another session → test in Task 5.
3. A user whose password was reset by an admin, or who was deactivated, must lose every existing session immediately, not at expiry → tests in Task 7.
4. A member update that leaves a project with no owner, or an admin deactivating or de-admining themselves, must be refused → tests in Task 7 and Task 8.
5. Vietnamese project names must produce readable ASCII slugs (`"Dự án Cổng Khách hàng"` → `du-an-cong-khach-hang`), and a second project with the same name gets `-2` → tests in Task 3 and Task 8.

---

## File Structure

```
QC-Agent/
├── .gitignore
├── .pre-commit-config.yaml
├── deploy/dev/
│   ├── docker-compose.yml          # PostgreSQL 16 for dev + tests (port 5433)
│   └── init-test-db.sql
└── backend/
    ├── pyproject.toml
    ├── .python-version
    ├── .env.example
    ├── alembic.ini
    ├── migrations/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/0001_identity_and_projects.py
    ├── app/
    │   ├── __init__.py
    │   ├── main.py                 # create_app(), CSRF middleware, routers
    │   ├── cli.py                  # qc-agent create-admin
    │   ├── core/
    │   │   ├── __init__.py
    │   │   ├── config.py           # Settings, get_settings
    │   │   ├── passwords.py        # Argon2id hashing, policy, temp passwords
    │   │   ├── tokens.py           # session tokens + HMAC hashing
    │   │   ├── crypto.py           # SecretBox (Fernet)
    │   │   ├── totp.py             # TOTP + recovery codes
    │   │   ├── slugs.py            # slugify, unique_slug
    │   │   ├── emails.py           # normalize_email, is_valid_email
    │   │   └── ratelimit.py        # SlidingWindowLimiter
    │   ├── db/
    │   │   ├── __init__.py
    │   │   ├── base.py             # Base with naming convention
    │   │   ├── session.py          # engine + get_session
    │   │   └── models/
    │   │       ├── __init__.py
    │   │       ├── identity.py     # User, AuthSession
    │   │       ├── projects.py     # Project, ProjectMember
    │   │       └── audit.py        # AuditLog
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── context.py          # SessionContext dataclass
│   │   ├── audit.py            # record()
    │   │   ├── auth.py             # authenticate, revoke_user_sessions, change_password
    │   │   ├── mfa.py              # enroll, confirm, verify_second_factor
    │   │   ├── users.py            # create/update/reset users
    │   │   └── projects.py         # create project, replace members, list
    │   ├── schemas/
    │   │   ├── __init__.py
    │   │   ├── auth.py
    │   │   ├── users.py
    │   │   └── projects.py
    │   └── api/
    │       ├── __init__.py
    │       ├── cookies.py
    │       ├── deps.py             # settings, db, session/mfa/user/admin/project-role deps
    │       └── routes/
    │           ├── __init__.py
    │           ├── health.py
    │           ├── auth.py
    │           ├── users.py
    │           └── projects.py
    └── tests/
        ├── __init__.py
        ├── conftest.py
        ├── factories.py
        ├── core/__init__.py + test_*.py
        ├── db/__init__.py + test_models.py
        └── api/__init__.py + test_*.py
```

---

### Task 1: Backend scaffold, settings, app factory, CSRF guard, health

**Files:**
- Create: `.gitignore`, `deploy/dev/docker-compose.yml`, `deploy/dev/init-test-db.sql`, `backend/pyproject.toml`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/app/db/__init__.py`, `backend/app/db/session.py`, `backend/app/api/__init__.py`, `backend/app/api/deps.py`, `backend/app/api/routes/__init__.py`, `backend/app/api/routes/health.py`, `backend/app/main.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`
- Test: `backend/tests/api/__init__.py`, `backend/tests/api/test_health.py`

**Interfaces:**
- Produces: `Settings` (fields listed below), `get_settings() -> Settings`; `init_engine(url: str, *, null_pool: bool = False) -> async_sessionmaker[AsyncSession]`, `is_initialised() -> bool`, `dispose_engine() -> Awaitable[None]`, `get_session() -> AsyncIterator[AsyncSession]`; `create_app(settings: Settings | None = None) -> FastAPI` (stores `app.state.settings`); `API_PREFIX = "/api/v1"`; `settings_dep(request) -> Settings`; type aliases `AppSettings`, `DbSession` in `app/api/deps.py`.

- [ ] **Step 1: Repository ignores and dev database**

`.gitignore` (repo root):

```gitignore
# secrets
.env
*.env.local
service-account*.json
# python
__pycache__/
*.pyc
.venv/
.mypy_cache/
.ruff_cache/
.pytest_cache/
# app data
workspace/
staging/
# node
node_modules/
.next/
```

`deploy/dev/docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: qc
      POSTGRES_PASSWORD: qc   # local development only
      POSTGRES_DB: qc_agent
    ports:
      - "127.0.0.1:5433:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init-test-db.sql:/docker-entrypoint-initdb.d/init-test-db.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U qc -d qc_agent"]
      interval: 5s
      retries: 10
volumes:
  pgdata:
```

`deploy/dev/init-test-db.sql`:

```sql
CREATE DATABASE qc_agent_test;
```

- [ ] **Step 2: Python project**

`backend/pyproject.toml`:

```toml
[project]
name = "qc-agent-backend"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[project.scripts]
qc-agent = "app.cli:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "S", "ASYNC"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105", "S106", "S608"]
"migrations/**" = ["E501"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
exclude = ["migrations/"]

[[tool.mypy.overrides]]
module = ["pyotp"]
ignore_missing_imports = true
```

Run:

```bash
cd backend
uv python pin 3.12
uv add fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings argon2-cffi pyotp cryptography
uv add --dev pytest pytest-asyncio httpx ruff mypy
```

Expected: `uv.lock` created, `.python-version` contains `3.12`.

`backend/.env.example`:

```dotenv
# Copy to .env. Generate secrets with:
#   uv run python -c "import secrets; print(secrets.token_urlsafe(48))"            -> SESSION_SECRET
#   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" -> SECRET_ENCRYPTION_KEY
DATABASE_URL=postgresql+asyncpg://qc:qc@localhost:5433/qc_agent
SESSION_SECRET=
SECRET_ENCRYPTION_KEY=
PUBLIC_BASE_URL=http://localhost:3000
COOKIE_SECURE=false
```

Create empty `__init__.py` files: `app/`, `app/core/`, `app/db/`, `app/api/`, `app/api/routes/`, `tests/`, `tests/api/`.

- [ ] **Step 3: Write the failing tests**

`backend/tests/conftest.py` (minimal for this task; Task 2 replaces it):

```python
import os

from cryptography.fernet import Fernet

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://qc:qc@localhost:5433/qc_agent_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-production")
os.environ.setdefault("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["COOKIE_SECURE"] = "false"
```

`backend/tests/api/test_health.py`:

```python
from collections.abc import AsyncIterator
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app


class _OkSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _BrokenSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("database down")


def _client_with(session: object, headers: dict[str, str] | None = None) -> AsyncClient:
    app = create_app(Settings())

    async def override() -> AsyncIterator[object]:
        yield session

    app.dependency_overrides[get_session] = override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver",
                       headers=headers or {})


async def test_health_ok() -> None:
    async with _client_with(_OkSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


async def test_health_reports_database_failure() -> None:
    async with _client_with(_BrokenSession()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": "error"}}


async def test_state_changing_request_without_csrf_header_is_rejected() -> None:
    async with _client_with(_OkSession()) as client:
        response = await client.post("/api/v1/health")
    assert response.status_code == 403
    assert response.json() == {"detail": "Missing CSRF header."}


async def test_state_changing_request_with_csrf_header_reaches_router() -> None:
    async with _client_with(_OkSession(), headers={"X-QC-Agent": "1"}) as client:
        response = await client.post("/api/v1/health")
    assert response.status_code == 405  # no POST route; the guard let it through
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.config'`.

- [ ] **Step 5: Implement settings, DB session, deps, health, app factory**

`backend/app/core/config.py`:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    session_secret: str
    secret_encryption_key: str
    public_base_url: str = "http://localhost:3000"
    cookie_secure: bool = True
    session_ttl_hours: int = 8
    login_max_failures: int = 5
    lockout_minutes: int = 15
    rate_limit_auth_per_5min: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
```

`backend/app/db/session.py`:

```python
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str, *, null_pool: bool = False) -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    kwargs: dict[str, Any] = {"poolclass": NullPool} if null_pool else {"pool_pre_ping": True}
    _engine = create_async_engine(url, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


def is_initialised() -> bool:
    return _sessionmaker is not None


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database engine is not initialised")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
```

`backend/app/api/deps.py`:

```python
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_session


def settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(settings_dep)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
```

`backend/app/api/routes/health.py`:

```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession

router = APIRouter(tags=["meta"])


async def _check_database(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means the check failed
        return "error"
    return "ok"


@router.get("/health")
async def health(db: DbSession) -> JSONResponse:
    checks = {"database": await _check_database(db)}
    ok = all(value == "ok" for value in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks},
        status_code=200 if ok else 503,
    )
```

`backend/app/main.py`:

```python
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes import health
from app.core.config import Settings, get_settings
from app.db.session import dispose_engine, init_engine, is_initialised

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-qc-agent"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not is_initialised():
            init_engine(app_settings.database_url)
        yield
        await dispose_engine()

    app = FastAPI(title="QC-Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings

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
    return app
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_health.py -v`
Expected: 4 passed.

- [ ] **Step 7: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: no errors (run `uv run ruff format .` first if formatting differs).

```bash
cd ..
git add .gitignore deploy/dev backend
git commit -m "feat(backend): scaffold FastAPI app with settings, CSRF guard and health check"
```

---

### Task 2: Database models, Alembic migration, test fixtures

**Files:**
- Create: `backend/app/db/base.py`, `backend/app/db/models/__init__.py`, `backend/app/db/models/identity.py`, `backend/app/db/models/projects.py`, `backend/app/db/models/audit.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_identity_and_projects.py`
- Modify: `backend/tests/conftest.py` (replace whole file)
- Test: `backend/tests/db/__init__.py`, `backend/tests/db/test_models.py`

**Interfaces:**
- Consumes: `init_engine`, `dispose_engine`, `create_app`, `Settings` (Task 1).
- Produces: ORM models `User`, `AuthSession`, `Project`, `ProjectMember`, `AuditLog` importable from `app.db.models`; `Base` from `app.db.base`. Test fixtures: `settings`, `db_sessionmaker`, `db`, `make_app(**overrides) -> FastAPI`, `app`, `client`, `make_client(token: str | None = None, app: FastAPI | None = None) -> AsyncClient`. Constants `ACCOUNT_TYPES = ("internal", "customer")`, `PROJECT_ROLES = ("owner", "editor", "viewer", "client")`.

- [ ] **Step 0: Start PostgreSQL**

Run (repo root): `docker compose -f deploy/dev/docker-compose.yml up -d db`
Expected: container healthy (`docker compose -f deploy/dev/docker-compose.yml ps` shows `healthy`). If `docker` is not installed, stop and ask the user to install Docker Desktop or OrbStack — this is a listed dependency in `docs/PENDING.md`.

Then in `backend/`: `cp .env.example .env` and fill `SESSION_SECRET` and `SECRET_ENCRYPTION_KEY` using the commands in the file.

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/conftest.py`:

```python
import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from cryptography.fernet import Fernet

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://qc:qc@localhost:5433/qc_agent_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-production")
os.environ.setdefault("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["COOKIE_SECURE"] = "false"

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db import models  # noqa: E402,F401  - registers tables on Base.metadata
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, init_engine  # noqa: E402
from app.main import create_app  # noqa: E402

BASE_URL = "http://testserver"
CSRF = {"X-QC-Agent": "1"}


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
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
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    maker = init_engine(os.environ["DATABASE_URL"], null_pool=True)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with maker() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
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

Create `backend/tests/db/__init__.py` (empty) and `backend/tests/db/test_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Project, ProjectMember, User


def _user(email: str = "a@example.com", account_type: str = "internal") -> User:
    return User(email=email, password_hash="x", display_name="A", account_type=account_type)


async def test_user_defaults(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.commit()
    assert user.id is not None
    assert user.is_active is True
    assert user.is_admin is False
    assert user.must_change_password is True
    assert user.mfa_enabled is False
    assert user.recovery_codes_hash == []
    assert user.failed_logins == 0
    assert user.created_at is not None


async def test_user_email_is_unique(db: AsyncSession) -> None:
    db.add(_user())
    await db.commit()
    db.add(_user())
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_account_type_is_constrained(db: AsyncSession) -> None:
    db.add(_user(account_type="partner"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_project_member_role_is_constrained(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.flush()
    project = Project(slug="demo", name="Demo", created_by=user.id)
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="superuser"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_audit_log_accepts_details(db: AsyncSession) -> None:
    db.add(AuditLog(action="test.event", details={"k": "v"}))
    await db.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db.models'`.

- [ ] **Step 3: Implement the models**

`backend/app/db/base.py`:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

`backend/app/db/models/identity.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ACCOUNT_TYPES = ("internal", "customer")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("account_type IN ('internal', 'customer')", name="account_type"),
        CheckConstraint("NOT (is_admin AND account_type = 'customer')", name="customer_not_admin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[str] = mapped_column(String(16))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text)
    mfa_pending_secret_enc: Mapped[str | None] = mapped_column(Text)
    mfa_last_counter: Mapped[int | None] = mapped_column(Integer)
    recovery_codes_hash: Mapped[list[str]] = mapped_column(JSONB, default=list)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`backend/app/db/models/projects.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PROJECT_ROLES = ("owner", "editor", "viewer", "client")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    client_name: Mapped[str | None] = mapped_column(String(200))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'editor', 'viewer', 'client')", name="role"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))
```

`backend/app/db/models/audit.py`:

```python
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
```

`backend/app/db/models/__init__.py`:

```python
from app.db.models.audit import AuditLog
from app.db.models.identity import ACCOUNT_TYPES, AuthSession, User
from app.db.models.projects import PROJECT_ROLES, Project, ProjectMember

__all__ = [
    "ACCOUNT_TYPES",
    "PROJECT_ROLES",
    "AuditLog",
    "AuthSession",
    "Project",
    "ProjectMember",
    "User",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: 5 passed.

- [ ] **Step 5: Alembic setup and first migration**

Run: `uv run alembic init -t async migrations`
Then replace `backend/migrations/env.py`:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db import models  # noqa: F401  - registers tables
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

In `backend/alembic.ini` leave `sqlalchemy.url` empty (the URL comes from settings) and set `file_template = %%(rev)s_%%(slug)s`.

Generate against the dev database (`.env` points at `qc_agent`):

```bash
uv run alembic revision --autogenerate --rev-id 0001 -m "identity and projects"
```

Rename the file to `migrations/versions/0001_identity_and_projects.py` if needed. Open it and confirm `upgrade()` creates exactly `users`, `projects`, `auth_sessions`, `project_members`, `audit_log`, including check constraints `ck_users_account_type`, `ck_users_customer_not_admin`, `ck_project_members_role` (autogenerate may omit check constraints; if so add them with `op.create_check_constraint(...)` matching the model names) and the unique constraints on `users.email`, `projects.slug`, `auth_sessions.token_hash`.

- [ ] **Step 6: Verify the migration matches the models**

Run:

```bash
uv run alembic upgrade head
uv run alembic check
```

Expected: upgrade succeeds; `check` prints `No new upgrade operations detected.`

- [ ] **Step 7: Commit**

```bash
uv run ruff check . && uv run mypy app
git add backend
git commit -m "feat(backend): add identity, project and audit models with first migration"
```

---

### Task 3: Security and utility primitives

**Files:**
- Create: `backend/app/core/passwords.py`, `backend/app/core/tokens.py`, `backend/app/core/crypto.py`, `backend/app/core/totp.py`, `backend/app/core/slugs.py`, `backend/app/core/emails.py`, `backend/app/core/ratelimit.py`
- Test: `backend/tests/core/__init__.py`, `backend/tests/core/test_passwords.py`, `test_tokens.py`, `test_crypto.py`, `test_totp.py`, `test_slugs.py`, `test_emails.py`, `test_ratelimit.py`

**Interfaces:**
- Produces:
  - `hash_password(password: str) -> str`, `verify_password(password_hash: str, password: str) -> bool`, `validate_new_password(password: str, *, email: str) -> list[str]`, `generate_temporary_password() -> str`, `burn_password_check(password: str) -> None` (constant-time dummy verify), `MIN_PASSWORD_LENGTH = 12`
  - `new_session_token() -> str`, `hash_token(token: str, secret: str) -> str`
  - `SecretBox(key: str)` with `.encrypt(plaintext: str) -> str`, `.decrypt(token: str) -> str`
  - `new_totp_secret() -> str`, `provisioning_uri(secret: str, email: str) -> str`, `match_totp(secret: str, code: str, *, now: datetime | None = None) -> int | None` (returns matched time-step counter), `generate_recovery_codes(count: int = 10) -> list[str]`, `hash_recovery_code(code: str) -> str`, `is_recovery_code_format(code: str) -> bool`
  - `slugify(text: str, max_len: int = 80) -> str`, `unique_slug(base: str, taken: set[str], max_len: int = 80) -> str`
  - `normalize_email(email: str) -> str`, `is_valid_email(email: str) -> bool`
  - `SlidingWindowLimiter(limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic)` with `.hit(key: str) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/core/__init__.py` (empty).

`backend/tests/core/test_passwords.py`:

```python
from app.core.passwords import (
    MIN_PASSWORD_LENGTH,
    generate_temporary_password,
    hash_password,
    validate_new_password,
    verify_password,
)


def test_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("correct-horse-battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct-horse-battery") is True
    assert verify_password(hashed, "wrong-password-123") is False


def test_verify_rejects_malformed_hash() -> None:
    assert verify_password("not-a-hash", "anything") is False


def test_policy_rejects_short_password() -> None:
    errors = validate_new_password("short", email="alice@example.com")
    assert f"Password must be at least {MIN_PASSWORD_LENGTH} characters." in errors


def test_policy_rejects_email_local_part() -> None:
    errors = validate_new_password("my-alice-password-1", email="Alice@example.com")
    assert "Password must not contain your e-mail name." in errors


def test_policy_accepts_good_password() -> None:
    assert validate_new_password("a-very-long-passphrase", email="alice@example.com") == []


def test_temporary_password_is_long_and_random() -> None:
    first, second = generate_temporary_password(), generate_temporary_password()
    assert len(first) >= MIN_PASSWORD_LENGTH
    assert first != second
```

`backend/tests/core/test_tokens.py`:

```python
from app.core.tokens import hash_token, new_session_token


def test_tokens_are_random_and_long() -> None:
    assert len(new_session_token()) >= 40
    assert new_session_token() != new_session_token()


def test_hash_is_deterministic_and_keyed() -> None:
    assert hash_token("t", "s1") == hash_token("t", "s1")
    assert hash_token("t", "s1") != hash_token("t", "s2")
    assert len(hash_token("t", "s1")) == 64
```

`backend/tests/core/test_crypto.py`:

```python
import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core.crypto import SecretBox


def test_roundtrip() -> None:
    box = SecretBox(Fernet.generate_key().decode())
    token = box.encrypt("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP"
    assert box.decrypt(token) == "JBSWY3DPEHPK3PXP"


def test_wrong_key_fails() -> None:
    token = SecretBox(Fernet.generate_key().decode()).encrypt("secret")
    with pytest.raises(InvalidToken):
        SecretBox(Fernet.generate_key().decode()).decrypt(token)
```

`backend/tests/core/test_totp.py`:

```python
from datetime import UTC, datetime, timedelta

import pyotp

from app.core.totp import (
    generate_recovery_codes,
    hash_recovery_code,
    is_recovery_code_format,
    match_totp,
    new_totp_secret,
    provisioning_uri,
)

NOW = datetime(2026, 10, 1, 9, 0, 15, tzinfo=UTC)


def test_current_code_matches_and_returns_counter() -> None:
    secret = new_totp_secret()
    code = pyotp.TOTP(secret).at(NOW)
    assert match_totp(secret, code, now=NOW) == pyotp.TOTP(secret).timecode(NOW)


def test_previous_step_is_accepted_two_steps_back_is_not() -> None:
    secret = new_totp_secret()
    totp = pyotp.TOTP(secret)
    assert match_totp(secret, totp.at(NOW - timedelta(seconds=30)), now=NOW) is not None
    assert match_totp(secret, totp.at(NOW - timedelta(seconds=60)), now=NOW) is None


def test_bad_codes_are_rejected() -> None:
    secret = new_totp_secret()
    assert match_totp(secret, "12345", now=NOW) is None
    assert match_totp(secret, "abcdef", now=NOW) is None


def test_code_with_spaces_is_accepted() -> None:
    secret = new_totp_secret()
    code = pyotp.TOTP(secret).at(NOW)
    assert match_totp(secret, f"{code[:3]} {code[3:]}", now=NOW) is not None


def test_provisioning_uri_names_issuer_and_account() -> None:
    uri = provisioning_uri(new_totp_secret(), "alice@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=QC-Agent" in uri
    assert "alice%40example.com" in uri


def test_recovery_codes() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(is_recovery_code_format(c) for c in codes)
    assert hash_recovery_code(codes[0]) == hash_recovery_code(f"  {codes[0].upper()} ")
    assert is_recovery_code_format("123456") is False
```

`backend/tests/core/test_slugs.py`:

```python
from app.core.slugs import slugify, unique_slug


def test_vietnamese_is_transliterated() -> None:
    assert slugify("Dự án Cổng Khách hàng") == "du-an-cong-khach-hang"
    assert slugify("Quản lý Đơn hàng") == "quan-ly-don-hang"


def test_symbols_collapse_and_trim() -> None:
    assert slugify("  SRS v2.1 (final)!! ") == "srs-v2-1-final"


def test_empty_becomes_untitled() -> None:
    assert slugify("!!!") == "untitled"


def test_max_length_does_not_end_with_hyphen() -> None:
    slug = slugify("a" * 79 + " b", max_len=80)
    assert len(slug) <= 80
    assert not slug.endswith("-")


def test_unique_slug_adds_suffix() -> None:
    assert unique_slug("demo", set()) == "demo"
    assert unique_slug("demo", {"demo"}) == "demo-2"
    assert unique_slug("demo", {"demo", "demo-2"}) == "demo-3"


def test_unique_slug_respects_max_length() -> None:
    base = "x" * 80
    result = unique_slug(base, {base})
    assert result.endswith("-2")
    assert len(result) == 80
```

`backend/tests/core/test_emails.py`:

```python
from app.core.emails import is_valid_email, normalize_email


def test_normalize() -> None:
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"


def test_validity() -> None:
    assert is_valid_email("alice@example.com")
    assert not is_valid_email("alice")
    assert not is_valid_email("alice@example")
    assert not is_valid_email("a lice@example.com")
```

`backend/tests/core/test_ratelimit.py`:

```python
from app.core.ratelimit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limit_and_window() -> None:
    clock = FakeClock()
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    assert limiter.hit("ip") is True
    assert limiter.hit("ip") is True
    assert limiter.hit("ip") is False
    assert limiter.hit("other-ip") is True
    clock.now += 61
    assert limiter.hit("ip") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core -v`
Expected: FAIL with `ModuleNotFoundError` for `app.core.passwords` (and the others).

- [ ] **Step 3: Implement the primitives**

`backend/app/core/passwords.py`:

```python
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("dummy-password-used-for-constant-time-checks")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown e-mails are not distinguishable."""
    verify_password(_DUMMY_HASH, password)


def validate_new_password(password: str, *, email: str) -> list[str]:
    errors: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    local_part = email.split("@", 1)[0].strip().lower()
    if len(local_part) >= 3 and local_part in password.lower():
        errors.append("Password must not contain your e-mail name.")
    return errors


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(12)  # 16 characters
```

`backend/app/core/tokens.py`:

```python
import hashlib
import hmac
import secrets


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
```

`backend/app/core/crypto.py`:

```python
from cryptography.fernet import Fernet


class SecretBox:
    """Symmetric encryption for secrets stored in the database."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()
```

`backend/app/core/totp.py`:

```python
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

import pyotp

ISSUER = "QC-Agent"
_STEP = timedelta(seconds=30)
_RECOVERY_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{8}$")


def new_totp_secret() -> str:
    return str(pyotp.random_base32())


def provisioning_uri(secret: str, email: str) -> str:
    return str(pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER))


def match_totp(secret: str, code: str, *, now: datetime | None = None) -> int | None:
    """Return the matched time-step counter (current or one step either side), or None."""
    cleaned = code.replace(" ", "").strip()
    if len(cleaned) != 6 or not cleaned.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    moment = now or datetime.now(UTC)
    for drift in (-1, 0, 1):
        at = moment + drift * _STEP
        if hmac.compare_digest(str(totp.at(at)), cleaned):
            return int(totp.timecode(at))
    return None


def _normalize_recovery(code: str) -> str:
    return code.replace(" ", "").strip().lower()


def is_recovery_code_format(code: str) -> bool:
    return _RECOVERY_RE.fullmatch(_normalize_recovery(code)) is not None


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(_normalize_recovery(code).encode()).hexdigest()
```

`backend/app/core/slugs.py`:

```python
import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 80) -> str:
    replaced = text.replace("đ", "d").replace("Đ", "D")
    ascii_text = unicodedata.normalize("NFKD", replaced).encode("ascii", "ignore").decode()
    slug = _NON_ALNUM.sub("-", ascii_text.lower()).strip("-")
    slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def unique_slug(base: str, taken: set[str], max_len: int = 80) -> str:
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: max_len - len(suffix)].rstrip("-") + suffix
        if candidate not in taken:
            return candidate
        n += 1
```

`backend/app/core/emails.py`:

```python
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return len(email) <= 320 and _EMAIL_RE.fullmatch(email) is not None
```

`backend/app/core/ratelimit.py`:

```python
import time
from collections import defaultdict, deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """In-process limiter. Correct for a single backend process (Phase 1 deployment)."""

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        now = self._clock()
        bucket = self._hits[key]
        while bucket and bucket[0] <= now - self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run mypy app
git add backend/app/core backend/tests/core
git commit -m "feat(backend): add password, token, encryption, TOTP, slug, e-mail and rate-limit primitives"
```

---
### Task 4: Login, sessions, logout, me, lockout, rate limit

**Files:**
- Create: `backend/app/services/__init__.py`, `backend/app/services/context.py`, `backend/app/services/audit.py`, `backend/app/services/auth.py`, `backend/app/schemas/__init__.py`, `backend/app/schemas/auth.py`, `backend/app/api/cookies.py`, `backend/app/api/routes/auth.py`, `backend/tests/factories.py`
- Modify: `backend/app/api/deps.py` (append), `backend/app/main.py` (limiter + router)
- Test: `backend/tests/api/test_auth_login.py`

**Interfaces:**
- Consumes: Task 3 primitives; models from Task 2; `AppSettings`, `DbSession` (Task 1).
- Produces:
  - `app.services.audit.record(db, action: str, *, user_id=None, project_id=None, target_type=None, target_id=None, details=None) -> None` (adds a row, does not commit)
  - `app.services.auth.LoginResult(user: User, token: str, auth_session: AuthSession)`; `authenticate(db, email: str, password: str, settings: Settings, *, ip: str | None, user_agent: str | None, now: datetime | None = None) -> LoginResult | None`
  - `app.api.cookies.SESSION_COOKIE = "qc_session"`, `set_session_cookie(response, token, settings)`, `clear_session_cookie(response, settings)`
  - `app.services.context.SessionContext(auth_session: AuthSession, user: User)` dataclass (import it from `app.services.context` everywhere; mypy strict forbids implicit re-exports); `app.api.deps.session_context` dependency; alias `SessionCtx`; `auth_rate_limit(request) -> None` (429 when exceeded)
  - `app.api.routes.auth.router` with `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`; helper `me_response(ctx: SessionContext) -> MeResponse`
  - Schemas: `LoginRequest(email, password)`, `LoginResponse(mfa_enrolled: bool, must_change_password: bool)`, `MeResponse(id, email, display_name, account_type, is_admin, mfa_enabled, mfa_verified, must_change_password)`
  - Test helpers in `tests/factories.py`: `DEFAULT_PASSWORD`, `make_user(db, settings, **kw) -> User`, `make_session_token(db, settings, user, *, mfa_verified=True, expires_in=timedelta(hours=8)) -> str`, `reload(db, model, id)`

- [ ] **Step 1: Write the test helpers**

`backend/tests/factories.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.passwords import hash_password
from app.core.tokens import hash_token, new_session_token
from app.db.models import AuthSession, User

DEFAULT_PASSWORD = "correct-horse-battery-staple"
T = TypeVar("T")


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


async def reload(db: AsyncSession, model: type[T], obj_id: uuid.UUID | Any) -> T | None:
    db.expire_all()
    return await db.get(model, obj_id)
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/api/test_auth_login.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, AuthSession, User
from tests.factories import DEFAULT_PASSWORD, make_session_token, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def _login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD):  # type: ignore[no-untyped-def]
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_sets_cookie_and_requires_mfa(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    response = await _login(client, "alice@example.com")
    assert response.status_code == 200
    assert response.json() == {"mfa_enrolled": False, "must_change_password": False}
    assert "qc_session" in client.cookies
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["mfa_verified"] is False
    sessions = (await db.scalars(select(AuthSession))).all()
    assert len(sessions) == 1 and sessions[0].mfa_verified is False
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "auth.login" in actions


async def test_email_case_and_spaces_are_ignored(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    response = await _login(client, "  Alice@Example.COM ")
    assert response.status_code == 200


async def test_wrong_password_and_unknown_email_share_one_message(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    wrong = await _login(client, "alice@example.com", "not-the-password")
    unknown = await _login(client, "bob@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid e-mail or password."}


async def test_lockout_after_five_failures(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    for _ in range(5):
        assert (await _login(client, "alice@example.com", "wrong-password")).status_code == 401
    assert (await _login(client, "alice@example.com")).status_code == 401  # locked
    locked = await reload(db, User, user.id)
    assert locked is not None and locked.locked_until is not None
    locked.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert (await _login(client, "alice@example.com")).status_code == 200


async def test_inactive_user_cannot_log_in(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings, is_active=False)
    assert (await _login(client, "alice@example.com")).status_code == 401


async def test_logout_revokes_session(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    await _login(client, "alice@example.com")
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    session = (await db.scalars(select(AuthSession))).one()
    assert session.revoked_at is not None


async def test_revoked_or_expired_token_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    expired = await make_session_token(db, settings, user, expires_in=timedelta(seconds=-1))
    assert (await (await make_client(expired)).get("/api/v1/auth/me")).status_code == 401
    valid = await make_session_token(db, settings, user)
    c = await make_client(valid)
    assert (await c.get("/api/v1/auth/me")).status_code == 200
    assert (await c.post("/api/v1/auth/logout")).status_code == 204
    assert (await (await make_client(valid)).get("/api/v1/auth/me")).status_code == 401


async def test_me_without_cookie_is_401(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_login_is_rate_limited(
    make_app: Callable[..., FastAPI], make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    app = make_app(rate_limit_auth_per_5min=3)
    c = await make_client(app_=app)
    for _ in range(3):
        await _login(c, "nobody@example.com")
    response = await _login(c, "nobody@example.com")
    assert response.status_code == 429


async def test_cookie_flags_when_secure(
    make_app: Callable[..., FastAPI], make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    c = await make_client(app_=make_app(cookie_secure=True))
    response = await _login(c, "alice@example.com")
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_auth_login.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services'` or 404 responses.

- [ ] **Step 4: Implement audit, auth service, schemas, cookies, deps, routes**

`backend/app/services/__init__.py` and `backend/app/schemas/__init__.py`: empty.

`backend/app/services/context.py` (shared by the API layer and services; services never import `app.api`):

```python
from dataclasses import dataclass

from app.db.models import AuthSession, User


@dataclass
class SessionContext:
    auth_session: AuthSession
    user: User
```

`backend/app/services/audit.py`:

```python
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def record(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            user_id=user_id,
            project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    )
```

`backend/app/services/auth.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.emails import normalize_email
from app.core.passwords import burn_password_check, verify_password
from app.core.tokens import hash_token, new_session_token
from app.db.models import AuthSession, User
from app.services import audit


@dataclass
class LoginResult:
    user: User
    token: str
    auth_session: AuthSession


def register_failure(user: User, settings: Settings, now: datetime) -> bool:
    """Count a failed credential check. Returns True when the account just got locked."""
    user.failed_logins += 1
    if user.failed_logins >= settings.login_max_failures:
        user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
        user.failed_logins = 0
        return True
    return False


def is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now


async def authenticate(
    db: AsyncSession,
    email: str,
    password: str,
    settings: Settings,
    *,
    ip: str | None,
    user_agent: str | None,
    now: datetime | None = None,
) -> LoginResult | None:
    moment = now or datetime.now(UTC)
    user = await db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or not user.is_active:
        burn_password_check(password)
        return None
    if is_locked(user, moment):
        burn_password_check(password)
        await audit.record(db, "auth.login_blocked_locked", user_id=user.id)
        await db.commit()
        return None
    if not verify_password(user.password_hash, password):
        locked = register_failure(user, settings, moment)
        await audit.record(db, "auth.login_failed", user_id=user.id, details={"locked": locked})
        await db.commit()
        return None
    user.failed_logins = 0
    user.locked_until = None
    token = new_session_token()
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token, settings.session_secret),
        expires_at=moment + timedelta(hours=settings.session_ttl_hours),
        ip=ip,
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(auth_session)
    await audit.record(db, "auth.login", user_id=user.id)
    await db.commit()
    return LoginResult(user=user, token=token, auth_session=auth_session)
```

`backend/app/schemas/auth.py`:

```python
import uuid

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class LoginResponse(BaseModel):
    mfa_enrolled: bool
    must_change_password: bool


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    account_type: str
    is_admin: bool
    mfa_enabled: bool
    mfa_verified: bool
    must_change_password: bool


class CodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class EnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)
```

`backend/app/api/cookies.py`:

```python
from fastapi import Response

from app.core.config import Settings

SESSION_COOKIE = "qc_session"


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
```

Append to `backend/app/api/deps.py` (keep the existing content, merge imports at the top):

```python
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.api.cookies import SESSION_COOKIE
from app.core.tokens import hash_token
from app.db.models import AuthSession, User
from app.services.context import SessionContext


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
    if auth_session is None or auth_session.revoked_at is not None or auth_session.expires_at <= now:
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
```

`backend/app/api/routes/auth.py`:

```python
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.cookies import clear_session_cookie, set_session_cookie
from app.api.deps import AppSettings, DbSession, SessionCtx, auth_rate_limit
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from app.services import audit
from app.services.auth import authenticate
from app.services.context import SessionContext

router = APIRouter(prefix="/auth", tags=["auth"])


def me_response(ctx: SessionContext) -> MeResponse:
    user = ctx.user
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        account_type=user.account_type,
        is_admin=user.is_admin,
        mfa_enabled=user.mfa_enabled,
        mfa_verified=ctx.auth_session.mfa_verified,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(auth_rate_limit)])
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession, settings: AppSettings
) -> LoginResponse:
    result = await authenticate(
        db,
        body.email,
        body.password,
        settings,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid e-mail or password.")
    set_session_cookie(response, result.token, settings)
    return LoginResponse(
        mfa_enrolled=result.user.mfa_enabled,
        must_change_password=result.user.must_change_password,
    )


@router.get("/me", response_model=MeResponse)
async def me(ctx: SessionCtx) -> MeResponse:
    return me_response(ctx)


@router.post("/logout", status_code=204)
async def logout(ctx: SessionCtx, response: Response, db: DbSession, settings: AppSettings) -> None:
    ctx.auth_session.revoked_at = datetime.now(UTC)
    await audit.record(db, "auth.logout", user_id=ctx.user.id)
    await db.commit()
    clear_session_cookie(response, settings)
```

Modify `backend/app/main.py`: add imports and, inside `create_app` after `app.state.settings = app_settings`:

```python
from app.api.routes import auth, health
from app.core.ratelimit import SlidingWindowLimiter
```

```python
    app.state.auth_limiter = SlidingWindowLimiter(
        limit=app_settings.rate_limit_auth_per_5min, window_seconds=300
    )
```

and register the router next to health:

```python
    app.include_router(auth.router, prefix=API_PREFIX)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_auth_login.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run mypy app
git add backend
git commit -m "feat(backend): add password login, server-side sessions, lockout and rate limiting"
```

---

### Task 5: Mandatory TOTP MFA with recovery codes

**Files:**
- Create: `backend/app/services/mfa.py`
- Modify: `backend/app/api/deps.py` (append), `backend/app/api/routes/auth.py` (append)
- Test: `backend/tests/api/test_auth_mfa.py`

**Interfaces:**
- Consumes: `SessionContext`, `session_context`, `auth_rate_limit`, `me_response` (Task 4); `register_failure`, `is_locked` from `app.services.auth`; TOTP and `SecretBox` (Task 3).
- Produces:
  - `app.services.mfa.start_enrolment(db, ctx, box) -> tuple[str, str]` (secret, otpauth URI); `confirm_enrolment(db, ctx, box, code) -> list[str] | None` (recovery codes, or None if code invalid); `verify_second_factor(db, ctx, box, settings, code, *, now=None) -> bool`; exception `MfaStateError(message)`
  - `app.api.deps.secret_box_dep(settings) -> SecretBox`, alias `Box`; `mfa_context` dependency, alias `MfaCtx` (401 `"MFA verification required."` when the session has not passed MFA)
  - Routes `POST /auth/mfa/enroll`, `POST /auth/mfa/confirm`, `POST /auth/mfa/verify`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_auth_mfa.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, User
from tests.factories import DEFAULT_PASSWORD, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def test_enrol_and_confirm(client: AsyncClient, db: AsyncSession, settings: Settings) -> None:
    await make_user(db, settings)
    await _login(client)
    enrol = await client.post("/api/v1/auth/mfa/enroll")
    assert enrol.status_code == 200
    secret = enrol.json()["secret"]
    assert "issuer=QC-Agent" in enrol.json()["otpauth_uri"]
    confirm = await client.post(
        "/api/v1/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirm.status_code == 200
    assert len(confirm.json()["recovery_codes"]) == 10
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["mfa_enabled"] is True and me["mfa_verified"] is True
    user = (await db.scalars(select(User))).one()
    assert user.mfa_secret_enc is not None and secret not in user.mfa_secret_enc
    assert user.mfa_pending_secret_enc is None


async def test_confirm_with_wrong_code_fails(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    await _login(client)
    await client.post("/api/v1/auth/mfa/enroll")
    response = await client.post("/api/v1/auth/mfa/confirm", json={"code": "123456x"})
    assert response.status_code == 400


async def test_confirm_without_enrolment_is_conflict(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    await _login(client)
    response = await client.post("/api/v1/auth/mfa/confirm", json={"code": "123456"})
    assert response.status_code == 409


async def test_enrol_when_already_enabled_is_conflict(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings, mfa_secret=SECRET)
    await _login(client)
    assert (await client.post("/api/v1/auth/mfa/enroll")).status_code == 409


async def test_verify_marks_session(client: AsyncClient, db: AsyncSession, settings: Settings) -> None:
    await make_user(db, settings, mfa_secret=SECRET)
    await _login(client)
    response = await client.post("/api/v1/auth/mfa/verify", json={"code": pyotp.TOTP(SECRET).now()})
    assert response.status_code == 200
    assert response.json()["mfa_verified"] is True
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "auth.mfa_verified" in actions


async def test_replayed_code_is_rejected(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings, mfa_secret=SECRET)
    code = pyotp.TOTP(SECRET).now()
    first, second = await make_client(), await make_client()
    await _login(first)
    await _login(second)
    assert (await first.post("/api/v1/auth/mfa/verify", json={"code": code})).status_code == 200
    assert (await second.post("/api/v1/auth/mfa/verify", json={"code": code})).status_code == 401


async def test_recovery_code_works_once(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    await make_user(db, settings)
    enrolling = await make_client()
    await _login(enrolling)
    secret = (await enrolling.post("/api/v1/auth/mfa/enroll")).json()["secret"]
    codes = (
        await enrolling.post("/api/v1/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    ).json()["recovery_codes"]
    a, b = await make_client(), await make_client()
    await _login(a)
    await _login(b)
    assert (await a.post("/api/v1/auth/mfa/verify", json={"code": codes[0]})).status_code == 200
    assert (await b.post("/api/v1/auth/mfa/verify", json={"code": codes[0]})).status_code == 401
    user = (await db.scalars(select(User))).one()
    await db.refresh(user)
    assert len(user.recovery_codes_hash) == 9


async def test_five_bad_codes_lock_account_and_revoke_session(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings, mfa_secret=SECRET)
    await _login(client)
    valid = pyotp.TOTP(SECRET).now()
    bad = "000000" if valid != "000000" else "111111"
    for _ in range(5):
        response = await client.post("/api/v1/auth/mfa/verify", json={"code": bad})
        assert response.status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    locked = await reload(db, User, user.id)
    assert locked is not None and locked.locked_until is not None
    assert locked.locked_until > datetime.now(UTC) + timedelta(minutes=10)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_auth_mfa.py -v`
Expected: FAIL — 404 for `/api/v1/auth/mfa/enroll`.

- [ ] **Step 3: Implement the MFA service, deps and routes**

`backend/app/services/mfa.py`:

```python
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import SecretBox
from app.core.totp import (
    generate_recovery_codes,
    hash_recovery_code,
    is_recovery_code_format,
    match_totp,
    new_totp_secret,
    provisioning_uri,
)
from app.services import audit
from app.services.auth import is_locked, register_failure
from app.services.context import SessionContext


class MfaStateError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def start_enrolment(db: AsyncSession, ctx: SessionContext, box: SecretBox) -> tuple[str, str]:
    if ctx.user.mfa_enabled:
        raise MfaStateError("MFA is already enabled.")
    secret = new_totp_secret()
    ctx.user.mfa_pending_secret_enc = box.encrypt(secret)
    await audit.record(db, "auth.mfa_enrol_started", user_id=ctx.user.id)
    await db.commit()
    return secret, provisioning_uri(secret, ctx.user.email)


async def confirm_enrolment(
    db: AsyncSession, ctx: SessionContext, box: SecretBox, code: str
) -> list[str] | None:
    user = ctx.user
    if user.mfa_enabled:
        raise MfaStateError("MFA is already enabled.")
    if user.mfa_pending_secret_enc is None:
        raise MfaStateError("Start MFA enrolment first.")
    counter = match_totp(box.decrypt(user.mfa_pending_secret_enc), code)
    if counter is None:
        return None
    codes = generate_recovery_codes()
    user.mfa_secret_enc = user.mfa_pending_secret_enc
    user.mfa_pending_secret_enc = None
    user.mfa_enabled = True
    user.mfa_last_counter = counter
    user.recovery_codes_hash = [hash_recovery_code(c) for c in codes]
    ctx.auth_session.mfa_verified = True
    await audit.record(db, "auth.mfa_enrolled", user_id=user.id)
    await db.commit()
    return codes


async def verify_second_factor(
    db: AsyncSession,
    ctx: SessionContext,
    box: SecretBox,
    settings: Settings,
    code: str,
    *,
    now: datetime | None = None,
) -> bool:
    user = ctx.user
    moment = now or datetime.now(UTC)
    if not user.mfa_enabled or user.mfa_secret_enc is None:
        raise MfaStateError("MFA is not enabled.")
    if is_locked(user, moment):
        return False
    ok = False
    if is_recovery_code_format(code):
        hashed = hash_recovery_code(code)
        if hashed in user.recovery_codes_hash:
            user.recovery_codes_hash = [h for h in user.recovery_codes_hash if h != hashed]
            await audit.record(db, "auth.recovery_code_used", user_id=user.id)
            ok = True
    else:
        counter = match_totp(box.decrypt(user.mfa_secret_enc), code, now=moment)
        if counter is not None and (
            user.mfa_last_counter is None or counter > user.mfa_last_counter
        ):
            user.mfa_last_counter = counter
            ok = True
    if ok:
        user.failed_logins = 0
        ctx.auth_session.mfa_verified = True
        await audit.record(db, "auth.mfa_verified", user_id=user.id)
    else:
        if register_failure(user, settings, moment):
            ctx.auth_session.revoked_at = moment
        await audit.record(db, "auth.mfa_failed", user_id=user.id)
    await db.commit()
    return ok
```

Append to `backend/app/api/deps.py`:

```python
from app.core.crypto import SecretBox


def secret_box_dep(settings: AppSettings) -> SecretBox:
    return SecretBox(settings.secret_encryption_key)


Box = Annotated[SecretBox, Depends(secret_box_dep)]


async def mfa_context(ctx: SessionCtx) -> SessionContext:
    if not ctx.auth_session.mfa_verified:
        raise HTTPException(status_code=401, detail="MFA verification required.")
    return ctx


MfaCtx = Annotated[SessionContext, Depends(mfa_context)]
```

Append to `backend/app/api/routes/auth.py` (merge imports at the top):

```python
from app.api.deps import Box
from app.schemas.auth import CodeRequest, EnrollResponse, RecoveryCodesResponse
from app.services.mfa import (
    MfaStateError,
    confirm_enrolment,
    start_enrolment,
    verify_second_factor,
)


@router.post("/mfa/enroll", response_model=EnrollResponse, dependencies=[Depends(auth_rate_limit)])
async def mfa_enroll(ctx: SessionCtx, db: DbSession, box: Box) -> EnrollResponse:
    try:
        secret, uri = await start_enrolment(db, ctx, box)
    except MfaStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return EnrollResponse(secret=secret, otpauth_uri=uri)


@router.post(
    "/mfa/confirm", response_model=RecoveryCodesResponse, dependencies=[Depends(auth_rate_limit)]
)
async def mfa_confirm(
    body: CodeRequest, ctx: SessionCtx, db: DbSession, box: Box
) -> RecoveryCodesResponse:
    try:
        codes = await confirm_enrolment(db, ctx, box, body.code)
    except MfaStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    if codes is None:
        raise HTTPException(status_code=400, detail="Invalid code.")
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/mfa/verify", response_model=MeResponse, dependencies=[Depends(auth_rate_limit)])
async def mfa_verify(
    body: CodeRequest, ctx: SessionCtx, db: DbSession, box: Box, settings: AppSettings
) -> MeResponse:
    try:
        ok = await verify_second_factor(db, ctx, box, settings, body.code)
    except MfaStateError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid code.")
    return me_response(ctx)
```

Note: services import `SessionContext` from `app.services.context`, never from `app.api`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api -v`
Expected: all passed (login + MFA + health).

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run mypy app
git add backend
git commit -m "feat(backend): add mandatory TOTP MFA with replay protection and recovery codes"
```

---

### Task 6: Password change and fully-authenticated user dependency

**Files:**
- Modify: `backend/app/services/auth.py` (append), `backend/app/api/deps.py` (append), `backend/app/api/routes/auth.py` (append)
- Test: `backend/tests/api/test_auth_password.py`

**Interfaces:**
- Consumes: `MfaCtx`, `SessionContext` (Task 5); password primitives (Task 3).
- Produces:
  - `app.services.auth.revoke_user_sessions(db, user_id, *, except_session_id=None, now=None) -> None` (no commit)
  - `app.services.auth.PasswordChangeError(messages: list[str])`; `change_password(db, ctx, current_password, new_password) -> None`
  - `app.api.deps.current_user` dependency → `User` (requires MFA-verified session and `must_change_password == False`, else 403 `"Password change required."`), alias `CurrentUser`; `require_admin` → `User` (403 `"Administrator access required."`), alias `AdminUser`
  - Route `POST /auth/change-password` (204)

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_auth_password.py`:

```python
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.config import Settings
from app.core.passwords import verify_password
from app.db.models import User
from tests.factories import DEFAULT_PASSWORD, make_session_token, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]
NEW_PASSWORD = "a-brand-new-passphrase"


def _with_probe_routes(app: FastAPI) -> FastAPI:
    @app.get("/api/v1/_probe/user")
    async def probe_user(user: CurrentUser) -> dict[str, str]:
        return {"email": user.email}

    @app.get("/api/v1/_probe/admin")
    async def probe_admin(user: AdminUser) -> dict[str, str]:
        return {"email": user.email}

    return app


async def test_current_user_requires_mfa_and_password_change(
    app: FastAPI, make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _with_probe_routes(app)
    user = await make_user(db, settings, must_change_password=True)
    no_mfa = await make_client(await make_session_token(db, settings, user, mfa_verified=False))
    assert (await no_mfa.get("/api/v1/_probe/user")).status_code == 401
    mfa = await make_client(await make_session_token(db, settings, user))
    response = await mfa.get("/api/v1/_probe/user")
    assert response.status_code == 403
    assert response.json() == {"detail": "Password change required."}


async def test_require_admin(
    app: FastAPI, make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _with_probe_routes(app)
    member = await make_user(db, settings)
    admin = await make_user(db, settings, email="root@example.com", is_admin=True)
    assert (
        await (await make_client(await make_session_token(db, settings, member))).get(
            "/api/v1/_probe/admin"
        )
    ).status_code == 403
    assert (
        await (await make_client(await make_session_token(db, settings, admin))).get(
            "/api/v1/_probe/admin"
        )
    ).status_code == 200


async def test_change_password_success_revokes_other_sessions(
    app: FastAPI, make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _with_probe_routes(app)
    user = await make_user(db, settings, must_change_password=True)
    other = await make_client(await make_session_token(db, settings, user))
    current = await make_client(await make_session_token(db, settings, user))
    response = await current.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204
    assert (await current.get("/api/v1/_probe/user")).status_code == 200
    assert (await other.get("/api/v1/auth/me")).status_code == 401
    refreshed = await reload(db, User, user.id)
    assert refreshed is not None
    assert refreshed.must_change_password is False
    assert verify_password(refreshed.password_hash, NEW_PASSWORD)


async def test_change_password_rejects_wrong_current(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, user))
    response = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": ["Current password is incorrect."]}


async def test_change_password_enforces_policy_and_difference(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, user))
    weak = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 400
    assert "Password must be at least 12 characters." in weak.json()["detail"]
    same = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD},
    )
    assert same.status_code == 400
    assert "New password must differ from the current password." in same.json()["detail"]


async def test_change_password_requires_mfa(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, user, mfa_verified=False))
    response = await c.post(
        "/api/v1/auth/change-password",
        json={"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_auth_password.py -v`
Expected: FAIL with `ImportError: cannot import name 'AdminUser'`.

- [ ] **Step 3: Implement**

Append to `backend/app/services/auth.py` (merge imports):

```python
import uuid

from sqlalchemy import update

from app.core.passwords import hash_password, validate_new_password
from app.services.context import SessionContext


async def revoke_user_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    except_session_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> None:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    await db.execute(stmt)


class PasswordChangeError(Exception):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


async def change_password(
    db: AsyncSession, ctx: SessionContext, current_password: str, new_password: str
) -> None:
    user = ctx.user
    if not verify_password(user.password_hash, current_password):
        raise PasswordChangeError(["Current password is incorrect."])
    errors = validate_new_password(new_password, email=user.email)
    if verify_password(user.password_hash, new_password):
        errors.append("New password must differ from the current password.")
    if errors:
        raise PasswordChangeError(errors)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await revoke_user_sessions(db, user.id, except_session_id=ctx.auth_session.id)
    await audit.record(db, "auth.password_changed", user_id=user.id)
    await db.commit()
```

Merge these imports with the existing ones at the top of the file.

Append to `backend/app/api/deps.py`:

```python
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
```

Append to `backend/app/api/routes/auth.py` (merge imports):

```python
from app.api.deps import MfaCtx
from app.schemas.auth import ChangePasswordRequest
from app.services.auth import PasswordChangeError, change_password


@router.post(
    "/change-password", status_code=204, dependencies=[Depends(auth_rate_limit)]
)
async def change_password_route(body: ChangePasswordRequest, ctx: MfaCtx, db: DbSession) -> None:
    try:
        await change_password(db, ctx, body.current_password, body.new_password)
    except PasswordChangeError as exc:
        raise HTTPException(status_code=400, detail=exc.messages) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run mypy app
git add backend
git commit -m "feat(backend): add password change and authenticated-user dependencies"
```

---
### Task 7: Admin user management and `create-admin` CLI

**Files:**
- Create: `backend/app/schemas/users.py`, `backend/app/services/users.py`, `backend/app/api/routes/users.py`, `backend/app/cli.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/api/test_users.py`, `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `AdminUser`, `DbSession` (Task 6); `revoke_user_sessions` (Task 6); `normalize_email`, `is_valid_email`, `generate_temporary_password`, `hash_password` (Task 3).
- Produces:
  - `app.services.users`: `DuplicateEmail`, `SelfLockout` exceptions; `create_user(db, *, email, display_name, account_type, is_admin, actor_id) -> tuple[User, str]`; `update_user(db, user, *, actor, display_name=None, is_active=None, is_admin=None) -> User`; `reset_password(db, user, *, actor_id) -> str`; `reset_mfa(db, user, *, actor_id) -> None`
  - Routes: `GET /users`, `POST /users` (201), `PATCH /users/{user_id}`, `POST /users/{user_id}/reset-password`, `POST /users/{user_id}/reset-mfa` (204)
  - Schemas: `UserOut`, `CreateUserRequest`, `CreateUserResponse(user: UserOut, temporary_password: str)`, `UpdateUserRequest`, `TemporaryPasswordResponse(temporary_password: str)`
  - `app.cli.create_admin(db, email, display_name) -> str`; `app.cli.main(argv: list[str] | None = None) -> int`; `app.cli.run() -> None`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_users.py`:

```python
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, User
from tests.factories import make_session_token, make_user, reload

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def _admin_client(make_client: MakeClient, db: AsyncSession, settings: Settings):  # type: ignore[no-untyped-def]
    admin = await make_user(db, settings, email="root@example.com", display_name="Root", is_admin=True)
    return admin, await make_client(await make_session_token(db, settings, admin))


async def test_non_admin_is_forbidden(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    member = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, member))
    assert (await c.get("/api/v1/users")).status_code == 403


async def test_create_user_returns_temporary_password_that_works(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    response = await admin.post(
        "/api/v1/users",
        json={"email": "  Bob@Example.com ", "display_name": "Bob", "account_type": "internal"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "bob@example.com"
    assert body["user"]["must_change_password"] is True
    login = await (await make_client()).post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": body["temporary_password"]},
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    assert "user.create" in (await db.scalars(select(AuditLog.action))).all()


async def test_duplicate_email_is_case_insensitive(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    payload = {"display_name": "Bob", "account_type": "internal"}
    assert (await admin.post("/api/v1/users", json={"email": "bob@example.com", **payload})).status_code == 201
    dup = await admin.post("/api/v1/users", json={"email": "BOB@example.com", **payload})
    assert dup.status_code == 409


async def test_validation_errors(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    bad_email = await admin.post(
        "/api/v1/users", json={"email": "bob", "display_name": "Bob", "account_type": "internal"}
    )
    customer_admin = await admin.post(
        "/api/v1/users",
        json={"email": "c@client.com", "display_name": "C", "account_type": "customer", "is_admin": True},
    )
    assert bad_email.status_code == 422
    assert customer_admin.status_code == 422


async def test_reset_password_revokes_sessions_and_unlocks(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    user = await make_user(db, settings)
    old = await make_client(await make_session_token(db, settings, user))
    assert (await old.get("/api/v1/auth/me")).status_code == 200
    response = await admin.post(f"/api/v1/users/{user.id}/reset-password")
    assert response.status_code == 200
    assert len(response.json()["temporary_password"]) >= 12
    assert (await old.get("/api/v1/auth/me")).status_code == 401
    refreshed = await reload(db, User, user.id)
    assert refreshed is not None and refreshed.must_change_password is True
    assert refreshed.locked_until is None


async def test_deactivate_revokes_sessions_and_blocks_login(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    user = await make_user(db, settings)
    old = await make_client(await make_session_token(db, settings, user))
    response = await admin.patch(f"/api/v1/users/{user.id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (await old.get("/api/v1/auth/me")).status_code == 401


async def test_admin_cannot_lock_themselves_out(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    root, admin = await _admin_client(make_client, db, settings)
    assert (await admin.patch(f"/api/v1/users/{root.id}", json={"is_active": False})).status_code == 409
    assert (await admin.patch(f"/api/v1/users/{root.id}", json={"is_admin": False})).status_code == 409


async def test_cannot_promote_customer_to_admin(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    customer = await make_user(db, settings, email="c@client.com", account_type="customer")
    response = await admin.patch(f"/api/v1/users/{customer.id}", json={"is_admin": True})
    assert response.status_code == 422


async def test_reset_mfa(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    user = await make_user(db, settings, mfa_secret="JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")
    old = await make_client(await make_session_token(db, settings, user))
    assert (await admin.post(f"/api/v1/users/{user.id}/reset-mfa")).status_code == 204
    assert (await old.get("/api/v1/auth/me")).status_code == 401
    refreshed = await reload(db, User, user.id)
    assert refreshed is not None
    assert refreshed.mfa_enabled is False
    assert refreshed.mfa_secret_enc is None
    assert refreshed.recovery_codes_hash == []


async def test_unknown_user_is_404(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    _, admin = await _admin_client(make_client, db, settings)
    response = await admin.post("/api/v1/users/00000000-0000-0000-0000-000000000000/reset-mfa")
    assert response.status_code == 404
```

`backend/tests/test_cli.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import create_admin
from app.core.passwords import verify_password
from app.db.models import User
from app.services.users import DuplicateEmail


async def test_create_admin(db: AsyncSession) -> None:
    temp = await create_admin(db, "Root@Example.com", "Root")
    user = (await db.scalars(select(User))).one()
    assert user.email == "root@example.com"
    assert user.is_admin is True
    assert user.account_type == "internal"
    assert user.must_change_password is True
    assert verify_password(user.password_hash, temp)


async def test_create_admin_duplicate(db: AsyncSession) -> None:
    await create_admin(db, "root@example.com", "Root")
    with pytest.raises(DuplicateEmail):
        await create_admin(db, "root@example.com", "Root")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_users.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cli'` and 404s.

- [ ] **Step 3: Implement schemas, service, routes, CLI**

`backend/app/schemas/users.py`:

```python
import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.emails import is_valid_email, normalize_email


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    account_type: str
    is_admin: bool
    is_active: bool
    mfa_enabled: bool
    must_change_password: bool
    locked_until: datetime | None


class CreateUserRequest(BaseModel):
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    account_type: Literal["internal", "customer"]
    is_admin: bool = False

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        email = normalize_email(value)
        if not is_valid_email(email):
            raise ValueError("Enter a valid e-mail address.")
        return email

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Display name is required.")
        return value.strip()

    @model_validator(mode="after")
    def _customer_not_admin(self) -> Self:
        if self.is_admin and self.account_type == "customer":
            raise ValueError("Customer accounts cannot be administrators.")
        return self


class CreateUserResponse(BaseModel):
    user: UserOut
    temporary_password: str


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    is_admin: bool | None = None


class TemporaryPasswordResponse(BaseModel):
    temporary_password: str
```

`backend/app/services/users.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.emails import normalize_email
from app.core.passwords import generate_temporary_password, hash_password
from app.db.models import User
from app.services import audit
from app.services.auth import revoke_user_sessions


class DuplicateEmail(Exception):
    pass


class SelfLockout(Exception):
    pass


class InvalidUserChange(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    display_name: str,
    account_type: str,
    is_admin: bool,
    actor_id: uuid.UUID | None,
) -> tuple[User, str]:
    normalized = normalize_email(email)
    if await db.scalar(select(User.id).where(User.email == normalized)) is not None:
        raise DuplicateEmail(normalized)
    temporary = generate_temporary_password()
    user = User(
        email=normalized,
        password_hash=hash_password(temporary),
        display_name=display_name.strip(),
        account_type=account_type,
        is_admin=is_admin,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    await audit.record(db, "user.create", user_id=actor_id, target_type="user", target_id=str(user.id))
    await db.commit()
    return user, temporary


async def update_user(
    db: AsyncSession,
    user: User,
    *,
    actor: User,
    display_name: str | None = None,
    is_active: bool | None = None,
    is_admin: bool | None = None,
) -> User:
    if user.id == actor.id and (is_active is False or is_admin is False):
        raise SelfLockout()
    if is_admin is True and user.account_type == "customer":
        raise InvalidUserChange("Customer accounts cannot be administrators.")
    changes: dict[str, object] = {}
    if display_name is not None:
        user.display_name = display_name.strip()
        changes["display_name"] = True
    if is_admin is not None:
        user.is_admin = is_admin
        changes["is_admin"] = is_admin
    if is_active is not None:
        user.is_active = is_active
        changes["is_active"] = is_active
        if not is_active:
            await revoke_user_sessions(db, user.id)
    await audit.record(
        db, "user.update", user_id=actor.id, target_type="user", target_id=str(user.id), details=changes
    )
    await db.commit()
    return user


async def reset_password(db: AsyncSession, user: User, *, actor_id: uuid.UUID) -> str:
    temporary = generate_temporary_password()
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    await revoke_user_sessions(db, user.id)
    await audit.record(db, "user.reset_password", user_id=actor_id, target_type="user", target_id=str(user.id))
    await db.commit()
    return temporary


async def reset_mfa(db: AsyncSession, user: User, *, actor_id: uuid.UUID) -> None:
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_pending_secret_enc = None
    user.mfa_last_counter = None
    user.recovery_codes_hash = []
    await revoke_user_sessions(db, user.id)
    await audit.record(db, "user.reset_mfa", user_id=actor_id, target_type="user", target_id=str(user.id))
    await db.commit()
```

`backend/app/api/routes/users.py`:

```python
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession
from app.db.models import User
from app.schemas.users import (
    CreateUserRequest,
    CreateUserResponse,
    TemporaryPasswordResponse,
    UpdateUserRequest,
    UserOut,
)
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])


async def _get_user(db: DbSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.get("", response_model=list[UserOut])
async def list_users(_: AdminUser, db: DbSession) -> list[UserOut]:
    users = (await db.scalars(select(User).order_by(User.email))).all()
    return [UserOut.model_validate(u) for u in users]


@router.post("", response_model=CreateUserResponse, status_code=201)
async def create_user(body: CreateUserRequest, admin: AdminUser, db: DbSession) -> CreateUserResponse:
    try:
        user, temporary = await users_service.create_user(
            db,
            email=body.email,
            display_name=body.display_name,
            account_type=body.account_type,
            is_admin=body.is_admin,
            actor_id=admin.id,
        )
    except users_service.DuplicateEmail as exc:
        raise HTTPException(status_code=409, detail="A user with this e-mail already exists.") from exc
    return CreateUserResponse(user=UserOut.model_validate(user), temporary_password=temporary)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UpdateUserRequest, admin: AdminUser, db: DbSession
) -> UserOut:
    user = await _get_user(db, user_id)
    try:
        updated = await users_service.update_user(
            db,
            user,
            actor=admin,
            display_name=body.display_name,
            is_active=body.is_active,
            is_admin=body.is_admin,
        )
    except users_service.SelfLockout as exc:
        raise HTTPException(
            status_code=409, detail="You cannot deactivate or remove admin rights from yourself."
        ) from exc
    except users_service.InvalidUserChange as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return UserOut.model_validate(updated)


@router.post("/{user_id}/reset-password", response_model=TemporaryPasswordResponse)
async def reset_password(user_id: uuid.UUID, admin: AdminUser, db: DbSession) -> TemporaryPasswordResponse:
    user = await _get_user(db, user_id)
    temporary = await users_service.reset_password(db, user, actor_id=admin.id)
    return TemporaryPasswordResponse(temporary_password=temporary)


@router.post("/{user_id}/reset-mfa", status_code=204)
async def reset_mfa(user_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    user = await _get_user(db, user_id)
    await users_service.reset_mfa(db, user, actor_id=admin.id)
```

`backend/app/cli.py`:

```python
import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.emails import is_valid_email, normalize_email
from app.db.session import dispose_engine, init_engine
from app.services.users import DuplicateEmail, create_user


async def create_admin(db: AsyncSession, email: str, display_name: str) -> str:
    _, temporary = await create_user(
        db,
        email=email,
        display_name=display_name,
        account_type="internal",
        is_admin=True,
        actor_id=None,
    )
    return temporary


async def _create_admin_command(email: str, display_name: str) -> int:
    if not is_valid_email(normalize_email(email)):
        print("Enter a valid e-mail address.", file=sys.stderr)
        return 1
    maker = init_engine(get_settings().database_url)
    try:
        async with maker() as db:
            try:
                temporary = await create_admin(db, email, display_name)
            except DuplicateEmail:
                print("A user with this e-mail already exists.", file=sys.stderr)
                return 1
    finally:
        await dispose_engine()
    print(f"Administrator created. Temporary password (shown once): {temporary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qc-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="Create an internal administrator account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return asyncio.run(_create_admin_command(args.email, args.name))
    return 2


def run() -> None:
    sys.exit(main())
```

Register in `backend/app/main.py`: `from app.api.routes import auth, health, users` and `app.include_router(users.router, prefix=API_PREFIX)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 5: Smoke-test the CLI against the dev database**

Run: `uv run qc-agent create-admin --email admin@techvify.com.vn --name "QC Admin"`
Expected: `Administrator created. Temporary password (shown once): ...`. Running it again prints `A user with this e-mail already exists.` and exits 1.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run mypy app
git add backend
git commit -m "feat(backend): add admin user management endpoints and create-admin CLI"
```

---

### Task 8: Projects, members and project-role authorisation

**Files:**
- Create: `backend/app/schemas/projects.py`, `backend/app/services/projects.py`, `backend/app/api/routes/projects.py`
- Modify: `backend/app/api/deps.py` (append), `backend/app/main.py` (register router)
- Test: `backend/tests/api/test_projects.py`

**Interfaces:**
- Consumes: `CurrentUser`, `DbSession` (Task 6); `slugify`, `unique_slug` (Task 3); models (Task 2); `audit.record` (Task 4).
- Produces:
  - `app.api.deps.ProjectContext(project: Project, user: User, role: str)`; `require_project_role(*allowed: str)` dependency factory (404 for missing/archived/non-member, 403 for insufficient role); constants `ALL_ROLES = ("owner", "editor", "viewer", "client")`, `INTERNAL_ROLES = ("owner", "editor", "viewer")`; aliases `AnyMember`, `InternalMember`, `ProjectOwner`
  - `app.schemas.projects`: `ProjectSettings(model="claude-opus-5", check_budget_usd=1.0, normalize_budget_usd=2.0)`, `ProjectSettingsPatch`, `ProjectCreate`, `ProjectUpdate`, `ProjectOut`, `MemberIn`, `MemberOut`
  - `app.services.projects`: `create_project(db, *, name, client_name, creator) -> Project`; `MemberValidationError(message)`; `replace_members(db, project, members: list[MemberIn], *, actor_id) -> None`; `list_members(db, project_id) -> list[MemberOut]`; `list_projects_for(db, user) -> list[tuple[Project, str]]`
  - Routes: `GET/POST /projects`, `GET/PATCH/DELETE /projects/{project_id}`, `GET/PUT /projects/{project_id}/members`

- [ ] **Step 1: Write the failing tests**

`backend/tests/api/test_projects.py`:

```python
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, Project, ProjectMember, User
from tests.factories import make_session_token, make_user

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def _client_for(make_client: MakeClient, db: AsyncSession, settings: Settings, user: User) -> AsyncClient:
    return await make_client(await make_session_token(db, settings, user))


async def _project_with_roles(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> dict[str, object]:
    owner = await make_user(db, settings, email="owner@example.com", display_name="Owner")
    editor = await make_user(db, settings, email="editor@example.com", display_name="Editor")
    viewer = await make_user(db, settings, email="viewer@example.com", display_name="Viewer")
    client_user = await make_user(
        db, settings, email="c@client.com", display_name="Client", account_type="customer"
    )
    outsider = await make_user(db, settings, email="out@example.com", display_name="Out")
    owner_c = await _client_for(make_client, db, settings, owner)
    created = await owner_c.post("/api/v1/projects", json={"name": "Dự án Cổng Khách hàng"})
    assert created.status_code == 201
    pid = created.json()["id"]
    members = [
        {"user_id": str(owner.id), "role": "owner"},
        {"user_id": str(editor.id), "role": "editor"},
        {"user_id": str(viewer.id), "role": "viewer"},
        {"user_id": str(client_user.id), "role": "client"},
    ]
    assert (await owner_c.put(f"/api/v1/projects/{pid}/members", json=members)).status_code == 200
    return {
        "pid": pid,
        "owner": owner_c,
        "editor": await _client_for(make_client, db, settings, editor),
        "viewer": await _client_for(make_client, db, settings, viewer),
        "client": await _client_for(make_client, db, settings, client_user),
        "outsider": await _client_for(make_client, db, settings, outsider),
        "users": {"owner": owner, "editor": editor, "viewer": viewer, "client": client_user},
    }


async def test_create_project_with_vietnamese_name(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    user = await make_user(db, settings)
    c = await _client_for(make_client, db, settings, user)
    first = await c.post("/api/v1/projects", json={"name": "Dự án Cổng Khách hàng", "client_name": "ACME"})
    second = await c.post("/api/v1/projects", json={"name": "Dự án Cổng Khách hàng"})
    assert first.status_code == second.status_code == 201
    assert first.json()["slug"] == "du-an-cong-khach-hang"
    assert second.json()["slug"] == "du-an-cong-khach-hang-2"
    assert first.json()["my_role"] == "owner"
    assert first.json()["settings"] == {
        "model": "claude-opus-5",
        "check_budget_usd": 1.0,
        "normalize_budget_usd": 2.0,
    }
    member = (await db.scalars(select(ProjectMember))).first()
    assert member is not None and member.role == "owner"
    assert "project.create" in (await db.scalars(select(AuditLog.action))).all()


async def test_blank_name_is_rejected(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    c = await _client_for(make_client, db, settings, await make_user(db, settings))
    assert (await c.post("/api/v1/projects", json={"name": "   "})).status_code == 422


async def test_customer_cannot_create_project(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    customer = await make_user(db, settings, email="c@client.com", account_type="customer")
    c = await _client_for(make_client, db, settings, customer)
    assert (await c.post("/api/v1/projects", json={"name": "X"})).status_code == 403


async def test_role_matrix(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    pid = ctx["pid"]
    url = f"/api/v1/projects/{pid}"
    for role in ("owner", "editor", "viewer", "client"):
        response = await ctx[role].get(url)  # type: ignore[attr-defined]
        assert response.status_code == 200, role
        assert response.json()["my_role"] == role
    assert (await ctx["client"].get(url)).json()["settings"] is None  # type: ignore[attr-defined]
    assert (await ctx["outsider"].get(url)).status_code == 404  # type: ignore[attr-defined]
    for role in ("editor", "viewer", "client"):
        response = await ctx[role].patch(url, json={"name": "Renamed"})  # type: ignore[attr-defined]
        assert response.status_code == 403, role
    assert (await ctx["client"].get(f"{url}/members")).status_code == 403  # type: ignore[attr-defined]
    assert (await ctx["viewer"].get(f"{url}/members")).status_code == 200  # type: ignore[attr-defined]


async def test_owner_updates_settings_with_merge_and_validation(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    owner: AsyncClient = ctx["owner"]  # type: ignore[assignment]
    url = f"/api/v1/projects/{ctx['pid']}"
    ok = await owner.patch(url, json={"settings": {"check_budget_usd": 0.5}, "client_name": None})
    assert ok.status_code == 200
    assert ok.json()["settings"]["check_budget_usd"] == 0.5
    assert ok.json()["settings"]["normalize_budget_usd"] == 2.0
    assert ok.json()["client_name"] is None
    assert (await owner.patch(url, json={"settings": {"check_budget_usd": 0}})).status_code == 422
    assert (await owner.patch(url, json={"settings": {"unknown": 1}})).status_code == 422


async def test_list_projects_scoped_by_membership_and_admin_sees_all(
    make_client: MakeClient, db: AsyncSession, settings: Settings
) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    outsider: AsyncClient = ctx["outsider"]  # type: ignore[assignment]
    assert (await outsider.get("/api/v1/projects")).json() == []
    client_list = (await ctx["client"].get("/api/v1/projects")).json()  # type: ignore[attr-defined]
    assert [p["id"] for p in client_list] == [ctx["pid"]]
    admin = await make_user(db, settings, email="root@example.com", is_admin=True)
    admin_c = await _client_for(make_client, db, settings, admin)
    admin_list = (await admin_c.get("/api/v1/projects")).json()
    assert [p["my_role"] for p in admin_list] == ["owner"]


async def test_archive_hides_project(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    owner: AsyncClient = ctx["owner"]  # type: ignore[assignment]
    url = f"/api/v1/projects/{ctx['pid']}"
    assert (await ctx["editor"].delete(url)).status_code == 403  # type: ignore[attr-defined]
    assert (await owner.delete(url)).status_code == 204
    assert (await owner.get(url)).status_code == 404
    assert (await owner.get("/api/v1/projects")).json() == []
    project = (await db.scalars(select(Project))).one()
    await db.refresh(project)
    assert project.archived_at is not None


async def test_member_rules(make_client: MakeClient, db: AsyncSession, settings: Settings) -> None:
    ctx = await _project_with_roles(make_client, db, settings)
    owner: AsyncClient = ctx["owner"]  # type: ignore[assignment]
    users = ctx["users"]  # type: ignore[assignment]
    url = f"/api/v1/projects/{ctx['pid']}/members"
    o, e, c = (str(users[k].id) for k in ("owner", "editor", "client"))  # type: ignore[index]
    cases = {
        "no owner": [{"user_id": e, "role": "editor"}],
        "customer as editor": [{"user_id": o, "role": "owner"}, {"user_id": c, "role": "editor"}],
        "internal as client": [{"user_id": o, "role": "owner"}, {"user_id": e, "role": "client"}],
        "duplicate": [{"user_id": o, "role": "owner"}, {"user_id": o, "role": "viewer"}],
        "unknown user": [
            {"user_id": o, "role": "owner"},
            {"user_id": "00000000-0000-0000-0000-000000000000", "role": "viewer"},
        ],
    }
    for name, payload in cases.items():
        response = await owner.put(url, json=payload)
        assert response.status_code == 422, name
    inactive = await make_user(db, settings, email="gone@example.com", is_active=False)
    response = await owner.put(
        url, json=[{"user_id": o, "role": "owner"}, {"user_id": str(inactive.id), "role": "viewer"}]
    )
    assert response.status_code == 422
    final = await owner.put(url, json=[{"user_id": o, "role": "owner"}, {"user_id": e, "role": "viewer"}])
    assert final.status_code == 200
    assert {m["role"] for m in final.json()} == {"owner", "viewer"}
    assert (await ctx["client"].get(f"/api/v1/projects/{ctx['pid']}")).status_code == 404  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_projects.py -v`
Expected: FAIL — 404 for `POST /api/v1/projects`.

- [ ] **Step 3: Implement schemas**

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


class ProjectOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    client_name: str | None
    created_at: datetime
    my_role: str
    settings: ProjectSettings | None


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

- [ ] **Step 4: Implement the service**

`backend/app/services/projects.py`:

```python
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slugs import slugify, unique_slug
from app.db.models import Project, ProjectMember, User
from app.schemas.projects import MemberIn, MemberOut, ProjectSettings
from app.services import audit


class MemberValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def create_project(
    db: AsyncSession, *, name: str, client_name: str | None, creator: User
) -> Project:
    base = slugify(name)
    taken = set((await db.scalars(select(Project.slug).where(Project.slug.startswith(base)))).all())
    project = Project(
        slug=unique_slug(base, taken),
        name=name,
        client_name=client_name,
        settings=ProjectSettings().model_dump(),
        created_by=creator.id,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=creator.id, role="owner"))
    await audit.record(
        db, "project.create", user_id=creator.id, project_id=project.id,
        target_type="project", target_id=str(project.id),
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
        db, "project.members_replaced", user_id=actor_id, project_id=project.id,
        target_type="project", target_id=str(project.id),
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
            user_id=u.id, email=u.email, display_name=u.display_name,
            account_type=u.account_type, role=role,
        )
        for u, role in rows
    ]
```

- [ ] **Step 5: Implement the role dependency**

Append to `backend/app/api/deps.py` (merge imports):

```python
import uuid
from collections.abc import Awaitable, Callable

from app.db.models import Project, ProjectMember

ALL_ROLES = ("owner", "editor", "viewer", "client")
INTERNAL_ROLES = ("owner", "editor", "viewer")


@dataclass
class ProjectContext:
    project: Project
    user: User
    role: str


def require_project_role(*allowed: str) -> Callable[..., Awaitable[ProjectContext]]:
    async def dependency(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProjectContext:
        project = await db.get(Project, project_id)
        if project is None or project.archived_at is not None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if user.is_admin:
            role: str | None = "owner"
        else:
            role = await db.scalar(
                select(ProjectMember.role).where(
                    ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
                )
            )
        if role is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if role not in allowed:
            raise HTTPException(status_code=403, detail="You do not have access to this action.")
        return ProjectContext(project=project, user=user, role=role)

    return dependency


AnyMember = Annotated[ProjectContext, Depends(require_project_role(*ALL_ROLES))]
InternalMember = Annotated[ProjectContext, Depends(require_project_role(*INTERNAL_ROLES))]
ProjectOwner = Annotated[ProjectContext, Depends(require_project_role("owner"))]
```

(`dataclass` is already imported if you kept it; otherwise add `from dataclasses import dataclass`.)

- [ ] **Step 6: Implement the routes**

`backend/app/api/routes/projects.py`:

```python
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.api.deps import (
    INTERNAL_ROLES,
    AnyMember,
    CurrentUser,
    DbSession,
    InternalMember,
    ProjectOwner,
)
from app.db.models import Project
from app.schemas.projects import (
    MemberIn,
    MemberOut,
    ProjectCreate,
    ProjectOut,
    ProjectSettings,
    ProjectUpdate,
)
from app.services import audit
from app.services import projects as projects_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _out(project: Project, role: str) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        client_name=project.client_name,
        created_at=project.created_at,
        my_role=role,
        settings=ProjectSettings(**project.settings) if role in INTERNAL_ROLES else None,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DbSession) -> list[ProjectOut]:
    return [_out(p, role) for p, role in await projects_service.list_projects_for(db, user)]


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, user: CurrentUser, db: DbSession) -> ProjectOut:
    if user.account_type != "internal":
        raise HTTPException(status_code=403, detail="Only internal users can create projects.")
    project = await projects_service.create_project(
        db, name=body.name, client_name=body.client_name, creator=user
    )
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
        db, "project.update", user_id=ctx.user.id, project_id=project.id,
        target_type="project", target_id=str(project.id),
        details={"fields": sorted(body.model_fields_set)},
    )
    await db.commit()
    return _out(project, ctx.role)


@router.delete("/{project_id}", status_code=204)
async def archive_project(ctx: ProjectOwner, db: DbSession) -> None:
    ctx.project.archived_at = datetime.now(UTC)
    await audit.record(
        db, "project.archive", user_id=ctx.user.id, project_id=ctx.project.id,
        target_type="project", target_id=str(ctx.project.id),
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
```

Register in `backend/app/main.py`: `from app.api.routes import auth, health, projects, users` and `app.include_router(projects.router, prefix=API_PREFIX)`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
uv run ruff check . && uv run mypy app
git add backend
git commit -m "feat(backend): add projects, members and project-role authorisation"
```

---

### Task 9: Quality gates, secret scanning and backend README

**Files:**
- Create: `.pre-commit-config.yaml`, `backend/README.md`, `.gitleaks.toml` (only if Step 1 needs it)
- Modify: `docs/PENDING.md` (tick the Plan 1 line in section 4)

**Interfaces:**
- Consumes: everything above.
- Produces: a repository where `pre-commit run --all-files` and the full test suite pass.

- [ ] **Step 1: Pre-commit with ruff, mypy and gitleaks**

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
  - repo: local
    hooks:
      - id: ruff
        name: ruff
        entry: bash -c 'cd backend && uv run ruff check . && uv run ruff format --check .'
        language: system
        pass_filenames: false
        files: ^backend/
      - id: mypy
        name: mypy
        entry: bash -c 'cd backend && uv run mypy app'
        language: system
        pass_filenames: false
        files: ^backend/
```

Run:

```bash
uv tool install pre-commit
pre-commit autoupdate --repo https://github.com/gitleaks/gitleaks
pre-commit install
pre-commit run --all-files
```

Expected: all hooks pass. If gitleaks flags the dev-only `POSTGRES_PASSWORD: qc` in `deploy/dev/docker-compose.yml` or the test secrets in `tests/conftest.py`, add a `.gitleaks.toml` allowlist for exactly those two paths:

```toml
[extend]
useDefault = true

[allowlist]
description = "Local development and test-only values"
paths = ['''deploy/dev/docker-compose\.yml''', '''backend/tests/conftest\.py''']
```

- [ ] **Step 2: Backend README**

`backend/README.md`:

````markdown
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
````

- [ ] **Step 3: Full verification**

Run:

```bash
cd backend
uv run alembic upgrade head && uv run alembic check
uv run pytest -v
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

Expected: `No new upgrade operations detected.`; all tests pass; no lint or type errors.

- [ ] **Step 4: Commit**

```bash
cd ..
git add .pre-commit-config.yaml backend/README.md docs/PENDING.md
[ -f .gitleaks.toml ] && git add .gitleaks.toml
git commit -m "chore: add pre-commit quality gates, secret scanning and backend README"
```
