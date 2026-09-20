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
from qbot.runtime.recovery import RecoveryAction, RecoveryPlanner
from qbot.runtime.recovery_executor import RecoveryExecutor, RecoveryMode
from qbot.runtime.reply_flow import DurableReplyFlow
from qbot.transport import IncomingTransportEvent, MockTransport, TransportCapability


class NoLookupMockTransport(MockTransport):
    @property
    def capabilities(self):
        return frozenset(
            {
                TransportCapability.READ_TEXT,
                TransportCapability.SEND_TEXT,
            }
        )


class RecoveryExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        self.runs = AgentRunRepository(self.db)
        self.outbox = OutboxRepository(self.db)

    async def asyncTearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _new_run(self, message_id: str):
        event = EventNormalizer("mock").normalize(
            IncomingTransportEvent(
                account_id="acc-1",
                conversation_id=f"private:{message_id}",
                sender_id="contact-1",
                platform_message_id=message_id,
                text="hello",
                occurred_at=datetime.now(UTC),
            )
        )
        admitted = InboundAdmissionRepository(self.db).admit(event)
        return event, admitted

    def _to_executing(self, run_id: str) -> None:
        self.runs.transition(run_id, "RESTORING")
        self.runs.transition(run_id, "REASONING")
        self.runs.transition(run_id, "EXECUTING")

    def _effect(self, run_id: str, conversation_id: str):
        return self.outbox.create_text(
            run_id=run_id,
            account_id="acc-1",
            conversation_id=conversation_id,
            dedupe_key=f"{run_id}:primary-reply",
            text="reply",
        )

    def _executor(self, transport):
        journal = JournalRepository(self.db)
        flow = DurableReplyFlow(
            admission=InboundAdmissionRepository(self.db),
            runs=self.runs,
            outbox=self.outbox,
            journal=journal,
            transport=transport,
        )
        planner = RecoveryPlanner(
            runs=self.runs,
            outbox=self.outbox,
            transport=transport,
        )
        return RecoveryExecutor(
            planner=planner,
            runs=self.runs,
            outbox=self.outbox,
            journal=journal,
            transport=transport,
            reply_flow=flow,
        )

    async def test_observe_reports_pending_but_does_not_send(self) -> None:
        event, admitted = self._new_run("msg-observe")
        self._to_executing(admitted.run_id)
        effect = self._effect(admitted.run_id, event.conversation_id)
        transport = MockTransport()
        await transport.start()
        try:
            report = await self._executor(transport).run(RecoveryMode.OBSERVE)
        finally:
            await transport.stop()

        self.assertEqual(self.outbox.load(effect.outbox_id).status, "PENDING")
        item = next(i for i in report.plan.items if i.outbox_id == effect.outbox_id)
        self.assertEqual(item.action, RecoveryAction.SEND_PENDING)
        self.assertEqual(
            next(x for x in report.executions if x.item == item).outcome,
            "REPORTED",
        )

    async def test_assist_sends_durable_pending_effect_once_and_finalizes(self) -> None:
        event, admitted = self._new_run("msg-pending")
        self._to_executing(admitted.run_id)
        effect = self._effect(admitted.run_id, event.conversation_id)
        transport = MockTransport()
        await transport.start()
        try:
            report = await self._executor(transport).run(RecoveryMode.ASSIST)
        finally:
            await transport.stop()

        self.assertEqual(self.outbox.load(effect.outbox_id).status, "SENT")
        self.assertEqual(self.outbox.load(effect.outbox_id).transport_attempts, 1)
        self.assertEqual(self.runs.load(admitted.run_id).status, "SUCCEEDED")
        execution = next(
            x for x in report.executions if x.item.outbox_id == effect.outbox_id
        )
        self.assertEqual(execution.outcome, "SENT")

    async def test_assist_reconciles_unknown_without_resend(self) -> None:
        event, admitted = self._new_run("msg-unknown")
        self._to_executing(admitted.run_id)
        effect = self._effect(admitted.run_id, event.conversation_id)
        transport = MockTransport()
        await transport.start()
        try:
            transport.make_next_send_uncertain_after_delivery()
            from qbot.runtime.send import SendExecutor

            unknown = await SendExecutor(self.outbox, transport).send(
                effect.outbox_id
            )
            self.assertEqual(unknown.status, "SENDING_UNKNOWN")
            self.assertEqual(unknown.transport_attempts, 1)

            report = await self._executor(transport).run(RecoveryMode.ASSIST)
        finally:
            await transport.stop()

        recovered = self.outbox.load(effect.outbox_id)
        self.assertEqual(recovered.status, "SENT")
        self.assertEqual(recovered.transport_attempts, 1)
        self.assertEqual(self.runs.load(admitted.run_id).status, "SUCCEEDED")
        execution = next(
            x for x in report.executions if x.item.outbox_id == effect.outbox_id
        )
        self.assertEqual(execution.outcome, "RECONCILED")

    async def test_assist_does_not_touch_unknown_without_lookup(self) -> None:
        event, admitted = self._new_run("msg-manual")
        self._to_executing(admitted.run_id)
        effect = self._effect(admitted.run_id, event.conversation_id)
        self.outbox.transition(
            effect.outbox_id,
            "SENDING",
            increment_attempt=True,
        )
        self.outbox.transition(
            effect.outbox_id,
            "SENDING_UNKNOWN",
            error="lost ack",
        )
        transport = NoLookupMockTransport()
        await transport.start()
        try:
            report = await self._executor(transport).run(RecoveryMode.ASSIST)
        finally:
            await transport.stop()

        self.assertEqual(
            self.outbox.load(effect.outbox_id).status,
            "SENDING_UNKNOWN",
        )
        self.assertEqual(
            self.outbox.load(effect.outbox_id).transport_attempts,
            1,
        )
        execution = next(
            x for x in report.executions if x.item.outbox_id == effect.outbox_id
        )
        self.assertEqual(execution.outcome, "DEFERRED")

    async def test_sent_but_unfinalized_only_updates_local_run(self) -> None:
        event, admitted = self._new_run("msg-sent")
        self._to_executing(admitted.run_id)
        effect = self._effect(admitted.run_id, event.conversation_id)
        self.outbox.transition(
            effect.outbox_id,
            "SENDING",
            increment_attempt=True,
        )
        self.outbox.transition(
            effect.outbox_id,
            "SENT",
            platform_message_id="platform-existing",
        )
        transport = NoLookupMockTransport()
        await transport.start()
        try:
            report = await self._executor(transport).run(RecoveryMode.ASSIST)
        finally:
            await transport.stop()

        self.assertEqual(self.runs.load(admitted.run_id).status, "SUCCEEDED")
        self.assertEqual(
            self.outbox.load(effect.outbox_id).transport_attempts,
            1,
        )
        self.assertEqual(report.executions[0].outcome, "FINALIZED")


if __name__ == "__main__":
    unittest.main()
