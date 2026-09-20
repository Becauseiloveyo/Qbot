package dev.qbot.android.data

import dev.qbot.android.data.db.AgentRunEntity
import dev.qbot.android.data.db.QbotDao
import java.time.Clock
import java.time.Instant

class InvalidAgentRunTransition(
    message: String,
) : IllegalArgumentException(message)

class ConcurrentAgentRunTransition(
    message: String,
) : IllegalStateException(message)

class AgentRunRepository(
    private val dao: QbotDao,
    private val clock: Clock = Clock.systemUTC(),
) {
    suspend fun load(runId: String): AgentRunEntity? =
        dao.agentRun(runId)

    suspend fun listNonTerminal(): List<AgentRunEntity> =
        dao.agentRunsByStatus(NON_TERMINAL.toList())

    suspend fun beginRestore(runId: String): AgentRunEntity {
        val current = requireNotNull(dao.agentRun(runId)) {
            "unknown AgentRun: " + runId
        }
        return if (current.status == "CREATED") {
            transition(runId, "RESTORING")
        } else {
            current
        }
    }

    suspend fun transition(
        runId: String,
        targetStatus: String,
    ): AgentRunEntity {
        val current = requireNotNull(dao.agentRun(runId)) {
            "unknown AgentRun: " + runId
        }
        val allowed = ALLOWED_TRANSITIONS[current.status].orEmpty()
        if (targetStatus !in allowed) {
            throw InvalidAgentRunTransition(
                "illegal AgentRun transition: " +
                    current.status + " -> " + targetStatus,
            )
        }

        val changed = dao.transitionAgentRun(
            runId = runId,
            expectedStatus = current.status,
            targetStatus = targetStatus,
            updatedAt = Instant.now(clock).toString(),
        )
        if (changed != 1) {
            throw ConcurrentAgentRunTransition(
                "AgentRun changed concurrently while transitioning " +
                    runId + " from " + current.status + " to " + targetStatus,
            )
        }

        return requireNotNull(dao.agentRun(runId)) {
            "AgentRun disappeared after transition: " + runId
        }
    }

    companion object {
        val NON_TERMINAL: Set<String> = setOf(
            "CREATED",
            "RESTORING",
            "REASONING",
            "WAITING_USER",
            "EXECUTING",
        )

        private val ALLOWED_TRANSITIONS: Map<String, Set<String>> = mapOf(
            "CREATED" to setOf("RESTORING"),
            "RESTORING" to setOf("REASONING", "FAILED"),
            "REASONING" to setOf(
                "WAITING_USER",
                "EXECUTING",
                "SUCCEEDED",
                "FAILED",
            ),
            "WAITING_USER" to setOf("REASONING", "CANCELLED"),
            "EXECUTING" to setOf("REASONING", "SUCCEEDED", "FAILED"),
            "SUCCEEDED" to emptySet(),
            "FAILED" to emptySet(),
            "CANCELLED" to emptySet(),
        )
    }
}
