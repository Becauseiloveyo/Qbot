from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.journal import JournalRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.persistence.tables import task_checkpoints, task_steps, tasks
from qbot.persistence.tasks import TaskRepository
from qbot.runtime import EventNormalizer
from qbot.runtime.recovery import RecoveryPlanner
from qbot.runtime.recovery_executor import RecoveryExecutor, RecoveryMode
from qbot.runtime.reply_flow import DurableReplyFlow
from qbot.runtime.send import SendExecutor
from qbot.transport import (
    DeliveryLookupResult,
    IncomingTransportEvent,
    MockTransport,
    OutgoingMessage,
    SendResult,
    TransportCapability,
)


class SharedDeliveryTransport(MockTransport):
    """Fake external platform whose delivery history survives transport recreation."""

    def __init__(self, shared: dict[tuple[str, str], str], *, crash=False) -> None:
        super().__init__()
        self.shared = shared
        self.crash = crash
        self.counter = len(shared)

    @property
    def capabilities(self):
        return frozenset(
            {
                TransportCapability.READ_TEXT,
                TransportCapability.SEND_TEXT,
                TransportCapability.DELIVERY_LOOKUP,
            }
        )

    async def send(self, message: OutgoingMessage) -> SendResult:
        self._require_started()
        key = (message.account_id, message.dedupe_key)
        platform_id = self.shared.get(key)
        if platform_id is None:
            self.counter += 1
            platform_id = f"external-{self.counter}"
            self.shared[key] = platform_id

        if self.crash:
            # Simulate process death after the remote platform accepted the
            # message but before Qbot could commit SENT locally.
            raise SystemExit("injected crash after remote delivery")

        return SendResult(
            accepted=True,
            platform_message_id=platform_id,
        )

    async def lookup_delivery(
        self,
        account_id: str,
        dedupe_key: str,
    ) -> DeliveryLookupResult:
        self._require_started()
        platform_id = self.shared.get((account_id, dedupe_key))
        return DeliveryLookupResult(
            found=platform_id is not None,
            platform_message_id=platform_id,
        )


class CrashInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "qbot.db"
        self.db = Database(QbotConfig(database_path=self.db_path))
        self.assertFalse(self.db.bootstrap().safe_mode)

    async def asyncTearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _seed_task(self) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                tasks.insert().values(
                    task_id="task-crash",
                    schema_version="0.1.0",
                    conversation_id="conv-task",
                    parent_task_id=None,
                    goal="durable task",
                    status="READY",
                    phase="phase-1",
                    constraints_json="[]",
                    decisions_json=json.dumps(["commit atomically"]),
                    blockers_json="[]",
                    next_action="step one",
                    writer_epoch=3,
                    version=1,
                    created_at="2026-09-20T00:00:00Z",
                    updated_at="2026-09-20T00:00:00Z",
                )
            )
            conn.execute(
                task_steps.insert().values(
                    step_id="step-crash",
                    task_id="task-crash",
                    sequence=1,
                    description="step one",
                    status="PENDING",
                    result=None,
                    error=None,
                    started_at=None,
                    completed_at=None,
                )
            )

    def test_crash_before_checkpoint_commit_rolls_back_task_and_step(self) -> None:
        self._seed_task()
        repo = TaskRepository(self.db)

        with patch.object(
            repo,
            "_insert_checkpoint",
            side_effect=SystemExit("injected crash before checkpoint"),
        ):
            with self.assertRaises(SystemExit):
                repo.start_step(
                    task_id="task-crash",
                    step_id="step-crash",
                    expected_version=1,
                    writer_epoch=3,
                )

        with self.db.engine.connect() as conn:
            task = conn.execute(
                select(tasks).where(tasks.c.task_id == "task-crash")
            ).mappings().one()
            step = conn.execute(
                select(task_steps).where(task_steps.c.step_id == "step-crash")
            ).mappings().one()
            checkpoints = conn.execute(
                select(func.count()).select_from(task_checkpoints)
            ).scalar_one()

        self.assertEqual(task["version"], 1)
        self.assertEqual(task["status"], "READY")
        self.assertEqual(step["status"], "PENDING")
        self.assertEqual(checkpoints, 0)

    async def test_crash_after_remote_delivery_recovers_by_lookup_without_resend(self) -> None:
        event = EventNormalizer("mock").normalize(
            IncomingTransportEvent(
                account_id="acc-1",
                conversation_id="private:crash",
                sender_id="contact-1",
                platform_message_id="msg-crash",
                text="hello",
                occurred_at=datetime.now(UTC),
            )
        )
        admission = InboundAdmissionRepository(self.db)
        admitted = admission.admit(event)
        runs = AgentRunRepository(self.db)
        runs.transition(admitted.run_id, "RESTORING")
        runs.transition(admitted.run_id, "REASONING")
        runs.transition(admitted.run_id, "EXECUTING")

        outbox = OutboxRepository(self.db)
        effect = outbox.create_text(
            run_id=admitted.run_id,
            account_id="acc-1",
            conversation_id=event.conversation_id,
            dedupe_key=f"{admitted.run_id}:primary-reply",
            text="reply once",
        )

        external: dict[tuple[str, str], str] = {}
        crashing = SharedDeliveryTransport(external, crash=True)
        await crashing.start()
        try:
            with self.assertRaises(SystemExit):
                await SendExecutor(outbox, crashing).send(effect.outbox_id)
        finally:
            await crashing.stop()

        # Local commit stopped at SENDING, but the external system has one
        # durable delivery.
        self.assertEqual(outbox.load(effect.outbox_id).status, "SENDING")
        self.assertEqual(outbox.load(effect.outbox_id).transport_attempts, 1)
        self.assertEqual(len(external), 1)

        restored_transport = SharedDeliveryTransport(external, crash=False)
        await restored_transport.start()
        try:
            journal = JournalRepository(self.db)
            flow = DurableReplyFlow(
                admission=admission,
                runs=runs,
                outbox=outbox,
                journal=journal,
                transport=restored_transport,
            )
            executor = RecoveryExecutor(
                planner=RecoveryPlanner(
                    runs=runs,
                    outbox=outbox,
                    transport=restored_transport,
                ),
                runs=runs,
                outbox=outbox,
                journal=journal,
                transport=restored_transport,
                reply_flow=flow,
            )
            report = await executor.run(RecoveryMode.ASSIST)
        finally:
            await restored_transport.stop()

        recovered = outbox.load(effect.outbox_id)
        self.assertEqual(recovered.status, "SENT")
        self.assertEqual(recovered.transport_attempts, 1)
        self.assertEqual(runs.load(admitted.run_id).status, "SUCCEEDED")
        self.assertEqual(len(external), 1)

        execution = next(
            item
            for item in report.executions
            if item.item.outbox_id == effect.outbox_id
        )
        self.assertEqual(execution.outcome, "RECONCILED")


if __name__ == "__main__":
    unittest.main()
