package dev.qbot.android.data

import androidx.room.withTransaction
import dev.qbot.android.data.db.JournalEntity
import dev.qbot.android.data.db.MemoryEntity
import dev.qbot.android.data.db.QbotDatabase
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

private val MEMORY_STATES = setOf(
    "CANDIDATE",
    "PROMOTED",
    "SUPERSEDED",
    "REJECTED",
    "EXPIRED",
)

private val MEMORY_SCOPES = setOf(
    "SYSTEM_POLICY",
    "USER_PERSONA",
    "CONTACT_PROFILE",
    "CONVERSATION_MEMORY",
    "TASK_MEMORY",
)

private val SOURCE_TYPES = setOf(
    "SYSTEM",
    "USER_SELF",
    "CONTACT",
    "AGENT_INFERENCE",
    "IMPORT",
)

private val ALLOWED_SCOPES_BY_SOURCE = mapOf(
    "SYSTEM" to MEMORY_SCOPES,
    "USER_SELF" to setOf(
        "USER_PERSONA",
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    ),
    "CONTACT" to setOf(
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    ),
    "AGENT_INFERENCE" to setOf(
        "USER_PERSONA",
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    ),
    "IMPORT" to setOf(
        "USER_PERSONA",
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    ),
)

class MemoryPolicyError(message: String) : IllegalArgumentException(message)

class MemoryStateError(message: String) : IllegalStateException(message)

data class MemoryRecord(
    val memoryId: String,
    val schemaVersion: String,
    val state: String,
    val scope: String,
    val ownerId: String?,
    val conversationId: String?,
    val taskId: String?,
    val content: String,
    val entities: List<String>,
    val importance: Double?,
    val trust: Double,
    val confidence: Double?,
    val sourceType: String,
    val sourceMessageId: String?,
    val sourceEventId: String?,
    val validFrom: String?,
    val validTo: String?,
    val supersedes: String?,
    val createdAt: String,
)

