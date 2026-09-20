package dev.qbot.android.runtime

import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.data.db.OutboxMessageEntity
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.TransportCapability
import kotlinx.coroutines.CancellationException

class SendExecutor(
    private val outbox: OutboxRepository,
    private val transport: QQTransport,
    private val attemptTransportId: String = transport.name,
) {
    suspend fun send(outboxId: String): OutboxMessageEntity {
        val record = outbox.load(outboxId)
        require(record.status == "PENDING") {
            "send requires PENDING Outbox record, got " + record.status
        }

        val sending = outbox.transition(
            outboxId = outboxId,
            targetStatus = "SENDING",
            incrementAttempt = true,
            attemptTransportId = attemptTransportId,
        )
        val message = OutgoingMessage(
            accountId = sending.accountId,
            conversationId = sending.conversationId,
            dedupeKey = sending.dedupeKey,
            text = sending.payloadText.orEmpty(),
            replyToMessageId = sending.replyToMessageId,
        )

        val result = try {
            transport.send(message)
        } catch (cancelled: CancellationException) {
            outbox.transition(
                outboxId = outboxId,
                targetStatus = "SENDING_UNKNOWN",
                error = "send coroutine was cancelled after entering SENDING",
            )
            throw cancelled
        } catch (failure: Exception) {
            return outbox.transition(
                outboxId = outboxId,
                targetStatus = "SENDING_UNKNOWN",
                error = failure.message ?: failure::class.java.simpleName,
            )
        }

        if (result.uncertain) {
            return outbox.transition(
                outboxId = outboxId,
                targetStatus = "SENDING_UNKNOWN",
                platformMessageId = result.platformMessageId,
                error = result.error,
            )
        }

        if (result.accepted) {
            return outbox.transition(
                outboxId = outboxId,
                targetStatus = "SENT",
                platformMessageId = result.platformMessageId,
            )
        }

        return outbox.transition(
            outboxId = outboxId,
            targetStatus = "FAILED",
            error = result.error ?: "transport rejected message",
        )
    }

    suspend fun reconcile(outboxId: String): OutboxMessageEntity {
        val record = outbox.load(outboxId)
        if (record.status != "SENDING_UNKNOWN") {
            return record
        }
        if (
            TransportCapability.DELIVERY_LOOKUP !in transport.capabilities
        ) {
            return record
        }

        val result = transport.lookupDelivery(
            accountId = record.accountId,
            dedupeKey = record.dedupeKey,
        )
        if (!result.found) {
            return record
        }

        return outbox.transition(
            outboxId = outboxId,
            targetStatus = "SENT",
            platformMessageId = result.platformMessageId,
        )
    }
}
