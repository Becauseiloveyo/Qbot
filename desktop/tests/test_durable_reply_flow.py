from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import func, select
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.domain.actions import ActionProposal, RiskClass
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.journal import JournalRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.persistence.tables import outbox_messages
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


    async def test_r2_send_waits_for_human_and_never_creates_outbox(self) -> None:
        event, admitted = self._admit()

        class R2Decision:
            async def decide(self, *, run_id, event):
                return ActionProposal(
                    proposal_id="proposal-r2",
                    run_id=run_id,
                    action="SEND_MESSAGE",
                    risk_hint=RiskClass.R2,
                    arguments={"text": "需要确认"},
                    source_message_ids=(),
                )

        flow = DurableReplyFlow(
            admission=self.admission,
            runs=self.runs,
            outbox=self.outbox,
            journal=JournalRepository(self.db),
            transport=self.transport,
            decision=R2Decision(),
        )
        result = await flow.execute(
            run_id=admitted.run_id,
            event_id=event.event_id,
        )

        self.assertEqual(result.run_status, "WAITING_USER")
        self.assertIsNone(result.outbox)
        with self.db.engine.connect() as conn:
            count = conn.execute(
                select(func.count()).select_from(outbox_messages)
            ).scalar_one()
        self.assertEqual(count, 0)

    async def test_request_human_is_elevated_even_if_model_marks_r0(self) -> None:
        event, admitted = self._admit()

        class HumanDecision:
            async def decide(self, *, run_id, event):
                return ActionProposal(
                    proposal_id="proposal-human",
                    run_id=run_id,
                    action="REQUEST_HUMAN",
                    risk_hint=RiskClass.R0,
                    arguments={},
                    source_message_ids=(),
                )

        flow = DurableReplyFlow(
            admission=self.admission,
            runs=self.runs,
            outbox=self.outbox,
            journal=JournalRepository(self.db),
            transport=self.transport,
            decision=HumanDecision(),
        )
        result = await flow.execute(
            run_id=admitted.run_id,
            event_id=event.event_id,
        )
        self.assertEqual(result.run_status, "WAITING_USER")
        self.assertIsNone(result.outbox)


if __name__ == "__main__":
    unittest.main()
