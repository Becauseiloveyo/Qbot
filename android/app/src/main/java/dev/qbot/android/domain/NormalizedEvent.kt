package dev.qbot.android.domain

data class NormalizedEvent(
    val schemaVersion: String = "0.1.0",
    val eventId: String,
    val fingerprint: String,
    val platform: String,
    val transport: String?,
    val accountId: String,
    val conversationId: String,
    val senderId: String?,
    val platformMessageId: String?,
    val eventType: String = "MESSAGE_RECEIVED",
    val messageType: String?,
    val text: String?,
    val contentRef: String? = null,
    val replyToMessageId: String? = null,
    val occurredAt: String,
    val receivedAt: String,
    val rawRef: String? = null,
    val metadata: Map<String, String> = emptyMap(),
)
