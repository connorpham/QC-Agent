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
