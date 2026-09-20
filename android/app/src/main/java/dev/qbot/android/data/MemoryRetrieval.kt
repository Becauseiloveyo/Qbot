package dev.qbot.android.data

import dev.qbot.android.data.db.MemoryEntity
import dev.qbot.android.data.db.QbotDatabase
import java.text.Normalizer
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.Locale
import org.json.JSONArray

private val RETRIEVAL_MEMORY_SCOPES = setOf(
    "SYSTEM_POLICY",
    "USER_PERSONA",
    "CONTACT_PROFILE",
    "CONVERSATION_MEMORY",
    "TASK_MEMORY",
)

private val OWNER_SCOPES = setOf(
    "USER_PERSONA",
    "CONTACT_PROFILE",
)

private val TERM_PATTERN = Regex(
    "[0-9a-z]+|[\\u3400-\\u4dbf\\u4e00-\\u9fff]+",
)

class MemoryRetrievalError(message: String) : IllegalArgumentException(message)

data class MemoryQuery(
    val scopes: List<String>,
    val text: String = "",
    val ownerId: String? = null,
    val conversationId: String? = null,
    val taskId: String? = null,
    val entities: List<String> = emptyList(),
    val minTrust: Double = 0.0,
    val limit: Int = 10,
)

data class MemoryScore(
    val totalPoints: Int,
    val keywordMilli: Int,
    val entityMilli: Int,
    val recencyMilli: Int,
    val importanceMilli: Int,
    val trustMilli: Int,
) {
    val total: Double
        get() = totalPoints / 100_000.0
}

data class MemoryHit(
    val record: MemoryRecord,
    val score: MemoryScore,
)

data class MemoryScoringWeights(
    val keyword: Int = 40,
    val entity: Int = 20,
    val recency: Int = 15,
    val importance: Int = 10,
    val trust: Int = 15,
) {
    fun validate() {
        val values = listOf(
            keyword,
            entity,
            recency,
            importance,
            trust,
        )
        if (values.any { it < 0 }) {
            throw MemoryRetrievalError(
                "memory scoring weights must be non-negative",
            )
        }
        if (values.sum() != 100) {
            throw MemoryRetrievalError(
                "memory scoring weights must sum to 100",
            )
        }
    }
}

