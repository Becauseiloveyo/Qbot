from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.journal import JournalRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.runtime import EventNormalizer
from qbot.runtime.reply_flow import DurableReplyFlow
from qbot.transport import IncomingTransportEvent, MockTransport


class DurableReplyFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(QbotConfig(database_path=Path(self.tmp.name) / "qbot.db"))
        self.db.bootstrap()
        self.transport = MockTransport()
        await self.transport.start()

        self.admission = InboundAdmissionRepository(self.db)
        self.runs = AgentRunRepository(self.db)
        self.outbox = OutboxRepository(self.db)
        self.flow = DurableReplyFlow(
            admission=self.admission,
            runs=self.runs,
            outbox=self.outbox,
            journal=JournalRepository(self.db),
            transport=self.transport,
        )

    async def asyncTearDown(self) -> None:
        await self.transport.stop()
        self.db.close()
        self.tmp.cleanup()

    def _admit(self):
        event = EventNormalizer("mock").normalize(
            IncomingTransportEvent(
                account_id="acc-1",
                conversation_id="conv-1",
                sender_id="contact-1",
                platform_message_id="msg-e2e-1",
                text="在吗",
                occurred_at=datetime.now(UTC),
            )
        )
        result = self.admission.admit(event)
        return event, result

    async def test_admitted_run_reaches_durable_sent_reply(self) -> None:
        event, admitted = self._admit()
        result = await self.flow.execute(
            run_id=admitted.run_id,
            event_id=event.event_id,
        )

        self.assertEqual(result.run_status, "SUCCEEDED")
        self.assertIsNotNone(result.outbox)
        self.assertEqual(result.outbox.status, "SENT")
        self.assertEqual(result.outbox.transport_attempts, 1)

        restored = self.runs.load(admitted.run_id)
        self.assertEqual(restored.status, "SUCCEEDED")

        duplicate_execution = await self.flow.execute(
            run_id=admitted.run_id,
            event_id=event.event_id,
        )
        self.assertEqual(duplicate_execution.run_status, "SUCCEEDED")
        self.assertEqual(
            duplicate_execution.outbox.platform_message_id,
            result.outbox.platform_message_id,
        )

    async def test_ambiguous_send_remains_recoverable_and_reconciles(self) -> None:
        event, admitted = self._admit()
        self.transport.make_next_send_uncertain_after_delivery()

        first = await self.flow.execute(
            run_id=admitted.run_id,
            event_id=event.event_id,
        )
        self.assertEqual(first.run_status, "EXECUTING")
        self.assertEqual(first.outbox.status, "SENDING_UNKNOWN")

        recovered = await self.flow.execute(
            run_id=admitted.run_id,
            event_id=event.event_id,
        )
        self.assertEqual(recovered.run_status, "SUCCEEDED")
        self.assertEqual(recovered.outbox.status, "SENT")
        self.assertEqual(recovered.outbox.transport_attempts, 1)


if __name__ == "__main__":
    unittest.main()
