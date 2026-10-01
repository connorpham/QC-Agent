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
