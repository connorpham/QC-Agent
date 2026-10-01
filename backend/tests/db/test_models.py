import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Document,
    DocumentVersion,
    Project,
    ProjectMember,
    Upload,
    UploadItem,
    User,
)


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


async def test_project_storage_and_consent_columns(db: AsyncSession) -> None:
    user = _user()
    db.add(user)
    await db.flush()
    project = Project(
        slug="demo", name="Demo", created_by=user.id, storage={"type": "localfs", "root": "demo"}
    )
    db.add(project)
    await db.commit()
    assert project.storage == {"type": "localfs", "root": "demo"}
    assert project.llm_consent is None


async def _project(db: AsyncSession) -> tuple[User, Project]:
    user = _user()
    db.add(user)
    await db.flush()
    project = Project(slug="demo", name="Demo", created_by=user.id, storage={})
    db.add(project)
    await db.flush()
    return user, project


async def test_document_defaults_and_stub_slug_rule(db: AsyncSession) -> None:
    user, project = await _project(db)
    document = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        created_by=user.id,
    )
    db.add(document)
    await db.commit()
    assert document.visibility == "internal" and document.current_version == 0
    assert document.is_stub is False and document.updated_at is not None
    db.add(
        Document(
            project_id=project.id,
            folder_id="requirements",
            doc_type="brd",
            title="BRD",
            slug="brd",
            is_stub=True,
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_document_slug_is_unique_per_project_and_type(db: AsyncSession) -> None:
    user, project = await _project(db)
    for doc_type in ("srs", "brd"):
        db.add(
            Document(
                project_id=project.id,
                folder_id="requirements",
                doc_type=doc_type,
                title="Portal",
                slug="portal",
                created_by=user.id,
            )
        )
    await db.commit()  # same slug, different types: allowed
    db.add(
        Document(
            project_id=project.id,
            folder_id="requirements",
            doc_type="srs",
            title="Portal",
            slug="portal",
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_upload_item_status_is_constrained(db: AsyncSession) -> None:
    user, project = await _project(db)
    upload = Upload(project_id=project.id, uploaded_by=user.id)
    db.add(upload)
    await db.flush()
    db.add(
        UploadItem(
            upload_id=upload.id,
            original_name="a.docx",
            ext="docx",
            size=1,
            sha256="0" * 64,
            staging_path="x/a.docx",
            selected_doc_type="srs",
            title="A",
            status="teleporting",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_document_version_unique_per_document(db: AsyncSession) -> None:
    user, project = await _project(db)
    document = Document(
        project_id=project.id,
        folder_id="requirements",
        doc_type="srs",
        title="SRS",
        slug="srs",
        created_by=user.id,
    )
    db.add(document)
    await db.flush()
    for _ in range(2):
        db.add(
            DocumentVersion(
                document_id=document.id,
                version=1,
                sha256="0" * 64,
                markdown_path="02-requirements/srs--srs.md",
                markdown_storage_version="1",
                markdown_text="# SRS",
                uploaded_by=user.id,
            )
        )
    with pytest.raises(IntegrityError):
        await db.commit()
