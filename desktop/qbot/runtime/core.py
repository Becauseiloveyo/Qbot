from __future__ import annotations

import asyncio

from qbot.persistence import Database
from qbot.persistence.admission import AdmissionResult, InboundAdmissionRepository
from qbot.persistence.journal import JournalRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.transport import QQTransport

from .decision import DecisionEngine
from .locks import ConversationLockManager
from .normalizer import EventNormalizer
from .reply_flow import DurableReplyFlow, ReplyFlowResult


class DesktopCore:
    """Durable Desktop message core."""

    def __init__(
        self,
        database: Database,
        transport: QQTransport,
        locks: ConversationLockManager | None = None,
        decision: DecisionEngine | None = None,
        memory_maintenance=None,
    ) -> None:
        self.database = database
        self.transport = transport
        self.normalizer = EventNormalizer(transport_name=transport.name)
        self.admission = InboundAdmissionRepository(database)
        self.runs = AgentRunRepository(database)
        self.outbox = OutboxRepository(database)
        self.journal = JournalRepository(database)
        self.locks = locks or ConversationLockManager()
        self.memory_maintenance = memory_maintenance
        self._maintenance_tasks: set[asyncio.Task] = set()
        self.reply_flow = DurableReplyFlow(
            admission=self.admission,
            runs=self.runs,
            outbox=self.outbox,
            journal=self.journal,
            transport=transport,
            decision=decision,
        )

    def set_memory_maintenance(self, service) -> None:
        self.memory_maintenance = service

    def set_decision_engine(self, decision: DecisionEngine) -> None:
        """Install an explicit decision engine after runtime bootstrap."""

        self.reply_flow.decision = decision

    async def process_one(self) -> AdmissionResult:
        """Observe mode: durably admit one event without executing a reply."""

        incoming = await self.transport.receive()
        event = self.normalizer.normalize(incoming)

        async with self.locks.serial(
            event.account_id,
            event.conversation_id,
        ):
            admitted = self.admission.admit(event)
            if admitted.is_new:
                self._schedule_memory_maintenance(admitted.event_id)
            return admitted

    async def process_one_with_reply(self) -> ReplyFlowResult:
        """Assist mode: admit then execute through Policy and durable Outbox."""

        incoming = await self.transport.receive()
        event = self.normalizer.normalize(incoming)

        async with self.locks.serial(
            event.account_id,
            event.conversation_id,
        ):
            admitted = self.admission.admit(event)
            result = await self.reply_flow.execute(
                run_id=admitted.run_id,
                event_id=admitted.event_id,
            )
            if admitted.is_new:
                self._schedule_memory_maintenance(admitted.event_id)
            return result

    def schedule_memory_catch_up(self) -> None:
        if self.memory_maintenance is None:
            return
        task = asyncio.create_task(self.memory_maintenance.catch_up())
        self._track_maintenance_task(task)

    async def drain_memory_maintenance(self) -> None:
        if not self._maintenance_tasks:
            return
        await asyncio.gather(
            *tuple(self._maintenance_tasks),
            return_exceptions=True,
        )

    def _schedule_memory_maintenance(self, event_id: str) -> None:
        if self.memory_maintenance is None:
            return
        task = asyncio.create_task(
            self.memory_maintenance.process_event(event_id)
        )
        self._track_maintenance_task(task)

    def _track_maintenance_task(self, task: asyncio.Task) -> None:
        self._maintenance_tasks.add(task)
        task.add_done_callback(self._maintenance_tasks.discard)

    async def process_one_with_mock_reply(self) -> ReplyFlowResult:
        """Backward-compatible alias for existing v0.2 tests."""

        return await self.process_one_with_reply()
