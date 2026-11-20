"""A database lease lock that works across workers, containers and channels.

Holding a database transaction open during the LLM calls would tie up a connection for seconds, so
the lock is a row with an expiry instead: acquiring inserts it, releasing deletes it, and a row left
behind by a crashed worker stops counting once it expires.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import ChatLock, utcnow

LEASE = timedelta(minutes=3)
WAIT_SECONDS = 60.0
POLL_SECONDS = 0.2


class LockTimeout(Exception):
    pass


class DbLeaseLock:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        lease: timedelta = LEASE,
        wait_seconds: float = WAIT_SECONDS,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._lease = lease
        self._wait = wait_seconds

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        token = secrets.token_hex(16)
        deadline = asyncio.get_running_loop().time() + self._wait
        while not await self._try_acquire(key, token):
            if asyncio.get_running_loop().time() >= deadline:
                raise LockTimeout(f"could not lock {key!r} within {self._wait:.0f}s")
            await asyncio.sleep(POLL_SECONDS)
        try:
            yield
        finally:
            async with self._sessionmaker() as db, db.begin():
                await db.execute(delete(ChatLock).where(ChatLock.key == key, ChatLock.token == token))

    async def _try_acquire(self, key: str, token: str) -> bool:
        now = utcnow()
        try:
            async with self._sessionmaker() as db, db.begin():
                await db.execute(delete(ChatLock).where(ChatLock.key == key, ChatLock.expires_at < now))
                db.add(ChatLock(key=key, token=token, expires_at=now + self._lease))
        except IntegrityError:
            return False
        return True
