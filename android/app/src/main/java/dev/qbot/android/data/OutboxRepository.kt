package dev.qbot.android.data

import androidx.room.withTransaction
import dev.qbot.android.data.db.JournalEntity
import dev.qbot.android.data.db.OutboxMessageEntity
import dev.qbot.android.data.db.QbotDatabase
import java.time.Clock
import java.time.Instant
import java.util.UUID
import org.json.JSONObject

class DuplicateOutboxEffect(
    message: String,
) : IllegalArgumentException(message)

class InvalidOutboxTransition(
    message: String,
) : IllegalArgumentException(message)

class ConcurrentOutboxTransition(
    message: String,
) : IllegalStateException(message)

class OutboxRepository(
    private val database: QbotDatabase,
    private val clock: Clock = Clock.systemUTC(),
    private val idFactory: () -> String = { UUID.randomUUID().toString() },
) {
    private val dao = database.qbotDao()

    suspend fun createText(
        runId: String,
        accountId: String,
        conversationId: String,
        dedupeKey: String,
        text: String,
        replyToMessageId: String? = null,
        writerEpoch: Long = 0,
    ): OutboxMessageEntity = database.withTransaction {
        val now = Instant.now(clock).toString()
        val outboxId = "out-" + idFactory()
        val record = OutboxMessageEntity(
            outboxId = outboxId,
            schemaVersion = "0.1.0",
            runId = runId,
            accountId = accountId,
            conversationId = conversationId,
            dedupeKey = dedupeKey,
            status = "PENDING",
            payloadKind = "TEXT",
            payloadText = text,
            contentRef = null,
            replyToMessageId = replyToMessageId,
            platformMessageId = null,
            transportAttempts = 0,
            lastError = null,
            writerEpoch = writerEpoch,
            createdAt = now,
            sentAt = null,
        )
        val inserted = dao.insertOutboxIfAbsent(record)
        if (inserted == -1L) {
            throw DuplicateOutboxEffect(
                "duplicate Outbox effect for account=" + accountId +
                    ", dedupeKey=" + dedupeKey,
            )
        }

        dao.insertJournal(
            JournalEntity(
                journalId = "journal-" + idFactory(),
                schemaVersion = "0.1.0",
                eventType = "OUTBOX_CREATED",
                actor = "SYSTEM",
                accountId = accountId,
                conversationId = conversationId,
                taskId = null,
                runId = runId,
                relatedId = outboxId,
                payloadJson = "{\"dedupe_key\":\"" +
                    jsonEscape(dedupeKey) + "\"}",
                occurredAt = now,
            ),
        )
        requireNotNull(dao.outbox(outboxId))
    }

    suspend fun load(outboxId: String): OutboxMessageEntity =
        requireNotNull(dao.outbox(outboxId)) {
            "unknown Outbox record: " + outboxId
        }

    suspend fun listForRun(runId: String): List<OutboxMessageEntity> =
        dao.outboxForRun(runId)

    suspend fun listByStatus(statuses: Set<String>): List<OutboxMessageEntity> =
        if (statuses.isEmpty()) {
            emptyList()
        } else {
            dao.outboxByStatus(statuses.toList())
        }

    suspend fun recoverInterruptedSends(): List<OutboxMessageEntity> {
        val interrupted = listByStatus(setOf("SENDING"))
        return interrupted.map { record ->
            transition(
                outboxId = record.outboxId,
                targetStatus = "SENDING_UNKNOWN",
                error = "process restarted while transport send was in flight",
            )
        }
    }

    suspend fun transition(
        outboxId: String,
        targetStatus: String,
        platformMessageId: String? = null,
        error: String? = null,
        incrementAttempt: Boolean = false,
        attemptTransportId: String? = null,
    ): OutboxMessageEntity = database.withTransaction {
        val current = requireNotNull(dao.outbox(outboxId)) {
            "unknown Outbox record: " + outboxId
        }
        val allowed = ALLOWED_TRANSITIONS[current.status].orEmpty()
        if (targetStatus !in allowed) {
            throw InvalidOutboxTransition(
                "illegal Outbox transition: " +
                    current.status + " -> " + targetStatus,
            )
        }

        val now = Instant.now(clock).toString()
        val changed = dao.transitionOutbox(
            outboxId = outboxId,
            expectedStatus = current.status,
            targetStatus = targetStatus,
            platformMessageId = platformMessageId,
            error = error,
            attemptDelta = if (incrementAttempt) 1 else 0,
            sentAt = if (targetStatus == "SENT") now else null,
        )
        if (changed != 1) {
            throw ConcurrentOutboxTransition(
                "Outbox changed concurrently while transitioning " +
                    outboxId + " from " + current.status +
                    " to " + targetStatus,
            )
        }

        if (targetStatus == "SENDING" && attemptTransportId != null) {
            dao.insertJournal(
                JournalEntity(
                    journalId = "journal-" + idFactory(),
                    schemaVersion = current.schemaVersion,
                    eventType = "SEND_STARTED",
                    actor = "TRANSPORT",
                    accountId = current.accountId,
                    conversationId = current.conversationId,
                    taskId = null,
                    runId = current.runId,
                    relatedId = outboxId,
                    payloadJson = JSONObject()
                        .put("transport_id", attemptTransportId)
                        .toString(),
                    occurredAt = now,
                ),
            )
        }

        val journalType = when (targetStatus) {
            "SENT" -> "MESSAGE_SENT"
            "SENDING_UNKNOWN" -> "SEND_UNKNOWN"
            else -> null
        }
        if (journalType != null) {
            dao.insertJournal(
                JournalEntity(
                    journalId = "journal-" + idFactory(),
                    schemaVersion = current.schemaVersion,
                    eventType = journalType,
                    actor = "TRANSPORT",
                    accountId = current.accountId,
                    conversationId = current.conversationId,
                    taskId = null,
                    runId = current.runId,
                    relatedId = outboxId,
                    payloadJson = if (platformMessageId == null) {
                        "{\"platform_message_id\":null}"
                    } else {
                        "{\"platform_message_id\":\"" +
                            jsonEscape(platformMessageId) + "\"}"
                    },
                    occurredAt = now,
                ),
            )
        }

        requireNotNull(dao.outbox(outboxId))
    }

    suspend fun lastAttemptTransportId(
        outboxId: String,
    ): String? {
        val record = dao.latestJournalForRelated(
            relatedId = outboxId,
            eventType = "SEND_STARTED",
        ) ?: return null

        return runCatching {
            JSONObject(record.payloadJson)
                .optString("transport_id")
                .takeIf { it.isNotBlank() }
        }.getOrNull()
    }

    companion object {
        private val ALLOWED_TRANSITIONS: Map<String, Set<String>> = mapOf(
            "PENDING" to setOf("SENDING", "CANCELLED"),
            "SENDING" to setOf("SENT", "FAILED", "SENDING_UNKNOWN"),
            "SENDING_UNKNOWN" to setOf("SENT", "FAILED", "SENDING"),
            "FAILED" to setOf("PENDING", "CANCELLED"),
            "SENT" to emptySet(),
            "CANCELLED" to emptySet(),
        )

        private fun jsonEscape(value: String): String =
            buildString {
                value.forEach { char ->
                    when (char) {
                        '\\' -> append("\\\\")
                        '"' -> append("\\\"")
                        '\n' -> append("\\n")
                        '\r' -> append("\\r")
                        '\t' -> append("\\t")
                        else -> append(char)
                    }
                }
            }
    }
}
