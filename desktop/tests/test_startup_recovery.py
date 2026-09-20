from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.app import build_runtime
from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.runtime import EventNormalizer
from qbot.runtime.recovery_executor import RecoveryMode
from qbot.transport import IncomingTransportEvent, MockTransport


class StartupRecoveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "qbot.db"
        self.config = QbotConfig(database_path=self.db_path)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_pending_effect(self, suffix: str):
        db = Database(self.config)
        db.bootstrap()
        try:
            event = EventNormalizer("mock").normalize(
                IncomingTransportEvent(
                    account_id="acc-1",
                    conversation_id=f"private:{suffix}",
                    sender_id="contact-1",
                    platform_message_id=f"msg-{suffix}",
                    text="hello",
                    occurred_at=datetime.now(UTC),
                )
            )
            admitted = InboundAdmissionRepository(db).admit(event)
            runs = AgentRunRepository(db)
            runs.transition(admitted.run_id, "RESTORING")
            runs.transition(admitted.run_id, "REASONING")
            runs.transition(admitted.run_id, "EXECUTING")

            effect = OutboxRepository(db).create_text(
                run_id=admitted.run_id,
                account_id="acc-1",
                conversation_id=event.conversation_id,
                dedupe_key=f"{admitted.run_id}:primary-reply",
                text="durable pending reply",
            )
            return admitted.run_id, effect.outbox_id
        finally:
            db.close()

    async def test_observe_restart_reports_but_does_not_send_pending_effect(self) -> None:
        run_id, outbox_id = self._seed_pending_effect("observe")

        runtime = build_runtime(
            config=self.config,
            transport=MockTransport(),
        )
        try:
            report = await runtime.start(RecoveryMode.OBSERVE)
            self.assertEqual(report.mode, RecoveryMode.OBSERVE)
            self.assertEqual(runtime.core.outbox.load(outbox_id).status, "PENDING")
            self.assertEqual(runtime.core.runs.load(run_id).status, "EXECUTING")
            self.assertEqual(
                next(
                    item.outcome
                    for item in report.executions
                    if item.item.outbox_id == outbox_id
                ),
                "REPORTED",
            )
        finally:
            await runtime.stop()

    async def test_assist_restart_sends_existing_pending_effect_and_finalizes(self) -> None:
        run_id, outbox_id = self._seed_pending_effect("assist")

        transport = MockTransport()
        runtime = build_runtime(
            config=self.config,
            transport=transport,
        )
        try:
            report = await runtime.start(RecoveryMode.ASSIST)
            recovered = runtime.core.outbox.load(outbox_id)
            self.assertEqual(recovered.status, "SENT")
            self.assertEqual(recovered.transport_attempts, 1)
            self.assertEqual(runtime.core.runs.load(run_id).status, "SUCCEEDED")
            self.assertEqual(
                next(
                    item.outcome
                    for item in report.executions
                    if item.item.outbox_id == outbox_id
                ),
                "SENT",
            )
        finally:
            await runtime.stop()

    async def test_second_assist_restart_does_not_resend_already_sent_effect(self) -> None:
        run_id, outbox_id = self._seed_pending_effect("idempotent")

        first = build_runtime(
            config=self.config,
            transport=MockTransport(),
        )
        try:
            await first.start(RecoveryMode.ASSIST)
            first_record = first.core.outbox.load(outbox_id)
            self.assertEqual(first_record.status, "SENT")
            self.assertEqual(first_record.transport_attempts, 1)
        finally:
            await first.stop()

        second = build_runtime(
            config=self.config,
            transport=MockTransport(),
        )
        try:
            report = await second.start(RecoveryMode.ASSIST)
            second_record = second.core.outbox.load(outbox_id)
            self.assertEqual(second_record.status, "SENT")
            self.assertEqual(second_record.transport_attempts, 1)
            self.assertEqual(second.core.runs.load(run_id).status, "SUCCEEDED")
            self.assertEqual(report.plan.items, ())
        finally:
            await second.stop()


if __name__ == "__main__":
    unittest.main()
