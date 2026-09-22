package dev.qbot.android.data

import androidx.room.withTransaction
import dev.qbot.android.data.db.ConversationSummaryEntity
import dev.qbot.android.data.db.InboundEventEntity
import dev.qbot.android.data.db.JournalEntity
import dev.qbot.android.data.db.QbotDatabase
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

data class MemoryCandidateProposal(
    val scope: String,
    val content: String,
    val entities: List<String> = emptyList(),
    val importance: Double? = null,
    val confidence: Double? = null,
)

data class MemoryExtractionRequest(
    val eventId: String,
    val conversationId: String,
    val senderId: String?,
    val text: String,
)

interface MemoryCandidateExtractor {
    val providerName: String

    val modelName: String?
        get() = null

    suspend fun extract(
        request: MemoryExtractionRequest,
    ): List<MemoryCandidateProposal>
}

data class RollingSummaryMessage(
    val eventId: String,
    val senderId: String?,
    val text: String,
    val receivedAt: String,
)

data class RollingSummaryRequest(
    val conversationId: String,
    val previousSummary: String?,
    val messages: List<RollingSummaryMessage>,
)

interface RollingSummarizer {
    val providerName: String

    val modelName: String?
        get() = null

    suspend fun summarize(
        request: RollingSummaryRequest,
    ): String
}

data class MemoryMaintenanceReport(
    val eventId: String,
    val extractionStatus: String,
    val candidateIds: List<String>,
    val summaryStatus: String,
    val summaryUpdated: Boolean,
    val errorTypes: List<String> = emptyList(),
)

private data class BoundCandidate(
    val scope: String,
    val content: String,
    val ownerId: String?,
    val conversationId: String?,
    val taskId: String?,
    val entities: List<String>,
    val importance: Double?,
    val confidence: Double?,
)

