from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.runtime import EventNormalizer
from qbot.runtime.recovery import RecoveryAction, RecoveryPlanner
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


class RecoveryPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        self.runs = AgentRunRepository(self.db)
        self.outbox = OutboxRepository(self.db)

    def tearDown(self) -> None:
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

    def _create_outbox(self, run_id: str, conversation_id: str):
        return self.outbox.create_text(
            run_id=run_id,
            account_id="acc-1",
            conversation_id=conversation_id,
            dedupe_key=f"{run_id}:primary-reply",
            text="reply",
        )

    def test_crash_left_sending_becomes_unknown_and_reconciles_when_supported(self) -> None:
        event, admitted = self._new_run("msg-1")
        self._to_executing(admitted.run_id)
        effect = self._create_outbox(admitted.run_id, event.conversation_id)
        self.outbox.transition(
            effect.outbox_id,
            "SENDING",
            increment_attempt=True,
        )

        plan = RecoveryPlanner(
            runs=self.runs,
            outbox=self.outbox,
            transport=MockTransport(),
        ).plan()

        self.assertEqual(
            self.outbox.load(effect.outbox_id).status,
            "SENDING_UNKNOWN",
        )
        self.assertIn(
            effect.outbox_id,
            plan.interrupted_sends_reclassified,
        )
        item = next(
            item for item in plan.items if item.outbox_id == effect.outbox_id
        )
        self.assertEqual(item.action, RecoveryAction.RECONCILE_UNKNOWN)

    def test_unknown_without_lookup_requires_manual_review_not_replay(self) -> None:
        event, admitted = self._new_run("msg-2")
        self._to_executing(admitted.run_id)
        effect = self._create_outbox(admitted.run_id, event.conversation_id)
        self.outbox.transition(
            effect.outbox_id,
            "SENDING",
            increment_attempt=True,
        )
        self.outbox.transition(
            effect.outbox_id,
            "SENDING_UNKNOWN",
            error="ack lost",
        )

        plan = RecoveryPlanner(
            runs=self.runs,
            outbox=self.outbox,
            transport=NoLookupMockTransport(),
        ).plan()

        actions = [
            item.action
            for item in plan.items
            if item.outbox_id == effect.outbox_id
        ]
        self.assertEqual(actions, [RecoveryAction.MANUAL_REVIEW])
        self.assertNotIn(RecoveryAction.SEND_PENDING, actions)

    def test_pending_effect_is_safe_send_candidate(self) -> None:
        event, admitted = self._new_run("msg-3")
        self._to_executing(admitted.run_id)
        effect = self._create_outbox(admitted.run_id, event.conversation_id)

        plan = RecoveryPlanner(
            runs=self.runs,
            outbox=self.outbox,
            transport=NoLookupMockTransport(),
        ).plan()

        item = next(
            item for item in plan.items if item.outbox_id == effect.outbox_id
        )
        self.assertEqual(item.action, RecoveryAction.SEND_PENDING)

    def test_sent_effect_only_finalizes_local_run(self) -> None:
        event, admitted = self._new_run("msg-4")
        self._to_executing(admitted.run_id)
        effect = self._create_outbox(admitted.run_id, event.conversation_id)
        self.outbox.transition(
            effect.outbox_id,
            "SENDING",
            increment_attempt=True,
        )
        self.outbox.transition(
            effect.outbox_id,
            "SENT",
            platform_message_id="platform-1",
        )

        plan = RecoveryPlanner(
            runs=self.runs,
            outbox=self.outbox,
            transport=NoLookupMockTransport(),
        ).plan()

        run_items = [
            item for item in plan.items if item.run_id == admitted.run_id
        ]
        self.assertEqual(
            [item.action for item in run_items],
            [RecoveryAction.FINALIZE_SENT_RUN],
        )

    def test_run_without_effect_is_resumed_and_waiting_user_is_preserved(self) -> None:
        _, resumable = self._new_run("msg-5")
        _, waiting = self._new_run("msg-6")
        self.runs.transition(waiting.run_id, "RESTORING")
        self.runs.transition(waiting.run_id, "REASONING")
        self.runs.transition(waiting.run_id, "WAITING_USER")

        plan = RecoveryPlanner(
            runs=self.runs,
            outbox=self.outbox,
            transport=NoLookupMockTransport(),
        ).plan()

        by_run = {item.run_id: item.action for item in plan.items}
        self.assertEqual(
            by_run[resumable.run_id],
            RecoveryAction.RESUME_RUN,
        )
        self.assertEqual(
            by_run[waiting.run_id],
            RecoveryAction.WAITING_USER,
        )


if __name__ == "__main__":
    unittest.main()
