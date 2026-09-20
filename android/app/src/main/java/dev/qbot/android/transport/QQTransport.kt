package dev.qbot.android.transport

import java.time.Instant

enum class TransportCapability {
    READ_TEXT,
    SEND_TEXT,
    SEND_IMAGE,
    READ_HISTORY,
    QUOTE_REPLY,
    GROUP_MESSAGE,
    SEND_FILE,
    REACTION,
    RECALL,
    DELIVERY_LOOKUP,
}

data class IncomingTransportEvent(
    val accountId: String,
    val conversationId: String,
    val senderId: String? = null,
    val platformMessageId: String? = null,
    val messageType: String = "private",
    val text: String? = null,
    val occurredAt: Instant,
    val metadata: Map<String, String> = emptyMap(),
)

data class OutgoingMessage(
    val accountId: String,
    val conversationId: String,
    val dedupeKey: String,
    val text: String,
    val replyToMessageId: String? = null,
)

enum class SendAvailability {
    READY,
    TEMPORARILY_UNAVAILABLE,
    UNSUPPORTED,
}

data class SendReadiness(
    val availability: SendAvailability,
    val reason: String? = null,
) {
    val ready: Boolean
        get() = availability == SendAvailability.READY
}

data class SendResult(
    val accepted: Boolean,
    val platformMessageId: String? = null,
    val uncertain: Boolean = false,
    val error: String? = null,
)

data class DeliveryLookupResult(
    val found: Boolean,
    val platformMessageId: String? = null,
)

interface QQTransport {
    val name: String
    val capabilities: Set<TransportCapability>

    suspend fun start()
    suspend fun stop()
    suspend fun receive(): IncomingTransportEvent
    suspend fun send(message: OutgoingMessage): SendResult

    suspend fun checkSendReadiness(
        message: OutgoingMessage,
    ): SendReadiness =
        if (TransportCapability.SEND_TEXT in capabilities) {
            SendReadiness(SendAvailability.READY)
        } else {
            SendReadiness(
                SendAvailability.UNSUPPORTED,
                "transport does not support text sends",
            )
        }

    suspend fun lookupDelivery(
        accountId: String,
        dedupeKey: String,
    ): DeliveryLookupResult = DeliveryLookupResult(found = false)
}
