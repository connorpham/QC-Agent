"""Project creation provisions the workspace; the owner records the LLM data-processing
confirmation; uploads stay blocked until then (checked in test_uploads)."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import AuditLog, Document, DocumentVersion, Project, User
from app.ingestion.naming import split_frontmatter
from app.ingestion.taxonomy import Taxonomy
from app.services.projects import create_project
from app.services.workspace import ensure_workspace
from app.storage.base import StorageError
from app.storage.localfs import LocalFsBackend
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


async def test_concurrent_project_creation_with_same_name_is_serialised(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    taxonomy: Taxonomy,
    storage_root: Path,
) -> None:
    """Two requests creating a project with the same name race on the same base slug. The
    advisory lock in ``create_project`` serialises them: the second sees the first's slug as
    taken and provisions its own root under ``<base>-2`` instead of writing into the same
    folder."""
    async with db_sessionmaker() as setup:
        owner = await make_user(setup, settings)
        owner_id = owner.id

    async with db_sessionmaker() as db_a, db_sessionmaker() as db_b:
        owner_a = await db_a.get(User, owner_id)
        owner_b = await db_b.get(User, owner_id)
        assert owner_a is not None
        assert owner_b is not None
        project_a, project_b = await asyncio.gather(
            create_project(
                db_a,
                name="Same Name",
                client_name=None,
                creator=owner_a,
                settings=settings,
                taxonomy=taxonomy,
            ),
            create_project(
                db_b,
                name="Same Name",
                client_name=None,
                creator=owner_b,
                settings=settings,
                taxonomy=taxonomy,
            ),
        )

    assert {project_a.slug, project_b.slug} == {"same-name", "same-name-2"}
    async with db_sessionmaker() as check:
        for project in (project_a, project_b):
            srs_text = (storage_root / project.slug / "02-requirements/srs.md").read_text()
            data, _ = split_frontmatter(srs_text)
            document = await check.scalar(
                select(Document).where(
                    Document.project_id == project.id, Document.doc_type == "srs"
                )
            )
            assert document is not None
            assert data["document_id"] == str(document.id)


async def test_create_project_rolls_back_when_workspace_provisioning_fails(
    make_client: MakeClient,
    db: AsyncSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await make_user(db, settings)
    c = await make_client(await make_session_token(db, settings, owner))

    async def _boom(self: LocalFsBackend, path: str) -> None:
        raise StorageError("Storage is unavailable.")

    monkeypatch.setattr(LocalFsBackend, "ensure_folder", _boom)

    response = await c.post("/api/v1/projects", json={"name": "Boom"})
    assert response.status_code == 503
    assert (await db.scalars(select(Project))).all() == []
