from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class ConversationLockManager:
    """Serialize authoritative processing inside one account/conversation."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _get(self, account_id: str, conversation_id: str) -> asyncio.Lock:
        key = (account_id, conversation_id)
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    @asynccontextmanager
    async def serial(
        self,
        account_id: str,
        conversation_id: str,
    ) -> AsyncIterator[None]:
        lock = await self._get(account_id, conversation_id)
        async with lock:
            yield
