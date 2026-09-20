package dev.qbot.android.data

import androidx.room.withTransaction
import dev.qbot.android.data.db.AgentRunEntity
import dev.qbot.android.data.db.InboundEventEntity
import dev.qbot.android.data.db.JournalEntity
import dev.qbot.android.data.db.QbotDatabase
import dev.qbot.android.domain.NormalizedEvent
import java.util.UUID

data class AdmissionResult(
    val isNew: Boolean,
    val eventId: String,
    val runId: String,
)

class InboundAdmissionRepository(
    private val database: QbotDatabase,
    private val idFactory: () -> String = { UUID.randomUUID().toString() },
) {
    private val dao = database.qbotDao()

    suspend fun admit(event: NormalizedEvent): AdmissionResult =
        database.withTransaction {
            val rowId = dao.insertInboundIfAbsent(event.toEntity())
            if (rowId == -1L) {
                val existing = requireNotNull(
                    dao.inboundByFingerprint(event.fingerprint),
                ) {
                    "duplicate fingerprint disappeared inside admission transaction"
                }
                val run = requireNotNull(
                    dao.agentRunByTriggerEvent(existing.eventId),
                ) {
                    "admitted inbound event has no primary AgentRun"
                }
                return@withTransaction AdmissionResult(
                    isNew = false,
                    eventId = existing.eventId,
                    runId = run.runId,
                )
            }

            val runId = "run-" + idFactory()
            dao.insertJournal(
                JournalEntity(
                    journalId = "journal-" + idFactory(),
                    schemaVersion = event.schemaVersion,
                    eventType = "MESSAGE_RECEIVED",
                    actor = "TRANSPORT",
                    accountId = event.accountId,
                    conversationId = event.conversationId,
                    taskId = null,
                    runId = null,
                    relatedId = event.eventId,
                    payloadJson = "{}",
                    occurredAt = event.receivedAt,
                ),
            )
            dao.insertAgentRun(
                AgentRunEntity(
                    runId = runId,
                    schemaVersion = event.schemaVersion,
                    conversationId = event.conversationId,
                    triggerEventId = event.eventId,
                    taskId = null,
                    status = "CREATED",
                    modelProfile = null,
                    writerEpoch = 0,
                    createdAt = event.receivedAt,
                    updatedAt = event.receivedAt,
                ),
            )
            dao.insertJournal(
                JournalEntity(
                    journalId = "journal-" + idFactory(),
                    schemaVersion = event.schemaVersion,
                    eventType = "RUN_CREATED",
                    actor = "SYSTEM",
                    accountId = event.accountId,
                    conversationId = event.conversationId,
                    taskId = null,
                    runId = runId,
                    relatedId = event.eventId,
                    payloadJson = "{}",
                    occurredAt = event.receivedAt,
                ),
            )

            AdmissionResult(
                isNew = true,
                eventId = event.eventId,
                runId = runId,
            )
        }

    private fun NormalizedEvent.toEntity(): InboundEventEntity =
        InboundEventEntity(
            eventId = eventId,
            fingerprint = fingerprint,
            schemaVersion = schemaVersion,
            platform = platform,
            transport = transport,
            accountId = accountId,
            conversationId = conversationId,
            senderId = senderId,
            platformMessageId = platformMessageId,
            eventType = eventType,
            messageType = messageType,
            text = text,
            contentRef = contentRef,
            replyToMessageId = replyToMessageId,
            occurredAt = occurredAt,
            receivedAt = receivedAt,
            rawRef = rawRef,
            metadataJson = metadataJson(metadata),
        )

    private fun metadataJson(metadata: Map<String, String>): String =
        metadata.toSortedMap()
            .entries
            .joinToString(
                prefix = "{",
                postfix = "}",
                separator = ",",
            ) { (key, value) ->
                "\"" + jsonEscape(key) + "\":\"" + jsonEscape(value) + "\""
            }

    private fun jsonEscape(value: String): String = buildString {
        value.forEach { char ->
            when (char) {
                '\\' -> append("\\\\")
                '"' -> append("\\\"")
                '\b' -> append("\\b")
                '\u000C' -> append("\\f")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> {
                    if (char.code < 0x20) {
                        append("\\u")
                        append(char.code.toString(16).padStart(4, '0'))
                    } else {
                        append(char)
                    }
                }
            }
        }
    }
}
