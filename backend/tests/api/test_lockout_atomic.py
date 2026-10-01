"""Failed-login counting must be atomic: two requests holding stale user state must each add
one failure, so the fifth failure locks the account even when counted concurrently."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import User
from app.services.auth import register_failure
from tests.factories import make_user, reload


async def test_concurrent_failures_are_not_lost(
    db_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with db_sessionmaker() as setup:
        user = await make_user(setup, settings)
        user.failed_logins = 3
        await setup.commit()
        user_id = user.id
    now = datetime.now(UTC)
    async with db_sessionmaker() as db_a, db_sessionmaker() as db_b:
        stale_a = await db_a.get(User, user_id)
        stale_b = await db_b.get(User, user_id)  # both see failed_logins == 3
        assert await register_failure(db_a, stale_a, settings, now) is False
        await db_a.commit()
        assert await register_failure(db_b, stale_b, settings, now) is True
        await db_b.commit()
    async with db_sessionmaker() as check:
        locked = await reload(check, User, user_id)
        assert locked is not None
        assert locked.locked_until is not None and locked.locked_until > now
        assert locked.failed_logins == 0
