from __future__ import annotations

import unittest
from datetime import UTC, datetime

from qbot.transport import (
    IncomingTransportEvent,
    MockTransport,
    OutgoingMessage,
    TransportCapability,
)


class MockTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.transport = MockTransport()
        await self.transport.start()

    async def asyncTearDown(self) -> None:
        await self.transport.stop()

    async def test_receive_injected_event(self) -> None:
        event = IncomingTransportEvent(
            account_id="acc-1",
            conversation_id="conv-1",
            sender_id="contact-1",
            platform_message_id="msg-1",
            text="hello",
            occurred_at=datetime.now(UTC),
        )
        await self.transport.inject(event)
        received = await self.transport.receive()
        self.assertEqual(received, event)

    async def test_same_dedupe_key_is_effectively_once(self) -> None:
        message = OutgoingMessage(
            account_id="acc-1",
            conversation_id="conv-1",
            dedupe_key="run-1:reply",
            text="hello",
        )

        first = await self.transport.send(message)
        second = await self.transport.send(message)

        self.assertTrue(first.accepted)
        self.assertEqual(first.platform_message_id, second.platform_message_id)

        lookup = await self.transport.lookup_delivery(
            account_id="acc-1",
            dedupe_key="run-1:reply",
        )
        self.assertTrue(lookup.found)
        self.assertEqual(lookup.platform_message_id, first.platform_message_id)

    async def test_capabilities_advertise_delivery_lookup(self) -> None:
        self.assertIn(
            TransportCapability.DELIVERY_LOOKUP,
            self.transport.capabilities,
        )


if __name__ == "__main__":
    unittest.main()
