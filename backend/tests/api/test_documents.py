"""Document endpoints: listing and filters, role × visibility matrix, downloads, versions,
PATCH rules, gap report and version suggestions."""

import json
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AuditLog, Document, Project, User
from app.ingestion.taxonomy import Taxonomy
from tests.factories import add_member, make_project, make_session_token, make_user
from tests.helpers.files import docx_bytes

MakeClient = Callable[..., Awaitable[AsyncClient]]
SRS = docx_bytes(["The system shall allow users to log in with a password and a one-time code."])
SRS_V2 = docx_bytes(["The system shall allow users to log in with a password and MFA."])


async def _world(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> tuple[Project, dict[str, AsyncClient], dict[str, User], dict[str, str]]:
    owner = await make_user(db, settings, email="owner@example.com", display_name="Owner")
    editor = await make_user(db, settings, email="editor@example.com", display_name="Editor")
    viewer = await make_user(db, settings, email="viewer@example.com", display_name="Viewer")
    client_user = await make_user(
        db, settings, email="c@client.com", display_name="Client", account_type="customer"
    )
    outsider = await make_user(db, settings, email="out@example.com", display_name="Out")
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    for user, role in ((editor, "editor"), (viewer, "viewer"), (client_user, "client")):
        await add_member(db, project, user, role)
    clients = {}
    for name, user in (
        ("owner", owner),
        ("editor", editor),
        ("viewer", viewer),
        ("client", client_user),
        ("outsider", outsider),
    ):
        clients[name] = await make_client(await make_session_token(db, settings, user))
    url = f"/api/v1/projects/{project.id}/uploads"
    files = [
        ("files", ("srs.docx", SRS, "application/octet-stream")),
        ("files", ("runbook.md", b"# Runbook\n\nRestart.\n", "text/markdown")),
    ]
    specs = [
        {"doc_type": "srs", "title": "Portal SRS"},
        {"doc_type": "runbook", "title": "Ops Runbook", "visibility": "shared"},
    ]
    created = await clients["editor"].post(url, files=files, data={"items": json.dumps(specs)})
    assert created.status_code == 201, created.text
    documents = (await db.scalars(select(Document).where(Document.is_stub.is_(False)))).all()
    ids = {d.doc_type: str(d.id) for d in documents}
    users = {"owner": owner, "editor": editor, "viewer": viewer, "client": client_user}
    return project, clients, users, ids


async def test_listing_and_filters(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    url = f"/api/v1/projects/{project.id}/documents"
    everything = (await clients["viewer"].get(url)).json()
    assert len(everything) == 10  # 8 remaining stubs + 2 real documents
    assert [d["folder_id"] for d in everything][:3] == ["overview", "overview", "requirements"]
    real = [d for d in everything if not d["is_stub"]]
    assert {d["id"] for d in real} == set(ids.values())
    assert (
        await clients["viewer"].get(url, params={"folder": "deployment", "doc_type": "runbook"})
    ).json()[-1]["title"] == "Ops Runbook"
    assert [
        d["title"] for d in (await clients["viewer"].get(url, params={"q": "portal"})).json()
    ] == ["Portal SRS"]
    assert (await clients["viewer"].get(url, params={"q": "%"})).json() == []
    shared_only = (await clients["client"].get(url)).json()
    assert [d["title"] for d in shared_only] == ["Ops Runbook"]
    assert (await clients["client"].get(url, params={"visibility": "internal"})).json() == []
    assert (await clients["outsider"].get(url)).status_code == 404


async def test_role_visibility_matrix(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    expected = {
        ("owner", "srs"): 200,
        ("editor", "srs"): 200,
        ("viewer", "srs"): 200,
        ("client", "srs"): 404,
        ("owner", "runbook"): 200,
        ("editor", "runbook"): 200,
        ("viewer", "runbook"): 200,
        ("client", "runbook"): 200,
        ("outsider", "srs"): 404,
        ("outsider", "runbook"): 404,
    }
    for (role, doc_type), status in expected.items():
        for suffix in ("", "/versions", "/versions/1/original", "/versions/1/markdown"):
            response = await clients[role].get(f"/api/v1/documents/{ids[doc_type]}{suffix}")
            assert response.status_code == status, (role, doc_type, suffix, response.status_code)


async def test_downloads_have_attachment_headers_and_content(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    original = await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/1/original")
    assert original.status_code == 200
    assert original.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert original.headers["content-disposition"].startswith(
        'attachment; filename="srs--portal-srs.docx"'
    )
    assert original.headers["x-content-type-options"] == "nosniff"
    assert original.content == SRS
    markdown = await clients["client"].get(
        f"/api/v1/documents/{ids['runbook']}/versions/1/markdown"
    )
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text.startswith("---\nqc_agent: 2\n") and "Restart." in markdown.text
    assert (
        await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/9/original")
    ).status_code == 404
    stub = (await db.scalars(select(Document).where(Document.is_stub.is_(True)))).first()
    assert stub is not None
    stub_original = await clients["viewer"].get(f"/api/v1/documents/{stub.id}/versions/1/original")
    assert (
        stub_original.status_code == 404
        and stub_original.json()["detail"] == "Stub documents have no original file."
    )
    assert (
        await clients["viewer"].get(f"/api/v1/documents/{stub.id}/versions/1/markdown")
    ).status_code == 200


async def test_versions_list_after_new_version(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    files = [("files", ("srs-v2.docx", SRS_V2, "application/octet-stream"))]
    specs = [{"doc_type": "srs", "intent": "version", "target_document_id": ids["srs"]}]
    created = await clients["owner"].post(
        f"/api/v1/projects/{project.id}/uploads", files=files, data={"items": json.dumps(specs)}
    )
    assert created.status_code == 201
    versions = (await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions")).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["uploaded_by"] for v in versions] == ["Editor", "Owner"]
    assert (await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}")).json()[
        "current_version"
    ] == 2
    old = await clients["viewer"].get(f"/api/v1/documents/{ids['srs']}/versions/1/original")
    assert old.content == SRS


async def test_patch_rules(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    _, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    srs = f"/api/v1/documents/{ids['srs']}"
    runbook = f"/api/v1/documents/{ids['runbook']}"
    assert (await clients["viewer"].patch(srs, json={"title": "X"})).status_code == 403
    assert (
        await clients["client"].patch(runbook, json={"visibility": "internal"})
    ).status_code == 403
    assert (await clients["client"].patch(srs, json={"title": "X"})).status_code == 404
    shared = await clients["editor"].patch(
        srs, json={"visibility": "shared", "title": "Portal SRS v2"}
    )
    assert shared.status_code == 200 and shared.json()["visibility"] == "shared"
    assert shared.json()["title"] == "Portal SRS v2" and shared.json()["slug"] == "portal-srs"
    assert (await clients["client"].get(srs)).status_code == 200  # now visible to the client
    assert (await clients["editor"].patch(srs, json={"visibility": "internal"})).status_code == 403
    assert (await clients["owner"].patch(srs, json={"visibility": "internal"})).status_code == 200
    assert (await clients["client"].get(srs)).status_code == 404
    assert (await clients["owner"].patch(srs, json={"title": "   "})).status_code == 422
    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "document.visibility_changed" in actions


async def test_gap_report_and_version_suggestions(
    make_client: MakeClient, db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    project, clients, _, ids = await _world(make_client, db, settings, taxonomy)
    report = await clients["viewer"].get(f"/api/v1/projects/{project.id}/gap-report")
    assert report.status_code == 200
    assert report.json()["required_present"] == 2 and report.json()["required_total"] == 10
    statuses = {
        t["doc_type"]: t["status"] for f in report.json()["folders"] for t in f["doc_types"]
    }
    assert (
        statuses["srs"] == "present"
        and statuses["brd"] == "stub"
        and statuses["glossary"] == "missing"
    )
    assert (
        await clients["client"].get(f"/api/v1/projects/{project.id}/gap-report")
    ).status_code == 403
    suggest = f"/api/v1/projects/{project.id}/version-suggestions"
    found = await clients["editor"].get(
        suggest, params={"doc_type": "srs", "title": "Portal SRS v1"}
    )
    assert found.status_code == 200
    assert [s["document_id"] for s in found.json()] == [ids["srs"]]
    assert found.json()[0]["current_version"] == 1 and found.json()[0]["similarity"] >= 0.8
    assert (
        await clients["editor"].get(
            suggest, params={"doc_type": "srs", "title": "Payments gateway"}
        )
    ).json() == []
    # clients only get suggestions among shared documents
    assert (
        await clients["client"].get(suggest, params={"doc_type": "srs", "title": "Portal SRS"})
    ).json() == []
    assert (
        await clients["viewer"].get(suggest, params={"doc_type": "srs", "title": "Portal SRS"})
    ).status_code == 403


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
