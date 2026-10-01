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
