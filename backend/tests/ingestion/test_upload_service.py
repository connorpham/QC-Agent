"""Intake service: staging, zip expansion, item specs and the rules applied when items are
created (forced visibility for clients, version targets, early no-change rejection)."""

import hashlib
import uuid
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fake import FakeAnalyzer, ScriptedVerdict
from app.core.config import Settings
from app.db.models import Document, DocumentVersion, ProjectMember, Upload, UploadItem
from app.ingestion.intake import IntakeLimits
from app.ingestion.taxonomy import Taxonomy
from app.schemas.uploads import UploadItemSpec
from app.services.uploads import (
    IncomingFile,
    ItemStateError,
    UploadError,
    confirm_type,
    create_upload,
    my_tasks,
    stage_files,
    staging_dir_for,
)
from tests.factories import add_member, make_project, make_user
from tests.helpers.files import bytes_reader, docx_bytes, make_zip
from tests.helpers.ingest import ingest

LIMITS = IntakeLimits.from_megabytes(1, 2)
SRS = docx_bytes(["The system shall allow users to log in."])


async def test_stage_files_expands_zip_and_keeps_entry_titles_open(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "export.zip", {"a/Glossary.md": b"# G", "a/Cases.csv": b"id\n1"})
    staged, rejections = await stage_files(
        [
            IncomingFile("SRS final.docx", bytes_reader(SRS)),
            IncomingFile("export.zip", bytes_reader(archive.read_bytes())),
            IncomingFile("notes.exe", bytes_reader(b"x")),
            IncomingFile("v2.zip", bytes_reader(archive.read_bytes())),
        ],
        [
            UploadItemSpec(doc_type="srs", title="Custom title"),
            UploadItemSpec(doc_type="glossary", title="Should not apply to entries"),
            UploadItemSpec(doc_type="srs"),
            UploadItemSpec(doc_type="srs", intent="version", target_document_id=uuid.uuid4()),
        ],
        staging_dir=tmp_path / "staging" / "u1",
        limits=LIMITS,
    )
    assert [(s.file.name, s.spec.title) for s in staged] == [
        ("SRS final.docx", "Custom title"),
        ("Glossary.md", None),
        ("Cases.csv", None),
    ]
    assert all(
        s.file.path.is_file() and s.file.path.is_relative_to(tmp_path / "staging") for s in staged
    )
    assert [r.name for r in rejections] == ["notes.exe", "v2.zip"]
    assert rejections[1].reason == "Zip archives cannot be uploaded as a new version."
    # the rejected v2.zip's staged copy must be removed, not left behind in "incoming"
    incoming_dir = tmp_path / "staging" / "u1" / "incoming"
    assert len(list(incoming_dir.iterdir())) == 2  # SRS final.docx and export.zip only


