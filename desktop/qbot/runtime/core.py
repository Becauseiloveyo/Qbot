from __future__ import annotations

from qbot.persistence import Database
from qbot.persistence.admission import AdmissionResult, InboundAdmissionRepository
from qbot.persistence.journal import JournalRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.transport import QQTransport

from .locks import ConversationLockManager
from .normalizer import EventNormalizer
from .reply_flow import DurableReplyFlow, ReplyFlowResult


class DesktopCore:
    """Durable Desktop message core before NapCat integration."""

    def __init__(
        self,
        database: Database,
        transport: QQTransport,
        locks: ConversationLockManager | None = None,
    ) -> None:
        self.database = database
        self.transport = transport
        self.normalizer = EventNormalizer(transport_name=transport.name)
        self.admission = InboundAdmissionRepository(database)
        self.runs = AgentRunRepository(database)
        self.outbox = OutboxRepository(database)
        self.journal = JournalRepository(database)
        self.locks = locks or ConversationLockManager()
        self.reply_flow = DurableReplyFlow(
            admission=self.admission,
            runs=self.runs,
            outbox=self.outbox,
            journal=self.journal,
            transport=transport,
        )

    async def process_one(self) -> AdmissionResult:
        """Receive and durably admit one event without executing a reply."""

        incoming = await self.transport.receive()
        event = self.normalizer.normalize(incoming)

        async with self.locks.serial(
            event.account_id,
            event.conversation_id,
        ):
            return self.admission.admit(event)

    async def process_one_with_mock_reply(self) -> ReplyFlowResult:
        """Receive one event and drive the current deterministic reply pipeline."""

        incoming = await self.transport.receive()
        event = self.normalizer.normalize(incoming)

        async with self.locks.serial(
            event.account_id,
            event.conversation_id,
        ):
            admitted = self.admission.admit(event)
            return await self.reply_flow.execute(
                run_id=admitted.run_id,
                event_id=admitted.event_id,
            )
