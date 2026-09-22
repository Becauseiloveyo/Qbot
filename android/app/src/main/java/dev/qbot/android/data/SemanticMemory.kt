package dev.qbot.android.data

enum class SemanticScoreStatus {
    DISABLED,
    SCORED,
    MISSING,
    UNAVAILABLE,
    FAILED,
}

class SemanticScorerUnavailable(message: String) : RuntimeException(message)

data class SemanticCandidate(
    val memoryId: String,
    val content: String,
    val entities: List<String>,
)

data class SemanticScoringRequest(
    val queryText: String,
    val queryEntities: List<String>,
    val candidates: List<SemanticCandidate>,
)

data class SemanticScore(
    val memoryId: String,
    val scoreMilli: Int,
)

data class SemanticAudit(
    val status: SemanticScoreStatus,
    val provider: String? = null,
    val model: String? = null,
    val scoreMilli: Int? = null,
    val errorType: String? = null,
)

interface SemanticRelevanceScorer {
    val providerName: String

    val modelName: String?
        get() = null

    suspend fun score(
        request: SemanticScoringRequest,
    ): List<SemanticScore>
}

class NoopSemanticRelevanceScorer : SemanticRelevanceScorer {
    override val providerName: String = "noop"

    override suspend fun score(
        request: SemanticScoringRequest,
    ): List<SemanticScore> {
        @Suppress("UNUSED_VARIABLE")
        val ignored = request
        throw SemanticScorerUnavailable(
            "semantic relevance backend is not configured",
        )
    }
}