class MemoryRetriever(
    database: QbotDatabase,
    private val weights: MemoryScoringWeights = MemoryScoringWeights(),
) {
    private val dao = database.qbotDao()

    init {
        weights.validate()
    }

    suspend fun retrieve(
        query: MemoryQuery,
        now: Instant = Instant.now(),
    ): List<MemoryHit> {
        val scopes = validateQuery(query)
        val terms = terms(query.text)
        val queryEntities = normalizedUnique(query.entities)
        val requiresRelevance = terms.isNotEmpty() || queryEntities.isNotEmpty()

        val hits = mutableListOf<MemoryHit>()
        for (entity in dao.memoriesByState("PROMOTED")) {
            if (entity.scope !in scopes) continue
            if (entity.trust < query.minTrust) continue
            if (!domainMatches(entity, query)) continue
            if (!isTemporallyValid(entity, now)) continue

            val record = record(entity)
            val keywordMilli = keywordScore(record, terms)
            val entityMilli = entityScore(record, queryEntities)
            if (
                requiresRelevance &&
                keywordMilli == 0 &&
                entityMilli == 0
            ) {
                continue
            }

            val recencyMilli = recencyScore(record, now)
            val importanceMilli = unitToMilli(record.importance ?: 0.5)
            val trustMilli = unitToMilli(record.trust)
            val totalPoints =
                keywordMilli * weights.keyword +
                    entityMilli * weights.entity +
                    recencyMilli * weights.recency +
                    importanceMilli * weights.importance +
                    trustMilli * weights.trust

            hits += MemoryHit(
                record = record,
                score = MemoryScore(
                    totalPoints = totalPoints,
                    keywordMilli = keywordMilli,
                    entityMilli = entityMilli,
                    recencyMilli = recencyMilli,
                    importanceMilli = importanceMilli,
                    trustMilli = trustMilli,
                ),
            )
        }

        return hits
            .sortedWith(hitComparator)
            .take(query.limit)
    }

    private fun validateQuery(query: MemoryQuery): Set<String> {
        if (query.scopes.isEmpty()) {
            throw MemoryRetrievalError(
                "at least one memory scope is required",
            )
        }
        val scopes = linkedSetOf<String>()
        query.scopes.forEach { raw ->
            scopes += raw.trim().uppercase(Locale.ROOT)
        }

        val unknown = scopes - RETRIEVAL_MEMORY_SCOPES
        if (unknown.isNotEmpty()) {
            throw MemoryRetrievalError(
                "unsupported memory scopes: " +
                    unknown.sorted().joinToString(", "),
            )
        }
        if (
            scopes.any { it in OWNER_SCOPES } &&
            query.ownerId.isNullOrBlank()
        ) {
            throw MemoryRetrievalError(
                "owner_id is required for " +
                    "USER_PERSONA/CONTACT_PROFILE retrieval",
            )
        }
        if (
            "CONVERSATION_MEMORY" in scopes &&
            query.conversationId.isNullOrBlank()
        ) {
            throw MemoryRetrievalError(
                "conversation_id is required for " +
                    "CONVERSATION_MEMORY retrieval",
            )
        }
        if (
            "TASK_MEMORY" in scopes &&
            query.taskId.isNullOrBlank()
        ) {
            throw MemoryRetrievalError(
                "task_id is required for TASK_MEMORY retrieval",
            )
        }
        if (query.minTrust !in 0.0..1.0) {
            throw MemoryRetrievalError(
                "min_trust must be between 0 and 1",
            )
        }
        if (query.limit !in 1..100) {
            throw MemoryRetrievalError(
                "limit must be between 1 and 100",
            )
        }
        return scopes
    }

    private fun domainMatches(
        entity: MemoryEntity,
        query: MemoryQuery,
    ): Boolean =
        when (entity.scope) {
            "USER_PERSONA",
            "CONTACT_PROFILE",
            -> entity.ownerId == query.ownerId

            "CONVERSATION_MEMORY" ->
                entity.conversationId == query.conversationId

            "TASK_MEMORY" ->
                entity.taskId == query.taskId

            else -> entity.scope == "SYSTEM_POLICY"
        }

    private fun isTemporallyValid(
        entity: MemoryEntity,
        now: Instant,
    ): Boolean {
        entity.validFrom?.let { raw ->
            val validFrom = parseTimestamp(raw) ?: return false
            if (now < validFrom) return false
        }
        entity.validTo?.let { raw ->
            val validTo = parseTimestamp(raw) ?: return false
            if (now >= validTo) return false
        }
        return true
    }

    private fun keywordScore(
        record: MemoryRecord,
        terms: List<String>,
    ): Int {
        if (terms.isEmpty()) return 0
        val searchable = normalizeText(
            buildList {
                add(record.content)
                addAll(record.entities)
            }.joinToString(" "),
        )
        val matched = terms.count { it in searchable }
        return matched * 1000 / terms.size
    }

    private fun entityScore(
        record: MemoryRecord,
        queryEntities: List<String>,
    ): Int {
        if (queryEntities.isEmpty()) return 0
        val recordEntities = normalizedUnique(record.entities).toSet()
        val matched = queryEntities.count { it in recordEntities }
        return matched * 1000 / queryEntities.size
    }

    private fun recencyScore(
        record: MemoryRecord,
        now: Instant,
    ): Int {
        val anchor = record.validFrom?.let(::parseTimestamp)
            ?: parseTimestamp(record.createdAt)
            ?: return 0

        val ageSeconds = maxOf(
            0L,
            now.epochSecond - anchor.epochSecond,
        )
        val ageDays = ageSeconds / 86_400.0
        return when {
            ageDays <= 1.0 -> 1000
            ageDays <= 7.0 -> 850
            ageDays <= 30.0 -> 700
            ageDays <= 180.0 -> 450
            ageDays <= 365.0 -> 250
            else -> 100
        }
    }

    private val hitComparator =
        compareByDescending<MemoryHit> { it.score.totalPoints }
            .thenByDescending { it.score.keywordMilli }
            .thenByDescending { it.score.entityMilli }
            .thenByDescending { it.score.recencyMilli }
            .thenByDescending { it.score.importanceMilli }
            .thenByDescending { it.score.trustMilli }
            .thenByDescending {
                parseTimestamp(it.record.createdAt)?.epochSecond
                    ?: Long.MIN_VALUE
            }
            .thenBy { it.record.memoryId }

    private fun record(entity: MemoryEntity): MemoryRecord =
        MemoryRecord(
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

    private fun decodeEntities(value: String): List<String> {
        val array = JSONArray(value)
        return buildList {
            for (index in 0 until array.length()) {
                add(array.getString(index))
            }
        }
    }

    private fun terms(value: String): List<String> {
        val normalized = normalizeText(value)
        return TERM_PATTERN
            .findAll(normalized)
            .map { it.value }
            .distinct()
            .toList()
    }

    private fun normalizedUnique(values: List<String>): List<String> {
        val seen = linkedSetOf<String>()
        values.forEach { raw ->
            val value = normalizeText(raw)
            if (value.isNotEmpty()) seen += value
        }
        return seen.toList()
    }

    private fun normalizeText(value: String): String {
        val normalized = Normalizer.normalize(
            value,
            Normalizer.Form.NFKC,
        ).lowercase(Locale.ROOT)
        return normalized
            .trim()
            .replace(Regex("\\s+"), " ")
    }

    private fun unitToMilli(value: Double): Int {
        val number = value.coerceIn(0.0, 1.0)
        return (number * 1000 + 0.5).toInt()
    }

    private fun parseTimestamp(value: String): Instant? =
        runCatching {
            OffsetDateTime
                .parse(value)
                .withOffsetSameInstant(ZoneOffset.UTC)
                .toInstant()
        }.getOrNull()
}
