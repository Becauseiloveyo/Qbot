from __future__ import annotations

import asyncio

from .base import (
    DeliveryLookupResult,
    IncomingTransportEvent,
    OutgoingMessage,
    QQTransport,
    SendResult,
    TransportCapability,
)


class MockTransport(QQTransport):
    """Deterministic in-memory transport for runtime/conformance tests."""

    def __init__(self) -> None:
        self._incoming: asyncio.Queue[IncomingTransportEvent] = asyncio.Queue()
        self._started = False
        self._send_counter = 0
        self._delivery_by_key: dict[tuple[str, str], str] = {}
        self._next_send_uncertain_after_delivery = False

    @property
    def name(self) -> str:
        return "mock"

    @property
    def capabilities(self) -> frozenset[TransportCapability]:
        return frozenset(
            {
                TransportCapability.READ_TEXT,
                TransportCapability.SEND_TEXT,
                TransportCapability.READ_HISTORY,
                TransportCapability.QUOTE_REPLY,
                TransportCapability.DELIVERY_LOOKUP,
            }
        )

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def inject(self, event: IncomingTransportEvent) -> None:
        await self._incoming.put(event)

    async def receive(self) -> IncomingTransportEvent:
        self._require_started()
        return await self._incoming.get()

    def make_next_send_uncertain_after_delivery(self) -> None:
        """Simulate a transport write that succeeds but loses its acknowledgement."""

        self._next_send_uncertain_after_delivery = True

    async def send(self, message: OutgoingMessage) -> SendResult:
        self._require_started()
        delivery_key = (message.account_id, message.dedupe_key)

        existing = self._delivery_by_key.get(delivery_key)
        if existing is not None:
            return SendResult(
                accepted=True,
                platform_message_id=existing,
            )

        self._send_counter += 1
        platform_message_id = f"mock-msg-{self._send_counter}"
        self._delivery_by_key[delivery_key] = platform_message_id

        if self._next_send_uncertain_after_delivery:
            self._next_send_uncertain_after_delivery = False
            return SendResult(
                accepted=True,
                platform_message_id=None,
                uncertain=True,
                error="simulated acknowledgement loss after delivery",
            )

        return SendResult(
            accepted=True,
            platform_message_id=platform_message_id,
        )

    async def lookup_delivery(
        self,
        account_id: str,
        dedupe_key: str,
    ) -> DeliveryLookupResult:
        self._require_started()
        platform_message_id = self._delivery_by_key.get((account_id, dedupe_key))
        return DeliveryLookupResult(
            found=platform_message_id is not None,
            platform_message_id=platform_message_id,
        )

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("transport is not started")
