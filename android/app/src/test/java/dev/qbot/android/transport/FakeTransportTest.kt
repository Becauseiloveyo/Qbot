package dev.qbot.android.transport

import java.time.Instant
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FakeTransportTest {
    @Test
    fun sameDedupeKeyProducesOneLogicalDelivery() = runTest {
        val transport = FakeTransport()
        transport.start()

        val message = OutgoingMessage(
            accountId = "acc-1",
            conversationId = "private:1",
            dedupeKey = "run-1:primary-reply",
            text = "hello",
        )
        val first = transport.send(message)
        val second = transport.send(message)

        assertTrue(first.accepted)
        assertEquals(first.platformMessageId, second.platformMessageId)

        val lookup = transport.lookupDelivery(
            accountId = "acc-1",
            dedupeKey = message.dedupeKey,
        )
        assertTrue(lookup.found)
        assertEquals(first.platformMessageId, lookup.platformMessageId)

        transport.stop()
    }

    @Test
    fun injectedEventCanBeReceivedAfterStart() = runTest {
        val transport = FakeTransport()
        val event = IncomingTransportEvent(
            accountId = "acc-1",
            conversationId = "private:2",
            platformMessageId = "msg-1",
            text = "hi",
            occurredAt = Instant.parse("2026-09-20T00:00:00Z"),
        )

        transport.inject(event)
        transport.start()
        assertEquals(event, transport.receive())
        transport.stop()

        assertFalse(
            TransportCapability.SEND_IMAGE in transport.capabilities,
        )
    }
}
