from __future__ import annotations

from qbot.persistence import Database
from qbot.persistence.admission import AdmissionResult, InboundAdmissionRepository
from qbot.transport import QQTransport

from .locks import ConversationLockManager
from .normalizer import EventNormalizer


class DesktopCore:
    """First durable Desktop event path.

    v0.2 currently stops after durable admission and primary AgentRun creation.
    Reasoning/restoration will be layered on only after this path is stable.
    """

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
        self.locks = locks or ConversationLockManager()

    async def process_one(self) -> AdmissionResult:
        incoming = await self.transport.receive()
        event = self.normalizer.normalize(incoming)

        async with self.locks.serial(
            event.account_id,
            event.conversation_id,
        ):
            return self.admission.admit(event)
