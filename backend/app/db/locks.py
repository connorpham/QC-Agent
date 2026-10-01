"""PostgreSQL advisory transaction locks with namespaced keys."""

import hashlib

from sqlalchemy import BigInteger, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession


def advisory_key(namespace: str, value: str) -> int:
    """Deterministic signed 64-bit key for ``pg_advisory_xact_lock``, stable across processes
    (the lock key space is a plain bigint, so a namespace prefix keeps different lock uses from
    colliding on the same hash)."""
    digest = hashlib.sha256(f"{namespace}:{value}".encode()).digest()[:8]
    unsigned = int.from_bytes(digest, "big")
    return unsigned - 2**64 if unsigned >= 2**63 else unsigned


async def acquire_xact_lock(db: AsyncSession, namespace: str, value: str) -> None:
    """Block until the lock is held; it is released automatically at commit or rollback."""
    await db.execute(
        select(func.pg_advisory_xact_lock(literal(advisory_key(namespace, value), BigInteger)))
    )
