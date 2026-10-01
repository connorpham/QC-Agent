import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import create_admin, main
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


@pytest.mark.parametrize("name", ["x" * 201, "   "])
def test_create_admin_command_rejects_bad_name(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["create-admin", "--email", "a@example.com", "--name", name]) == 1
    assert "Name must be 1-200 characters." in capsys.readouterr().err
