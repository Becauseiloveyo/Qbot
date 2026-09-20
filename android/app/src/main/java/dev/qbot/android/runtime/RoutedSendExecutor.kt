package dev.qbot.android.runtime

import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.data.db.OutboxMessageEntity
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.routing.TransportSelector

enum class RoutedSendOutcome {
    DEFERRED,
    SENT,
    FAILED,
    SEND_UNKNOWN,
}

data class RoutedSendResult(
    val outcome: RoutedSendOutcome,
    val adapterId: String?,
    val outbox: OutboxMessageEntity,
    val detail: String? = null,
)

class RoutedSendExecutor(
    private val outbox: OutboxRepository,
    private val selector: TransportSelector,
) {
    suspend fun send(outboxId: String): RoutedSendResult {
        val record = outbox.load(outboxId)
        require(record.status == "PENDING") {
            "routed send requires PENDING Outbox record, got " + record.status
        }

        val message = OutgoingMessage(
            accountId = record.accountId,
            conversationId = record.conversationId,
            dedupeKey = record.dedupeKey,
            text = record.payloadText.orEmpty(),
            replyToMessageId = record.replyToMessageId,
        )
        val selection = selector.selectTextSend(message)
            ?: return RoutedSendResult(
                outcome = RoutedSendOutcome.DEFERRED,
                adapterId = null,
                outbox = record,
                detail = "no adapter is currently ready for SEND_TEXT",
            )

        val selectedId = selection.snapshot.adapterId

        // From this point onward there is no transport fallback. SendExecutor
        // enters durable SENDING before invoking the selected adapter, so any
        // ambiguous result belongs to this one attempt and must be reconciled
        // rather than replayed through another adapter.
        val sent = SendExecutor(
            outbox = outbox,
            transport = selection.binding.transport,
        ).send(outboxId)

        return when (sent.status) {
            "SENT" -> RoutedSendResult(
                outcome = RoutedSendOutcome.SENT,
                adapterId = selectedId,
                outbox = sent,
            )

            "SENDING_UNKNOWN" -> RoutedSendResult(
                outcome = RoutedSendOutcome.SEND_UNKNOWN,
                adapterId = selectedId,
                outbox = sent,
                detail = sent.lastError,
            )

            else -> RoutedSendResult(
                outcome = RoutedSendOutcome.FAILED,
                adapterId = selectedId,
                outbox = sent,
                detail = sent.lastError,
            )
        }
    }
}