class MemoryRepository(
    private val database: QbotDatabase,
    private val clock: Clock = Clock.systemUTC(),
) {
    private val dao = database.qbotDao()

    suspend fun createCandidate(
        scope: String,
        content: String,
        sourceType: String,
        trust: Double,
        ownerId: String? = null,
        conversationId: String? = null,
        taskId: String? = null,
        entities: List<String> = emptyList(),
        importance: Double? = null,
        confidence: Double? = null,
        sourceMessageId: String? = null,
        sourceEventId: String? = null,
        validFrom: String? = null,
        validTo: String? = null,
        supersedes: String? = null,
    ): MemoryRecord {
        val normalizedScope = scope.trim().uppercase()
        val normalizedSource = sourceType.trim().uppercase()
        val normalizedContent = content.trim()
        if (normalizedContent.isEmpty()) {
            throw MemoryPolicyError("memory content must not be blank")
        }

        validateScopeForSource(normalizedScope, normalizedSource)
        validateScopeIdentity(
            scope = normalizedScope,
            ownerId = ownerId,
            conversationId = conversationId,
            taskId = taskId,
        )
        if (
            normalizedSource == "CONTACT" &&
            sourceMessageId == null &&
            sourceEventId == null
        ) {
            throw MemoryPolicyError(
                "CONTACT memory requires source_message_id or source_event_id",
            )
        }

        val normalizedTrust = score(trust, "trust")!!
        val normalizedImportance = score(importance, "importance")
        val normalizedConfidence = score(confidence, "confidence")
        val normalizedEntities = cleanEntities(entities)
        val createdAt = now()
        val memoryId = candidateId(
            scope = normalizedScope,
            ownerId = ownerId,
            conversationId = conversationId,
            taskId = taskId,
            content = normalizedContent,
            sourceType = normalizedSource,
            sourceMessageId = sourceMessageId,
            sourceEventId = sourceEventId,
        )

        return database.withTransaction {
            dao.memory(memoryId)?.let { return@withTransaction record(it) }

            if (supersedes != null) {
                val target = dao.memory(supersedes)
                    ?: throw MemoryPolicyError(
                        "superseded memory does not exist: $supersedes",
                    )
                assertSameMemoryDomain(
                    scope = normalizedScope,
                    ownerId = ownerId,
                    conversationId = conversationId,
                    taskId = taskId,
                    target = target,
                )
            }

            val entity = MemoryEntity(
                memoryId = memoryId,
                schemaVersion = "0.1.0",
                state = "CANDIDATE",
                scope = normalizedScope,
                ownerId = ownerId,
                conversationId = conversationId,
                taskId = taskId,
                content = normalizedContent,
                entitiesJson = encodeEntities(normalizedEntities),
                importance = normalizedImportance,
                trust = normalizedTrust,
                confidence = normalizedConfidence,
                sourceType = normalizedSource,
                sourceMessageId = sourceMessageId,
                sourceEventId = sourceEventId,
                validFrom = validFrom,
                validTo = validTo,
                supersedes = supersedes,
                createdAt = createdAt,
            )
            val inserted = dao.insertMemoryIfAbsent(entity)
            if (inserted == -1L) {
                val existing = dao.memory(memoryId)
                    ?: throw MemoryStateError(
                        "memory $memoryId conflicted but cannot be reloaded",
                    )
                return@withTransaction record(existing)
            }

            dao.insertJournal(
                journal(
                    eventType = "MEMORY_CANDIDATE_CREATED",
                    actor = sourceActor(normalizedSource),
                    memory = entity,
                    payload = JSONObject()
                        .put("scope", normalizedScope)
                        .put("source_type", normalizedSource)
                        .put(
                            "supersedes",
                            supersedes ?: JSONObject.NULL,
                        )
                        .toString(),
                    occurredAt = createdAt,
                ),
            )
            record(entity)
        }
    }

    suspend fun promote(memoryId: String): MemoryRecord =
        database.withTransaction {
            val candidate = dao.memory(memoryId)
                ?: throw NoSuchElementException("unknown memory: $memoryId")
            if (candidate.state != "CANDIDATE") {
                throw MemoryStateError(
                    "memory $memoryId must be CANDIDATE, got ${candidate.state}",
                )
            }

            validateScopeForSource(candidate.scope, candidate.sourceType)

            candidate.supersedes?.let { supersededId ->
                val target = dao.memory(supersededId)
                    ?: throw MemoryPolicyError(
                        "superseded memory does not exist: $supersededId",
                    )
                if (target.state != "PROMOTED") {
                    throw MemoryStateError(
                        "superseded memory $supersededId must be PROMOTED, " +
                            "got ${target.state}",
                    )
                }
                assertSameMemoryDomain(candidate, target)
                if (
                    dao.transitionMemory(
                        supersededId,
                        expectedState = "PROMOTED",
                        targetState = "SUPERSEDED",
                    ) != 1
                ) {
                    throw MemoryStateError(
                        "superseded memory $supersededId changed during promotion",
                    )
                }
            }

            if (
                dao.transitionMemory(
                    memoryId,
                    expectedState = "CANDIDATE",
                    targetState = "PROMOTED",
                ) != 1
            ) {
                throw MemoryStateError(
                    "memory $memoryId changed during promotion",
                )
            }

            val promoted = dao.memory(memoryId)
                ?: throw MemoryStateError("memory $memoryId disappeared")
            val occurredAt = now()
            dao.insertJournal(
                journal(
                    eventType = "MEMORY_PROMOTED",
                    actor = "SYSTEM",
                    memory = promoted,
                    payload = JSONObject()
                        .put("scope", promoted.scope)
                        .put("source_type", promoted.sourceType)
                        .put(
                            "supersedes",
                            promoted.supersedes ?: JSONObject.NULL,
                        )
                        .toString(),
                    occurredAt = occurredAt,
                ),
            )
            record(promoted)
        }

    suspend fun reject(memoryId: String): MemoryRecord =
        database.withTransaction {
            val current = dao.memory(memoryId)
                ?: throw NoSuchElementException("unknown memory: $memoryId")
            if (current.state != "CANDIDATE") {
                throw MemoryStateError(
                    "memory $memoryId must be CANDIDATE, got ${current.state}",
                )
            }
            if (
                dao.transitionMemory(
                    memoryId,
                    expectedState = "CANDIDATE",
                    targetState = "REJECTED",
                ) != 1
            ) {
                throw MemoryStateError(
                    "memory $memoryId changed during rejection",
                )
            }
            record(
                dao.memory(memoryId)
                    ?: throw MemoryStateError("memory $memoryId disappeared"),
            )
        }

    suspend fun load(memoryId: String): MemoryRecord? =
        dao.memory(memoryId)?.let(::record)

    suspend fun listByState(
        state: String,
        conversationId: String? = null,
        taskId: String? = null,
    ): List<MemoryRecord> {
        val normalized = state.trim().uppercase()
        if (normalized !in MEMORY_STATES) {
            throw MemoryPolicyError("unsupported memory state: $normalized")
        }
        return dao.memoriesByState(
            normalized,
            conversationId,
            taskId,
        ).map(::record)
    }

    private fun validateScopeForSource(scope: String, sourceType: String) {
        if (scope !in MEMORY_SCOPES) {
            throw MemoryPolicyError("unsupported memory scope: $scope")
        }
        if (sourceType !in SOURCE_TYPES) {
            throw MemoryPolicyError(
                "unsupported provenance source_type: $sourceType",
            )
        }
        if (scope !in ALLOWED_SCOPES_BY_SOURCE.getValue(sourceType)) {
            throw MemoryPolicyError(
                "$sourceType cannot create memory for scope $scope",
            )
        }
    }

    private fun validateScopeIdentity(
        scope: String,
        ownerId: String?,
        conversationId: String?,
        taskId: String?,
    ) {
        if (scope == "CONTACT_PROFILE" && ownerId.isNullOrBlank()) {
            throw MemoryPolicyError(
                "CONTACT_PROFILE memory requires owner_id",
            )
        }
        if (
            scope == "CONVERSATION_MEMORY" &&
            conversationId.isNullOrBlank()
        ) {
            throw MemoryPolicyError(
                "CONVERSATION_MEMORY requires conversation_id",
            )
        }
        if (scope == "TASK_MEMORY" && taskId.isNullOrBlank()) {
            throw MemoryPolicyError("TASK_MEMORY requires task_id")
        }
    }

    private fun assertSameMemoryDomain(
        candidate: MemoryEntity,
        target: MemoryEntity,
    ) {
        assertSameMemoryDomain(
            scope = candidate.scope,
            ownerId = candidate.ownerId,
            conversationId = candidate.conversationId,
            taskId = candidate.taskId,
            target = target,
        )
    }

    private fun assertSameMemoryDomain(
        scope: String,
        ownerId: String?,
        conversationId: String?,
        taskId: String?,
        target: MemoryEntity,
    ) {
        if (
            scope != target.scope ||
            ownerId != target.ownerId ||
            conversationId != target.conversationId ||
            taskId != target.taskId
        ) {
            throw MemoryPolicyError(
                "supersedes target must have the same memory domain",
            )
        }
    }

    private fun candidateId(
        scope: String,
        ownerId: String?,
        conversationId: String?,
        taskId: String?,
        content: String,
        sourceType: String,
        sourceMessageId: String?,
        sourceEventId: String?,
    ): String {
        if (sourceMessageId == null && sourceEventId == null) {
            return "mem-${UUID.randomUUID()}"
        }
        val material = listOf(
            sourceType,
            sourceEventId.orEmpty(),
            sourceMessageId.orEmpty(),
            scope,
            ownerId.orEmpty(),
            conversationId.orEmpty(),
            taskId.orEmpty(),
            content,
        ).joinToString("\u001f")
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(material.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte ->
                "%02x".format(byte.toInt() and 0xff)
            }
        return "mem-${digest.take(32)}"
    }

    private fun score(value: Double?, name: String): Double? {
        if (value == null) return null
        if (value !in 0.0..1.0) {
            throw MemoryPolicyError("$name must be between 0 and 1")
        }
        return value
    }

    private fun cleanEntities(values: List<String>): List<String> {
        val seen = linkedSetOf<String>()
        values.forEach { raw ->
            val value = raw.trim()
            if (value.isNotEmpty()) seen += value
        }
        return seen.toList()
    }

    private fun encodeEntities(values: List<String>): String {
        val array = JSONArray()
        values.forEach(array::put)
        return array.toString()
    }

    private fun decodeEntities(value: String): List<String> {
        val array = JSONArray(value)
        return buildList {
            for (index in 0 until array.length()) {
                add(array.getString(index))
            }
        }
    }

    private fun sourceActor(sourceType: String): String =
        when (sourceType) {
            "SYSTEM", "IMPORT" -> "SYSTEM"
            "USER_SELF" -> "USER"
            "CONTACT" -> "CONTACT"
            "AGENT_INFERENCE" -> "AGENT"
            else -> error("unsupported source type: $sourceType")
        }

    private fun journal(
        eventType: String,
        actor: String,
        memory: MemoryEntity,
        payload: String,
        occurredAt: String,
    ) = JournalEntity(
        journalId = "journal-${UUID.randomUUID()}",
        schemaVersion = "0.1.0",
        eventType = eventType,
        actor = actor,
        accountId = null,
        conversationId = memory.conversationId,
        taskId = memory.taskId,
        runId = null,
        relatedId = memory.memoryId,
        payloadJson = payload,
        occurredAt = occurredAt,
    )

    private fun record(entity: MemoryEntity) = MemoryRecord(
        memoryId = entity.memoryId,
        schemaVersion = entity.schemaVersion,
        state = entity.state,
        scope = entity.scope,
        ownerId = entity.ownerId,
        conversationId = entity.conversationId,
        taskId = entity.taskId,
        content = entity.content,
        entities = decodeEntities(entity.entitiesJson),
        importance = entity.importance,
        trust = entity.trust,
        confidence = entity.confidence,
        sourceType = entity.sourceType,
        sourceMessageId = entity.sourceMessageId,
        sourceEventId = entity.sourceEventId,
        validFrom = entity.validFrom,
        validTo = entity.validTo,
        supersedes = entity.supersedes,
        createdAt = entity.createdAt,
    )

    private fun now(): String = Instant.now(clock).toString()
}