async def test_create_upload_rules(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, staging_root: Path
) -> None:
    owner = await make_user(db, settings)
    client_user = await make_user(db, settings, email="c@client.com", account_type="customer")
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    other_project = await make_project(db, settings, taxonomy, owner=owner, name="Other")
    internal_doc = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        current_version=1,
        created_by=owner.id,
    )
    foreign_doc = Document(
        project_id=other_project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        current_version=1,
        created_by=owner.id,
    )
    db.add_all([internal_doc, foreign_doc])
    await db.flush()
    db.add(
        DocumentVersion(
            document_id=internal_doc.id,
            version=1,
            sha256=hashlib.sha256(SRS).hexdigest(),
            original_path="02-requirements/srs--srs.docx",
            original_storage_version="1",
            markdown_path="02-requirements/srs--srs.md",
            markdown_storage_version="1",
            markdown_text="# SRS",
            uploaded_by=owner.id,
        )
    )
    await db.commit()
    upload_id = uuid.uuid4()
    files = [
        IncomingFile("brd.docx", bytes_reader(SRS)),
        IncomingFile("poem.docx", bytes_reader(SRS)),
        IncomingFile("no-target.docx", bytes_reader(SRS)),
        IncomingFile("foreign.docx", bytes_reader(SRS)),
        IncomingFile("same-bytes.docx", bytes_reader(SRS)),
        IncomingFile("hidden-target.docx", bytes_reader(SRS)),
    ]
    specs = [
        UploadItemSpec(doc_type="brd", visibility="internal"),
        UploadItemSpec(doc_type="poem"),
        UploadItemSpec(doc_type="srs", intent="version"),
        UploadItemSpec(doc_type="srs", intent="version", target_document_id=foreign_doc.id),
        UploadItemSpec(doc_type="srs", intent="version", target_document_id=internal_doc.id),
        UploadItemSpec(doc_type="srs", intent="version", target_document_id=internal_doc.id),
    ]
    staged, rejections = await stage_files(
        files[:5] + files[5:],
        specs,
        staging_dir=staging_dir_for(staging_root, upload_id),
        limits=LIMITS,
    )
    assert rejections == []
    # the client uploads: visibility forced to shared, internal target hidden (404-style)
    upload, rejected = await create_upload(
        db,
        project=project,
        uploader=client_user,
        role="client",
        upload_id=upload_id,
        staged=staged,
        rejections=rejections,
        taxonomy=taxonomy,
        staging_root=staging_root,
    )
    reasons = {r.name: r.reason for r in rejected}
    assert reasons["poem.docx"] == "Unknown document type 'poem'."
    assert reasons["no-target.docx"] == "A target document is required for a new version."
    assert reasons["foreign.docx"] == "Target document not found."
    assert reasons["same-bytes.docx"] == "Target document not found."  # internal doc, client
    assert reasons["hidden-target.docx"] == "Target document not found."
    items = (await db.scalars(select(UploadItem).where(UploadItem.upload_id == upload.id))).all()
    assert [i.original_name for i in items] == ["brd.docx"]
    assert items[0].visibility == "shared" and items[0].title == "brd"
    assert items[0].staging_path.startswith(f"{upload_id}/incoming/")
    assert (staging_root / items[0].staging_path).is_file()


async def test_create_upload_no_change_for_internal_user_and_all_rejected(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, staging_root: Path
) -> None:
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    document = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        current_version=1,
        created_by=owner.id,
    )
    db.add(document)
    await db.flush()
    db.add(
        DocumentVersion(
            document_id=document.id,
            version=1,
            sha256=hashlib.sha256(SRS).hexdigest(),
            original_path="02-requirements/srs--srs.docx",
            original_storage_version="1",
            markdown_path="02-requirements/srs--srs.md",
            markdown_storage_version="1",
            markdown_text="# SRS",
            uploaded_by=owner.id,
        )
    )
    await db.commit()
    upload_id = uuid.uuid4()
    staged, rejections = await stage_files(
        [IncomingFile("same.docx", bytes_reader(SRS)), IncomingFile("brd.docx", bytes_reader(SRS))],
        [
            UploadItemSpec(doc_type="srs", intent="version", target_document_id=document.id),
            UploadItemSpec(doc_type="brd", intent="version", target_document_id=document.id),
        ],
        staging_dir=staging_dir_for(staging_root, upload_id),
        limits=LIMITS,
    )
    with pytest.raises(UploadError) as excinfo:
        await create_upload(
            db,
            project=project,
            uploader=owner,
            role="owner",
            upload_id=upload_id,
            staged=staged,
            rejections=rejections,
            taxonomy=taxonomy,
            staging_root=staging_root,
        )
    assert excinfo.value.message == "No files were accepted."
    assert [r.reason for r in excinfo.value.rejections] == [
        "No change: this file is identical to the current version.",
        "A new version must keep the document type of SRS.",
    ]
    assert (await db.scalars(select(Upload))).all() == []
    # the staging directory for this upload must be cleaned up since nothing was accepted
    assert not staging_dir_for(staging_root, upload_id).is_dir()


