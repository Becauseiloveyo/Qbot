package dev.qbot.android.data

import dev.qbot.android.data.db.AgentRunEntity
import dev.qbot.android.data.db.InboundEventEntity
import dev.qbot.android.data.db.QbotDao
import dev.qbot.android.data.db.TaskCheckpointEntity
import dev.qbot.android.data.db.TaskEntity

data class RestoredRunState(
    val run: AgentRunEntity,
    val triggerEvent: InboundEventEntity,
    val activeTask: TaskEntity?,
    val checkpoint: TaskCheckpointEntity?,
)

class DurableStateRepository(
    private val dao: QbotDao,
) {
    suspend fun restore(runId: String): RestoredRunState {
        val run = requireNotNull(dao.agentRun(runId)) {
            "unknown AgentRun: " + runId
        }
        val event = requireNotNull(dao.inboundById(run.triggerEventId)) {
            "AgentRun references missing inbound event: " + run.triggerEventId
        }

        val task = if (run.taskId != null) {
            dao.task(run.taskId)
        } else {
            dao.activeTask(run.conversationId)
        }

        val checkpoint = task?.let {
            dao.checkpointForVersion(
                taskId = it.taskId,
                taskVersion = it.version,
            )
        }

        return RestoredRunState(
            run = run,
            triggerEvent = event,
            activeTask = task,
            checkpoint = checkpoint,
        )
    }
}
