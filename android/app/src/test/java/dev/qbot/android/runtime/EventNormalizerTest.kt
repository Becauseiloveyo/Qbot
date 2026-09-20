package dev.qbot.android.runtime

import dev.qbot.android.transport.IncomingTransportEvent
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class EventNormalizerTest {
    private val clock = Clock.fixed(
        Instant.parse("2026-09-20T00:00:10Z"),
        ZoneOffset.UTC,
    )

    @Test
    fun samePlatformMessageIdentityHasSameFingerprintAcrossExecutions() {
        var nextId = 0
        val normalizer = EventNormalizer(
            transportName = "fake",
            clock = clock,
            idFactory = {
                nextId += 1
                "id-" + nextId
            },
        )
        val incoming = IncomingTransportEvent(
            accountId = "acc-1",
            conversationId = "private:2",
            senderId = "contact-2",
            platformMessageId = "message-42",
            text = "hello",
            occurredAt = Instant.parse("2026-09-20T00:00:00Z"),
        )

        val first = normalizer.normalize(incoming)
        val second = normalizer.normalize(incoming)

        assertNotEquals(first.eventId, second.eventId)
        assertEquals(first.fingerprint, second.fingerprint)
        assertEquals("2026-09-20T00:00:10Z", first.receivedAt)
        assertEquals(64, first.fingerprint.length)
    }

    @Test
    fun accountAndConversationArePartOfFingerprint() {
        val normalizer = EventNormalizer(
            transportName = "fake",
            clock = clock,
            idFactory = { "fixed" },
        )
        val base = IncomingTransportEvent(
            accountId = "acc-1",
            conversationId = "private:1",
            platformMessageId = "message-1",
            text = "hello",
            occurredAt = Instant.parse("2026-09-20T00:00:00Z"),
        )

        val first = normalizer.normalize(base)
        val otherConversation = normalizer.normalize(
            base.copy(conversationId = "private:2"),
        )

        assertNotEquals(first.fingerprint, otherConversation.fingerprint)
    }
}
