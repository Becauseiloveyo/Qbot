from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.outbox import DuplicateOutboxEffect, OutboxRepository
from qbot.runtime import EventNormalizer
from qbot.runtime.send import SendExecutor
from qbot.transport import IncomingTransportEvent, MockTransport


class OutboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(QbotConfig(database_path=Path(self.tmp.name) / "qbot.db"))
        self.db.bootstrap()
        event = EventNormalizer("mock").normalize(
            IncomingTransportEvent(
                account_id="acc-1",
                conversation_id="conv-1",
                platform_message_id="msg-1",
                text="hello",
                occurred_at=datetime.now(UTC),
            )
        )
        admitted = InboundAdmissionRepository(self.db).admit(event)
        self.run_id = admitted.run_id
        self.outbox = OutboxRepository(self.db)
        self.transport = MockTransport()
        await self.transport.start()
        self.executor = SendExecutor(self.outbox, self.transport)

    async def asyncTearDown(self) -> None:
        await self.transport.stop()
        self.db.close()
        self.tmp.cleanup()

    def _create(self, dedupe_key: str = "run-1:reply-main"):
        return self.outbox.create_text(
            run_id=self.run_id,
            account_id="acc-1",
            conversation_id="conv-1",
            dedupe_key=dedupe_key,
            text="在",
            reply_to_message_id="msg-1",
        )

    async def test_pending_to_sent(self) -> None:
        record = self._create()
        sent = await self.executor.send(record.outbox_id)
        self.assertEqual(sent.status, "SENT")
        self.assertEqual(sent.transport_attempts, 1)
        self.assertIsNotNone(sent.platform_message_id)

    async def test_unique_account_dedupe_key(self) -> None:
        self._create()
        with self.assertRaises(DuplicateOutboxEffect):
            self._create()

    async def test_uncertain_after_delivery_reconciles_without_resend(self) -> None:
        record = self._create("run-1:ambiguous")
        self.transport.make_next_send_uncertain_after_delivery()

        unknown = await self.executor.send(record.outbox_id)
        self.assertEqual(unknown.status, "SENDING_UNKNOWN")
        self.assertEqual(unknown.transport_attempts, 1)

        reconciled = await self.executor.reconcile(record.outbox_id)
        self.assertEqual(reconciled.status, "SENT")
        self.assertEqual(reconciled.transport_attempts, 1)
        self.assertIsNotNone(reconciled.platform_message_id)


if __name__ == "__main__":
    unittest.main()
