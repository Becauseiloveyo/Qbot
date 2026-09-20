from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.runtime import ConversationLockManager, DesktopCore
from qbot.transport import IncomingTransportEvent, MockTransport


class RuntimeCoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        self.transport = MockTransport()
        await self.transport.start()
        self.core = DesktopCore(self.db, self.transport)

    async def asyncTearDown(self) -> None:
        await self.transport.stop()
        self.db.close()
        self.tmp.cleanup()

    async def test_process_one_admits_event_and_creates_run(self) -> None:
        await self.transport.inject(
            IncomingTransportEvent(
                account_id="acc-1",
                conversation_id="conv-1",
                sender_id="contact-1",
                platform_message_id="msg-1",
                text="hello",
                occurred_at=datetime.now(UTC),
            )
        )

        result = await self.core.process_one()
        self.assertTrue(result.is_new)
        self.assertTrue(result.event_id.startswith("evt-"))
        self.assertTrue(result.run_id.startswith("run-"))


class ConversationLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_conversation_is_serialized(self) -> None:
        locks = ConversationLockManager()
        first_entered = self.entered = __import__("asyncio").Event()
        release_first = __import__("asyncio").Event()
        order: list[str] = []

        async def first() -> None:
            async with locks.serial("acc", "conv"):
                order.append("first-enter")
                first_entered.set()
                await release_first.wait()
                order.append("first-exit")

        async def second() -> None:
            await first_entered.wait()
            async with locks.serial("acc", "conv"):
                order.append("second-enter")

        import asyncio

        first_task = asyncio.create_task(first())
        second_task = asyncio.create_task(second())
        await first_entered.wait()
        await asyncio.sleep(0)
        self.assertEqual(order, ["first-enter"])

        release_first.set()
        await asyncio.gather(first_task, second_task)
        self.assertEqual(
            order,
            ["first-enter", "first-exit", "second-enter"],
        )


if __name__ == "__main__":
    unittest.main()