class MemoryMaintenanceEngine(
    private val database: QbotDatabase,
    private val extractor: MemoryCandidateExtractor? = null,
    private val summarizer: RollingSummarizer? = null,
    private val contactCandidateTrust: Double = 0.25,
    private val summaryEventLimit: Int = 24,
    private val maxCandidates: Int = 8,
    private val clock: Clock = Clock.systemUTC(),
) {
    private val dao = database.qbotDao()
    private val memory = MemoryRepository(database, clock)

    init {
        require(contactCandidateTrust in 0.0..1.0) {
            "contactCandidateTrust must be between 0 and 1"
        }
        require(summaryEventLimit in 1..200) {
            "summaryEventLimit must be between 1 and 200"
        }
        require(maxCandidates in 1..32) {
            "maxCandidates must be between 1 and 32"
        }
    }

    suspend fun processEvent(eventId: String): MemoryMaintenanceReport {
        val event = requireNotNull(dao.inboundById(eventId)) {
            "unknown inbound event: $eventId"
        }
        val errors = mutableListOf<String>()

        var extractionStatus = "SKIPPED"
        var candidateIds = emptyList<String>()
        if (
            event.eventType == "MESSAGE_RECEIVED" &&
            !event.text.isNullOrBlank()
        ) {
            try {
                val extraction = extract(event)
                extractionStatus = extraction.first
                candidateIds = extraction.second
            } catch (error: Exception) {
                extractionStatus = "FAILED"
                errors += error::class.java.simpleName
            }
        }

        var summaryStatus = "SKIPPED"
        var summaryUpdated = false
        try {
            val summary = summarize(event.conversationId)
            summaryStatus = summary.first
            summaryUpdated = summary.second
        } catch (error: Exception) {
            summaryStatus = "FAILED"
            errors += error::class.java.simpleName
        }

        return MemoryMaintenanceReport(
            eventId = eventId,
            extractionStatus = extractionStatus,
            candidateIds = candidateIds,
            summaryStatus = summaryStatus,
            summaryUpdated = summaryUpdated,
            errorTypes = errors,
        )
    }

    suspend fun catchUp(limit: Int = 64): List<MemoryMaintenanceReport> {
        require(limit in 1..1000) {
            "catch-up limit must be between 1 and 1000"
        }
        return dao.recentMessageEventsForMaintenance(limit)
            .asReversed()
            .map { event -> processEvent(event.eventId) }
    }

    private suspend fun extract(
        event: InboundEventEntity,
    ): Pair<String, List<String>> {
        if (
            dao.latestJournalForRelated(
                relatedId = event.eventId,
                eventType = "MEMORY_EXTRACTION_COMPLETED",
            ) != null
        ) {
            return "ALREADY_COMPLETED" to emptyList()
        }
        val provider = extractor ?: return "DISABLED" to emptyList()
        val text = event.text?.trim().orEmpty()
        if (text.isEmpty()) return "SKIPPED" to emptyList()

        val proposals = provider.extract(
            MemoryExtractionRequest(
                eventId = event.eventId,
                conversationId = event.conversationId,
                senderId = event.senderId,
                text = text,
            ),
        )
        require(proposals.size <= maxCandidates) {
            "memory extractor returned too many candidates"
        }

        val activeTaskId = dao.activeTask(event.conversationId)?.taskId
        val bound = proposals.map { proposal ->
            bindCandidate(
                proposal = proposal,
                event = event,
                activeTaskId = activeTaskId,
            )
        }

        val candidateIds = bound.map { candidate ->
            memory.createCandidate(
                scope = candidate.scope,
                content = candidate.content,
                sourceType = "CONTACT",
                trust = contactCandidateTrust,
                ownerId = candidate.ownerId,
                conversationId = candidate.conversationId,
                taskId = candidate.taskId,
                entities = candidate.entities,
                importance = candidate.importance,
                confidence = candidate.confidence,
                sourceMessageId = event.platformMessageId,
                sourceEventId = event.eventId,
            ).memoryId
        }

        dao.insertJournal(
            JournalEntity(
                journalId = "journal-${UUID.randomUUID()}",
                schemaVersion = "0.1.0",
                eventType = "MEMORY_EXTRACTION_COMPLETED",
                actor = "AGENT",
                accountId = event.accountId,
                conversationId = event.conversationId,
                taskId = activeTaskId,
                runId = null,
                relatedId = event.eventId,
                payloadJson = JSONObject()
                    .put(
                        "candidate_ids",
                        JSONArray(candidateIds),
                    )
                    .put("provider", provider.providerName)
                    .put(
                        "model",
                        provider.modelName ?: JSONObject.NULL,
                    )
                    .toString(),
                occurredAt = now(),
            ),
        )
        return "COMPLETED" to candidateIds
    }

    private fun bindCandidate(
        proposal: MemoryCandidateProposal,
        event: InboundEventEntity,
        activeTaskId: String?,
    ): BoundCandidate {
        val scope = proposal.scope.trim().uppercase()
        val content = proposal.content.trim()
        require(content.isNotEmpty() && content.length <= 2000) {
            "candidate content must contain 1..2000 characters"
        }
        validateScore(proposal.importance, "importance")
        validateScore(proposal.confidence, "confidence")
        val entities = proposal.entities
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .distinct()

        return when (scope) {
            "CONTACT_PROFILE" -> {
                val ownerId = requireNotNull(event.senderId) {
                    "CONTACT_PROFILE candidate requires durable sender_id"
                }
                BoundCandidate(
                    scope = scope,
                    content = content,
                    ownerId = ownerId,
                    conversationId = null,
                    taskId = null,
                    entities = entities,
                    importance = proposal.importance,
                    confidence = proposal.confidence,
                )
            }

            "CONVERSATION_MEMORY" ->
                BoundCandidate(
                    scope = scope,
                    content = content,
                    ownerId = null,
                    conversationId = event.conversationId,
                    taskId = null,
                    entities = entities,
                    importance = proposal.importance,
                    confidence = proposal.confidence,
                )

            "TASK_MEMORY" -> {
                val taskId = requireNotNull(activeTaskId) {
                    "TASK_MEMORY candidate requires active durable task"
                }
                BoundCandidate(
                    scope = scope,
                    content = content,
                    ownerId = null,
                    conversationId = null,
                    taskId = taskId,
                    entities = entities,
                    importance = proposal.importance,
                    confidence = proposal.confidence,
                )
            }

            else -> throw MemoryPolicyError(
                "background extractor cannot propose scope $scope",
            )
        }
    }

    private suspend fun summarize(
        conversationId: String,
    ): Pair<String, Boolean> {
        val messages = dao.recentMessageEvents(
            conversationId = conversationId,
            limit = summaryEventLimit,
        )
            .asReversed()
            .mapNotNull { event ->
                val text = event.text?.trim().orEmpty()
                if (text.isEmpty()) {
                    null
                } else {
                    RollingSummaryMessage(
                        eventId = event.eventId,
                        senderId = event.senderId,
                        text = text,
                        receivedAt = event.receivedAt,
                    )
                }
            }
        if (messages.isEmpty()) return "SKIPPED" to false

        val digest = sourceDigest(messages)
        val current = dao.conversationSummary(conversationId)
        if (current?.sourceDigest == digest) {
            return "UNCHANGED" to false
        }

        val provider = summarizer ?: return "DISABLED" to false
        val summary = provider.summarize(
            RollingSummaryRequest(
                conversationId = conversationId,
                previousSummary = current?.summary,
                messages = messages,
            ),
        ).trim()
        require(summary.isNotEmpty() && summary.length <= 8000) {
            "rolling summary must contain 1..8000 characters"
        }

        val updatedAt = now()
        database.withTransaction {
            dao.upsertConversationSummary(
                ConversationSummaryEntity(
                    conversationId = conversationId,
                    schemaVersion = "0.1.0",
                    summary = summary,
                    sourceDigest = digest,
                    sourceEventCount = messages.size,
                    sourceFromAt = messages.first().receivedAt,
                    sourceToAt = messages.last().receivedAt,
                    provider = provider.providerName,
                    model = provider.modelName,
                    updatedAt = updatedAt,
                ),
            )
            dao.insertJournal(
                JournalEntity(
                    journalId = "journal-${UUID.randomUUID()}",
                    schemaVersion = "0.1.0",
                    eventType = "ROLLING_SUMMARY_UPDATED",
                    actor = "AGENT",
                    accountId = null,
                    conversationId = conversationId,
                    taskId = null,
                    runId = null,
                    relatedId = conversationId,
                    payloadJson = JSONObject()
                        .put("source_digest", digest)
                        .put("source_event_count", messages.size)
                        .put("provider", provider.providerName)
                        .put(
                            "model",
                            provider.modelName ?: JSONObject.NULL,
                        )
                        .toString(),
                    occurredAt = updatedAt,
                ),
            )
        }
        return "UPDATED" to true
    }

    private fun sourceDigest(
        messages: List<RollingSummaryMessage>,
    ): String {
        val material = messages.joinToString("\u001e") { message ->
            listOf(
                message.eventId,
                message.senderId.orEmpty(),
                message.text,
                message.receivedAt,
            ).joinToString("\u001f")
        }
        return MessageDigest.getInstance("SHA-256")
            .digest(material.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte ->
                "%02x".format(byte.toInt() and 0xff)
            }
    }

    private fun validateScore(value: Double?, name: String) {
        if (value != null && value !in 0.0..1.0) {
            throw MemoryPolicyError(
                "$name must be between 0 and 1",
            )
        }
    }

    private fun now(): String = Instant.now(clock).toString()
}
