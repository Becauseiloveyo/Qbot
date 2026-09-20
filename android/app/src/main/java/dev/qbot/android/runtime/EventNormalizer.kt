package dev.qbot.android.runtime

import dev.qbot.android.domain.NormalizedEvent
import dev.qbot.android.transport.IncomingTransportEvent
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.util.UUID

class EventNormalizer(
    private val transportName: String,
    private val platform: String = "qq",
    private val clock: Clock = Clock.systemUTC(),
    private val idFactory: () -> String = { UUID.randomUUID().toString() },
) {
    fun normalize(event: IncomingTransportEvent): NormalizedEvent {
        val identity = event.platformMessageId ?: listOf(
            event.senderId.orEmpty(),
            event.messageType,
            event.text.orEmpty(),
            event.occurredAt.toString(),
        ).joinToString("|")

        val material = listOf(
            platform,
            event.accountId,
            event.conversationId,
            identity,
        ).joinToString("\u001f")

        return NormalizedEvent(
            eventId = "evt-" + idFactory(),
            fingerprint = sha256(material),
            platform = platform,
            transport = transportName,
            accountId = event.accountId,
            conversationId = event.conversationId,
            senderId = event.senderId,
            platformMessageId = event.platformMessageId,
            messageType = event.messageType,
            text = event.text,
            occurredAt = event.occurredAt.toString(),
            receivedAt = Instant.now(clock).toString(),
            metadata = event.metadata,
        )
    }

    private fun sha256(value: String): String =
        MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
}
