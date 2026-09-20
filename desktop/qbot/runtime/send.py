from __future__ import annotations

from qbot.persistence.outbox import OutboxRecord, OutboxRepository
from qbot.transport import OutgoingMessage, QQTransport, TransportCapability


class SendExecutor:
    """Drive one durable Outbox record through transport side effects."""

    def __init__(
        self,
        outbox: OutboxRepository,
        transport: QQTransport,
    ) -> None:
        self.outbox = outbox
        self.transport = transport

    async def send(self, outbox_id: str) -> OutboxRecord:
        record = self.outbox.load(outbox_id)
        if record.status != "PENDING":
            raise ValueError(
                f"send requires PENDING Outbox record, got {record.status}"
            )

        record = self.outbox.transition(
            outbox_id,
            "SENDING",
            increment_attempt=True,
        )

        message = OutgoingMessage(
            account_id=record.account_id,
            conversation_id=record.conversation_id,
            dedupe_key=record.dedupe_key,
            text=record.payload_text or "",
            reply_to_message_id=record.reply_to_message_id,
        )

        try:
            result = await self.transport.send(message)
        except Exception as exc:
            return self.outbox.transition(
                outbox_id,
                "SENDING_UNKNOWN",
                error=str(exc),
            )

        if result.uncertain:
            return self.outbox.transition(
                outbox_id,
                "SENDING_UNKNOWN",
                platform_message_id=result.platform_message_id,
                error=result.error,
            )

        if result.accepted:
            return self.outbox.transition(
                outbox_id,
                "SENT",
                platform_message_id=result.platform_message_id,
            )

        return self.outbox.transition(
            outbox_id,
            "FAILED",
            error=result.error or "transport rejected message",
        )

    async def reconcile(self, outbox_id: str) -> OutboxRecord:
        record = self.outbox.load(outbox_id)
        if record.status != "SENDING_UNKNOWN":
            return record

        if TransportCapability.DELIVERY_LOOKUP not in self.transport.capabilities:
            return record

        lookup = await self.transport.lookup_delivery(
            account_id=record.account_id,
            dedupe_key=record.dedupe_key,
        )
        if not lookup.found:
            return record

        return self.outbox.transition(
            outbox_id,
            "SENT",
            platform_message_id=lookup.platform_message_id,
        )