async def test_confirm_type_version_must_keep_target_document_type(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy, staging_root: Path
) -> None:
    """Ruling P1: confirming a version item with a doc_type other than the target document's
    refuses with ItemStateError and leaves the item unchanged; the target's own type works."""
    owner = await make_user(db, settings)
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    target = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        current_version=1,
        created_by=owner.id,
    )
    db.add(target)
    await db.flush()
    upload = Upload(project_id=project.id, uploaded_by=owner.id)
    db.add(upload)
    await db.flush()
    item = UploadItem(
        upload_id=upload.id,
        original_name="srs-v2.docx",
        ext="docx",
        size=len(SRS),
        sha256=hashlib.sha256(SRS).hexdigest(),
        staging_path=f"{upload.id}/incoming/{uuid.uuid4().hex}.docx",
        selected_doc_type="srs",
        title="SRS v2",
        intent="version",
        target_document_id=target.id,
        visibility="internal",
        status="needs_confirmation",
    )
    db.add(item)
    await db.commit()

    with pytest.raises(ItemStateError) as excinfo:
        await confirm_type(
            db,
            item,
            doc_type_key="brd",
            taxonomy=taxonomy,
            actor=owner,
            project_id=project.id,
        )
    assert excinfo.value.message == "A new version must keep the document type of SRS."
    assert item.status == "needs_confirmation"
    assert item.final_doc_type is None

    await confirm_type(
        db,
        item,
        doc_type_key="srs",
        taxonomy=taxonomy,
        actor=owner,
        project_id=project.id,
    )
    assert item.status == "publishing"
    assert item.final_doc_type == "srs"


async def test_batch_cap_counts_extracted_bytes_across_zips(tmp_path: Path) -> None:
    # Deflated archives are tiny on the wire; the cap must apply to what they extract to.
    entry = b"x" * 700 * 1024
    first = make_zip(
        tmp_path / "first.zip", {"a.md": entry, "b.md": entry}, compression=zipfile.ZIP_DEFLATED
    )
    second = make_zip(tmp_path / "second.zip", {"c.md": entry}, compression=zipfile.ZIP_DEFLATED)
    staged, rejections = await stage_files(
        [
            IncomingFile("first.zip", bytes_reader(first.read_bytes())),
            IncomingFile("second.zip", bytes_reader(second.read_bytes())),
        ],
        [UploadItemSpec(doc_type="glossary"), UploadItemSpec(doc_type="glossary")],
        staging_dir=tmp_path / "staging" / "u1",
        limits=LIMITS,
    )
    assert [s.file.name for s in staged] == ["a.md", "b.md"]
    assert [(r.name, r.reason) for r in rejections] == [
        ("c.md", "Upload batch exceeds the 2 MB limit.")
    ]
    items_dir = tmp_path / "staging" / "u1" / "items"
    assert sorted(items_dir.iterdir()) == sorted(s.file.path for s in staged)


async def test_my_tasks_only_lists_projects_the_user_still_belongs_to(
    db: AsyncSession, settings: Settings, taxonomy: Taxonomy
) -> None:
    owner = await make_user(db, settings)
    editor = await make_user(db, settings, email="editor@example.com")
    project = await make_project(db, settings, taxonomy, owner=owner, name="Demo")
    await add_member(db, project, editor, "editor")
    fake = FakeAnalyzer({"srs.docx": ScriptedVerdict("mismatch", "Looks like a plan.", None)})
    for uploader, role in ((editor, "editor"), (owner, "owner")):
        await db.refresh(uploader)
        await ingest(
            db,
            settings,
            taxonomy,
            project=project,
            uploader=uploader,
            role=role,
            files=[("srs.docx", SRS)],
            specs=[UploadItemSpec(doc_type="srs")],
            analyzer=fake,
        )
    await db.refresh(editor)  # each commit expires loaded users
    assert len(await my_tasks(db, editor)) == 1
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == editor.id))
    await db.commit()
    await db.refresh(editor)
    assert await my_tasks(db, editor) == []
    # the owner, made an administrator without a membership, still sees their own task
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == owner.id))
    owner.is_admin = True
    await db.commit()
    await db.refresh(owner)
    assert [item.original_name for item, _ in await my_tasks(db, owner)] == ["srs.docx"]
