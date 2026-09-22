package dev.qbot.android.data

import android.app.Application
import android.content.Context
import androidx.room.Room
import dev.qbot.android.data.db.MemoryEntity
import dev.qbot.android.data.db.QbotDatabase
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONArray
import org.json.JSONObject
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config


private class FixtureSemanticScorer(
    override val providerName: String,
    override val modelName: String?,
    private val outputs: List<SemanticScore>,
) : SemanticRelevanceScorer {
    var seenCandidateIds: List<String> = emptyList()
        private set

    override suspend fun score(
        request: SemanticScoringRequest,
    ): List<SemanticScore> {
        seenCandidateIds = request.candidates.map { it.memoryId }
        return outputs
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [37], application = Application::class)
class MemoryRetrievalRoomTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private lateinit var memory: MemoryRepository
    private lateinit var retriever: MemoryRetriever

    private val now = Instant.parse("2026-09-20T16:30:00Z")

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
        database = Room.inMemoryDatabaseBuilder(
            context,
            QbotDatabase::class.java,
        )
            .allowMainThreadQueries()
            .build()
        memory = MemoryRepository(
            database = database,
            clock = Clock.fixed(
                Instant.parse("2026-09-20T16:00:00Z"),
                ZoneOffset.UTC,
            ),
        )
        retriever = MemoryRetriever(database)
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun onlyPromotedCurrentDomainRecordsAreEligible() = runBlocking {
        val promoted = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-1",
            content = "project deadline is Friday",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-promoted",
            validFrom = "2026-09-20T12:00:00Z",
        )
        memory.createCandidate(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-1",
            content = "project deadline candidate",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-candidate",
        )
        val rejected = memory.createCandidate(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-1",
            content = "project deadline rejected",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-rejected",
        )
        memory.reject(rejected.memoryId)
        promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-2",
            content = "project deadline other conversation",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-other",
        )

        val old = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-1",
            content = "project deadline was Monday",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-old",
        )
        val replacement = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-1",
            content = "project deadline is now Tuesday",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-new",
            supersedes = old.memoryId,
        )

        val hits = retriever.retrieve(
            MemoryQuery(
                scopes = listOf("CONVERSATION_MEMORY"),
                conversationId = "conv-1",
                text = "project deadline",
                limit = 10,
            ),
            now = now,
        )

        val ids = hits.map { it.record.memoryId }
        assertTrue(promoted.memoryId in ids)
        assertTrue(replacement.memoryId in ids)
        assertTrue(old.memoryId !in ids)
        assertEquals(2, ids.size)
        assertTrue(hits.all { it.record.state == "PROMOTED" })
    }

    @Test
    fun scoringIsDeterministicAndExposesComponents() = runBlocking {
        val recent = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-score",
            content = "tea meeting moved to eight",
            entities = listOf("tea", "meeting"),
            sourceType = "USER_SELF",
            trust = 0.8,
            importance = 0.6,
            sourceEventId = "evt-recent",
            validFrom = "2026-09-20T12:00:00Z",
        )
        val older = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-score",
            content = "tea meeting notes",
            entities = listOf("tea"),
            sourceType = "USER_SELF",
            trust = 1.0,
            importance = 1.0,
            sourceEventId = "evt-older",
            validFrom = "2025-09-01T00:00:00Z",
        )

        val query = MemoryQuery(
            scopes = listOf("CONVERSATION_MEMORY"),
            conversationId = "conv-score",
            text = "tea meeting",
            entities = listOf("meeting"),
        )
        val first = retriever.retrieve(query, now)
        val second = retriever.retrieve(query, now)

        assertEquals(
            first.map { it.record.memoryId },
            second.map { it.record.memoryId },
        )
        assertEquals(recent.memoryId, first.first().record.memoryId)
        assertEquals(1000, first.first().score.keywordMilli)
        assertEquals(1000, first.first().score.entityMilli)
        assertEquals(1000, first.first().score.recencyMilli)
        assertEquals(600, first.first().score.importanceMilli)
        assertEquals(800, first.first().score.trustMilli)

        val olderScore = first
            .first { it.record.memoryId == older.memoryId }
            .score
            .totalPoints
        assertTrue(first.first().score.totalPoints > olderScore)
    }

    @Test
    fun ownerScopeIsolationIsStrict() = runBlocking {
        val wanted = promote(
            scope = "CONTACT_PROFILE",
            ownerId = "contact-1",
            content = "likes green tea",
            entities = listOf("tea"),
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-contact-1",
        )
        promote(
            scope = "CONTACT_PROFILE",
            ownerId = "contact-2",
            content = "likes green tea",
            entities = listOf("tea"),
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-contact-2",
        )

        val hits = retriever.retrieve(
            MemoryQuery(
                scopes = listOf("CONTACT_PROFILE"),
                ownerId = "contact-1",
                text = "tea",
            ),
            now = now,
        )

        assertEquals(
            listOf(wanted.memoryId),
            hits.map { it.record.memoryId },
        )
    }

    @Test
    fun temporalValidityAndRelevanceFailClosed() = runBlocking {
        val live = promote(
            scope = "TASK_MEMORY",
            taskId = "task-1",
            content = "deploy after tests pass",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-live",
            validFrom = "2026-09-20T10:00:00Z",
            validTo = "2026-09-21T10:00:00Z",
        )
        promote(
            scope = "TASK_MEMORY",
            taskId = "task-1",
            content = "deploy future plan",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-future",
            validFrom = "2026-09-21T10:00:00Z",
        )
        promote(
            scope = "TASK_MEMORY",
            taskId = "task-1",
            content = "deploy expired plan",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-expired",
            validTo = "2026-09-19T10:00:00Z",
        )
        promote(
            scope = "TASK_MEMORY",
            taskId = "task-1",
            content = "unrelated shopping preference",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-unrelated",
        )

        val hits = retriever.retrieve(
            MemoryQuery(
                scopes = listOf("TASK_MEMORY"),
                taskId = "task-1",
                text = "deploy",
            ),
            now = now,
        )

        assertEquals(
            listOf(live.memoryId),
            hits.map { it.record.memoryId },
        )
    }

    @Test
    fun explicitDomainIdentifiersAndLimitsAreRequired() = runBlocking {
        expectRetrievalError {
            retriever.retrieve(
                MemoryQuery(
                    scopes = listOf("CONVERSATION_MEMORY"),
                    text = "x",
                ),
                now = now,
            )
        }
        expectRetrievalError {
            retriever.retrieve(
                MemoryQuery(
                    scopes = listOf("CONTACT_PROFILE"),
                    text = "x",
                ),
                now = now,
            )
        }
        expectRetrievalError {
            retriever.retrieve(
                MemoryQuery(
                    scopes = listOf("SYSTEM_POLICY"),
                    limit = 0,
                ),
                now = now,
            )
        }
    }

    @Test
    fun minimumTrustAndStableLimitAreRepeatable() = runBlocking {
        repeat(3) { index ->
            promote(
                scope = "CONVERSATION_MEMORY",
                conversationId = "conv-limit",
                content = "same keyword record $index",
                sourceType = "USER_SELF",
                trust = if (index == 0) 0.2 else 0.8,
                importance = 0.5,
                sourceEventId = "evt-limit-$index",
                validFrom = "2026-09-20T12:00:00Z",
            )
        }

        val query = MemoryQuery(
            scopes = listOf("CONVERSATION_MEMORY"),
            conversationId = "conv-limit",
            text = "same keyword",
            minTrust = 0.5,
            limit = 2,
        )
        val first = retriever.retrieve(query, now)
        val second = retriever.retrieve(query, now)

        assertEquals(2, first.size)
        assertEquals(
            first.map { it.record.memoryId },
            second.map { it.record.memoryId },
        )
        assertTrue(first.all { it.record.trust >= 0.5 })
    }


    @Test
    fun sharedCrossRuntimeRetrievalFixture() = runBlocking {
        val repoRoot = System.getProperty("qbot.repo.root")
            ?: error("qbot.repo.root system property is required")
        val fixtureFile = File(
            repoRoot,
            "tests/conformance/memory-retrieval-parity.json",
        )
        assertTrue("shared retrieval fixture must exist", fixtureFile.isFile)

        val fixture = JSONObject(fixtureFile.readText())
        val given = fixture.getJSONObject("given")
        val records = given.getJSONArray("memories")
        for (index in 0 until records.length()) {
            val item = records.getJSONObject(index)
            val provenance = item.getJSONObject("provenance")
            val inserted = database.qbotDao().insertMemoryIfAbsent(
                MemoryEntity(
                    memoryId = item.getString("memory_id"),
                    schemaVersion = item.getString("schema_version"),
                    state = item.getString("state"),
                    scope = item.getString("scope"),
                    ownerId = nullableString(item, "owner_id"),
                    conversationId = nullableString(item, "conversation_id"),
                    taskId = nullableString(item, "task_id"),
                    content = item.getString("content"),
                    entitiesJson = item.getJSONArray("entities").toString(),
                    importance = nullableDouble(item, "importance"),
                    trust = item.getDouble("trust"),
                    confidence = nullableDouble(item, "confidence"),
                    sourceType = provenance.getString("source_type"),
                    sourceMessageId = nullableString(provenance, "source_message_id"),
                    sourceEventId = nullableString(provenance, "source_event_id"),
                    validFrom = nullableString(item, "valid_from"),
                    validTo = nullableString(item, "valid_to"),
                    supersedes = nullableString(item, "supersedes"),
                    createdAt = item.getString("created_at"),
                ),
            )
            assertTrue(inserted != -1L)
        }

        val cases = given.getJSONArray("retrieval_cases")
        for (caseIndex in 0 until cases.length()) {
            val fixtureCase = cases.getJSONObject(caseIndex)
            val rawQuery = fixtureCase.getJSONObject("query")
            val query = MemoryQuery(
                scopes = stringList(rawQuery.getJSONArray("scopes")),
                text = rawQuery.optString("text", ""),
                ownerId = nullableString(rawQuery, "owner_id"),
                conversationId = nullableString(rawQuery, "conversation_id"),
                taskId = nullableString(rawQuery, "task_id"),
                entities = stringList(rawQuery.getJSONArray("entities")),
                minTrust = rawQuery.getDouble("min_trust"),
                limit = rawQuery.getInt("limit"),
            )
            val evaluationTime = Instant.parse(
                fixtureCase.getString("evaluation_time"),
            )
            val indexedRetriever = MemoryRetriever(
                database = database,
                enableFts = true,
            )
            val scanRetriever = MemoryRetriever(
                database = database,
                enableFts = false,
            )
            val indexedHits = indexedRetriever.retrieve(
                query = query,
                now = evaluationTime,
            )
            val scanHits = scanRetriever.retrieve(
                query = query,
                now = evaluationTime,
            )
            val expected = fixtureCase
                .getJSONObject("expect")
                .getJSONArray("hits")

            assertEquals(
                "case ${fixtureCase.getString("case_id")} hit count",
                expected.length(),
                indexedHits.size,
            )
            assertEquals(
                scanHits.map { it.record.memoryId },
                indexedHits.map { it.record.memoryId },
            )
            assertEquals(
                scanHits.map { it.score },
                indexedHits.map { it.score },
            )
            assertEquals("fts4", indexedRetriever.lastCandidateBackend)
            assertEquals("scan", scanRetriever.lastCandidateBackend)

            for (hitIndex in 0 until expected.length()) {
                val expectedHit = expected.getJSONObject(hitIndex)
                val expectedScore = expectedHit.getJSONObject("score")
                val hit = indexedHits[hitIndex]
                assertEquals(expectedHit.getString("memory_id"), hit.record.memoryId)
                assertEquals(expectedScore.getInt("total_points"), hit.score.totalPoints)
                assertEquals(expectedScore.getInt("keyword_milli"), hit.score.keywordMilli)
                assertEquals(expectedScore.getInt("entity_milli"), hit.score.entityMilli)
                assertEquals(expectedScore.getInt("recency_milli"), hit.score.recencyMilli)
                assertEquals(expectedScore.getInt("importance_milli"), hit.score.importanceMilli)
                assertEquals(expectedScore.getInt("trust_milli"), hit.score.trustMilli)
            }
        }

        val retrievalById = buildMap<String, JSONObject> {
            for (caseIndex in 0 until cases.length()) {
                val fixtureCase = cases.getJSONObject(caseIndex)
                put(
                    fixtureCase.getString("case_id"),
                    fixtureCase,
                )
            }
        }
        val semanticCases = given.getJSONArray("semantic_cases")
        for (caseIndex in 0 until semanticCases.length()) {
            val semanticCase = semanticCases.getJSONObject(caseIndex)
            val retrievalCase = retrievalById.getValue(
                semanticCase.getString("retrieval_case_id"),
            )
            val rawQuery = retrievalCase.getJSONObject("query")
            val query = MemoryQuery(
                scopes = stringList(rawQuery.getJSONArray("scopes")),
                text = rawQuery.optString("text", ""),
                ownerId = nullableString(rawQuery, "owner_id"),
                conversationId = nullableString(
                    rawQuery,
                    "conversation_id",
                ),
                taskId = nullableString(rawQuery, "task_id"),
                entities = stringList(rawQuery.getJSONArray("entities")),
                minTrust = rawQuery.getDouble("min_trust"),
                limit = rawQuery.getInt("limit"),
            )
            val evaluationTime = Instant.parse(
                retrievalCase.getString("evaluation_time"),
            )
            val deterministic = retriever.retrieve(
                query = query,
                now = evaluationTime,
            )

            val rawScorer =
                if (semanticCase.isNull("scorer")) {
                    null
                } else {
                    semanticCase.getJSONObject("scorer")
                }
            val scorer: SemanticRelevanceScorer? =
                when {
                    rawScorer == null -> null
                    rawScorer.getString("behavior") == "unavailable" ->
                        NoopSemanticRelevanceScorer()
                    else -> {
                        val outputsJson =
                            rawScorer.getJSONArray("outputs")
                        val outputs = buildList {
                            for (
                                outputIndex in 0 until outputsJson.length()
                            ) {
                                val output =
                                    outputsJson.getJSONObject(outputIndex)
                                add(
                                    SemanticScore(
                                        memoryId = output.getString(
                                            "memory_id",
                                        ),
                                        scoreMilli = output.getInt(
                                            "score_milli",
                                        ),
                                    ),
                                )
                            }
                        }
                        FixtureSemanticScorer(
                            providerName = rawScorer.getString("provider"),
                            modelName = nullableString(
                                rawScorer,
                                "model",
                            ),
                            outputs = outputs,
                        )
                    }
                }

            val enriched = retriever.retrieveWithSemantics(
                query = query,
                scorer = scorer,
                now = evaluationTime,
            )
            val expected = semanticCase
                .getJSONObject("expect")
                .getJSONArray("hits")

            assertEquals(
                deterministic.map { it.record.memoryId },
                enriched.map { it.record.memoryId },
            )
            assertEquals(
                deterministic.map { it.score },
                enriched.map { it.score },
            )
            assertEquals(expected.length(), enriched.size)

            if (scorer is FixtureSemanticScorer) {
                assertEquals(
                    deterministic.map { it.record.memoryId },
                    scorer.seenCandidateIds,
                )
            }

            for (hitIndex in 0 until expected.length()) {
                val expectedHit = expected.getJSONObject(hitIndex)
                val expectedAudit =
                    expectedHit.getJSONObject("semantic")
                val hit = enriched[hitIndex]
                val audit = checkNotNull(hit.semantic)

                assertEquals(
                    expectedHit.getString("memory_id"),
                    hit.record.memoryId,
                )
                assertEquals(
                    expectedAudit.getString("status"),
                    audit.status.name,
                )
                assertEquals(
                    nullableString(expectedAudit, "provider"),
                    audit.provider,
                )
                assertEquals(
                    nullableString(expectedAudit, "model"),
                    audit.model,
                )
                assertEquals(
                    nullableInt(expectedAudit, "score_milli"),
                    audit.scoreMilli,
                )
                assertEquals(
                    nullableString(expectedAudit, "error_type"),
                    audit.errorType,
                )
            }
        }
    }

    @Test
    fun ftsFallsBackForShortNonAsciiQuery() = runBlocking {
        val wanted = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-cjk",
            content = "会议安排已经确认",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-cjk",
        )

        val hits = retriever.retrieve(
            MemoryQuery(
                scopes = listOf("CONVERSATION_MEMORY"),
                conversationId = "conv-cjk",
                text = "会议",
            ),
            now = now,
        )

        assertEquals(
            listOf(wanted.memoryId),
            hits.map { it.record.memoryId },
        )
        assertEquals("scan", retriever.lastCandidateBackend)
    }

    @Test
    fun ftsIndexRebuildsAfterAppendOnlyMemoryGrowth() = runBlocking {
        val first = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-growth",
            content = "alpha release note",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-growth-1",
        )
        val query = MemoryQuery(
            scopes = listOf("CONVERSATION_MEMORY"),
            conversationId = "conv-growth",
            text = "alpha",
        )

        val firstHits = retriever.retrieve(query, now)
        assertEquals(
            listOf(first.memoryId),
            firstHits.map { it.record.memoryId },
        )
        assertEquals("fts4", retriever.lastCandidateBackend)

        val second = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-growth",
            content = "alpha followup",
            sourceType = "USER_SELF",
            trust = 1.0,
            sourceEventId = "evt-growth-2",
        )
        val secondHits = retriever.retrieve(query, now)

        assertEquals(
            setOf(first.memoryId, second.memoryId),
            secondHits.map { it.record.memoryId }.toSet(),
        )
        assertEquals("fts4", retriever.lastCandidateBackend)
    }

    @Test
    fun explicitScanModeMatchesIndexedMode() = runBlocking {
        val wanted = promote(
            scope = "CONVERSATION_MEMORY",
            conversationId = "conv-scan",
            content = "stable keyword memory",
            sourceType = "USER_SELF",
            trust = 0.8,
            importance = 0.7,
            sourceEventId = "evt-scan",
        )
        val query = MemoryQuery(
            scopes = listOf("CONVERSATION_MEMORY"),
            conversationId = "conv-scan",
            text = "keyword",
        )

        val indexed = retriever.retrieve(query, now)
        val scanRetriever = MemoryRetriever(
            database = database,
            enableFts = false,
        )
        val scanned = scanRetriever.retrieve(query, now)

        assertEquals(
            listOf(wanted.memoryId),
            indexed.map { it.record.memoryId },
        )
        assertEquals(indexed, scanned)
        assertEquals("fts4", retriever.lastCandidateBackend)
        assertEquals("scan", scanRetriever.lastCandidateBackend)
    }

    private fun nullableString(value: JSONObject, key: String): String? =
        if (!value.has(key) || value.isNull(key)) null else value.getString(key)

    private fun nullableInt(value: JSONObject, key: String): Int? =
        if (!value.has(key) || value.isNull(key)) null else value.getInt(key)

    private fun nullableDouble(value: JSONObject, key: String): Double? =
        if (!value.has(key) || value.isNull(key)) null else value.getDouble(key)

    private fun stringList(value: JSONArray): List<String> =
        buildList {
            for (index in 0 until value.length()) {
                add(value.getString(index))
            }
        }

    private suspend fun promote(
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
    ): MemoryRecord =
        memory.promote(
            memory.createCandidate(
                scope = scope,
                content = content,
                sourceType = sourceType,
                trust = trust,
                ownerId = ownerId,
                conversationId = conversationId,
                taskId = taskId,
                entities = entities,
                importance = importance,
                confidence = confidence,
                sourceMessageId = sourceMessageId,
                sourceEventId = sourceEventId,
                validFrom = validFrom,
                validTo = validTo,
                supersedes = supersedes,
            ).memoryId,
        )

    private suspend fun expectRetrievalError(
        block: suspend () -> Unit,
    ) {
        try {
            block()
            fail("expected MemoryRetrievalError")
        } catch (_: MemoryRetrievalError) {
            // Expected.
        }
    }
}
