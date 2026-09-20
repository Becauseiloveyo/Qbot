package dev.qbot.android.transport.accessibility

import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.SendAvailability
import dev.qbot.android.transport.TransportCapability
import dev.qbot.android.transport.routing.AdapterHealth
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessibilityQQTransportTest {
    @Test
    fun doesNotAdvertiseSendUntilConnectedSessionIsRecognized() = runTest {
        val transport = AccessibilityQQTransport()

        assertFalse(TransportCapability.SEND_TEXT in transport.capabilities)
        assertEquals(AdapterHealth.STOPPED, transport.snapshot().health)

        transport.start()
        assertEquals(
            AdapterHealth.PERMISSION_REQUIRED,
            transport.snapshot().health,
        )

        transport.onServiceConnected()
        assertEquals(AdapterHealth.DEGRADED, transport.snapshot().health)
        assertFalse(TransportCapability.SEND_TEXT in transport.capabilities)

        transport.updateReplySession(
            ProbeSession(
                accountId = "acc-1",
                conversationId = "conv-1",
            ),
        )

        assertEquals(AdapterHealth.READY, transport.snapshot().health)
        assertTrue(TransportCapability.SEND_TEXT in transport.capabilities)
    }

    @Test
    fun serviceDisconnectStopsTransportAndDropsCapability() = runTest {
        val transport = AccessibilityQQTransport()
        transport.start()
        transport.onServiceConnected()
        transport.updateReplySession(
            ProbeSession(
                accountId = "acc-1",
                conversationId = "conv-1",
            ),
        )

        assertEquals(AdapterHealth.READY, transport.snapshot().health)
        assertTrue(TransportCapability.SEND_TEXT in transport.capabilities)

        transport.onServiceDisconnected()

        assertEquals(AdapterHealth.STOPPED, transport.snapshot().health)
        assertFalse(TransportCapability.SEND_TEXT in transport.capabilities)
    }

    @Test
    fun exactConversationCanSendButDifferentConversationIsRejected() = runTest {
        val session = ProbeSession(
            accountId = "acc-1",
            conversationId = "conv-1",
        )
        val transport = AccessibilityQQTransport()
        transport.start()
        transport.onServiceConnected()
        transport.updateReplySession(session)

        val mismatch = transport.checkSendReadiness(
            message(conversationId = "conv-2"),
        )
        assertEquals(SendAvailability.UNSUPPORTED, mismatch.availability)

        val result = transport.send(
            message(conversationId = "conv-1"),
        )
        assertTrue(result.accepted)
        assertEquals(1, session.sendCalls)
        assertEquals("hello", session.lastText)
    }

    @Test
    fun staleSessionFailsClosedAndDropsSendCapability() = runTest {
        val session = ProbeSession(
            accountId = "acc-1",
            conversationId = "conv-1",
        )
        val transport = AccessibilityQQTransport()
        transport.start()
        transport.onServiceConnected()
        transport.updateReplySession(session)

        session.valid = false

        val readiness = transport.checkSendReadiness(
            message(conversationId = "conv-1"),
        )

        assertEquals(
            SendAvailability.TEMPORARILY_UNAVAILABLE,
            readiness.availability,
        )
        assertFalse(TransportCapability.SEND_TEXT in transport.capabilities)
        assertEquals(0, session.sendCalls)
    }

    private fun message(
        conversationId: String,
    ): OutgoingMessage =
        OutgoingMessage(
            accountId = "acc-1",
            conversationId = conversationId,
            dedupeKey = "accessibility-dedupe",
            text = "hello",
        )

    private class ProbeSession(
        override val accountId: String,
        override val conversationId: String,
    ) : AccessibilityReplySession {
        var valid: Boolean = true
        var sendCalls: Int = 0
        var lastText: String? = null

        override fun isValid(): Boolean = valid

        override suspend fun sendText(
            text: String,
        ): AccessibilityReplyResult {
            sendCalls += 1
            lastText = text
            return AccessibilityReplyResult(
                actionAccepted = true,
            )
        }
    }
}
