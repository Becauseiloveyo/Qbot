package dev.qbot.android.runtime

import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.TransportCapability

enum class RecoveryAction {
    RESUME_RUN,
    SEND_PENDING,
    RECONCILE_UNKNOWN,
    MANUAL_REVIEW,
    FINALIZE_SENT_RUN,
    WAITING_USER,
}

data class RecoveryItem(
    val action: RecoveryAction,
    val runId: String,
    val outboxId: String? = null,
    val transportId: String? = null,
    val reason: String,
)

data class RecoveryPlan(
    val items: List<RecoveryItem>,
    val interruptedSendsReclassified: List<String>,
)

class RecoveryPlanner(
    private val runs: AgentRunRepository,
    private val outbox: OutboxRepository,
    private val transport: QQTransport,
) {
    suspend fun plan(): RecoveryPlan {
        val interrupted = outbox.recoverInterruptedSends()
        val items = mutableListOf<RecoveryItem>()

        for (run in runs.listNonTerminal()) {
            val effects = outbox.listForRun(run.runId)

            if (run.status == "WAITING_USER") {
                items += RecoveryItem(
                    action = RecoveryAction.WAITING_USER,
                    runId = run.runId,
                    reason = "run is waiting for explicit human input",
                )
                continue
            }

            if (effects.isEmpty()) {
                items += RecoveryItem(
                    action = RecoveryAction.RESUME_RUN,
                    runId = run.runId,
                    reason = "non-terminal run has no external effect; status=" +
                        run.status,
                )
                continue
            }

            val pending = effects.filter { it.status == "PENDING" }
            val unknown = effects.filter { it.status == "SENDING_UNKNOWN" }
            val sent = effects.filter { it.status == "SENT" }
            val unresolvedOther = effects.filter {
                it.status !in setOf(
                    "PENDING",
                    "SENDING_UNKNOWN",
                    "SENT",
                    "CANCELLED",
                )
            }

            pending.forEach { effect ->
                items += RecoveryItem(
                    action = RecoveryAction.SEND_PENDING,
                    runId = run.runId,
                    outboxId = effect.outboxId,
                    reason = "durable effect exists but no send attempt is in flight",
                )
            }

            unknown.forEach { effect ->
                val canLookup =
                    TransportCapability.DELIVERY_LOOKUP in transport.capabilities
                items += RecoveryItem(
                    action = if (canLookup) {
                        RecoveryAction.RECONCILE_UNKNOWN
                    } else {
                        RecoveryAction.MANUAL_REVIEW
                    },
                    runId = run.runId,
                    outboxId = effect.outboxId,
                    reason = if (canLookup) {
                        "delivery outcome is unknown; transport supports lookup"
                    } else {
                        "delivery outcome is unknown and transport cannot " +
                            "reconcile safely; blind replay is forbidden"
                    },
                )
            }

            if (unresolvedOther.isNotEmpty()) {
                unresolvedOther.forEach { effect ->
                    items += RecoveryItem(
                        action = RecoveryAction.MANUAL_REVIEW,
                        runId = run.runId,
                        outboxId = effect.outboxId,
                        reason = "external effect is in unexpected recovery state: " +
                            effect.status,
                    )
                }
                continue
            }

            if (
                run.status == "EXECUTING" &&
                sent.isNotEmpty() &&
                pending.isEmpty() &&
                unknown.isEmpty() &&
                effects.all { it.status == "SENT" || it.status == "CANCELLED" }
            ) {
                items += RecoveryItem(
                    action = RecoveryAction.FINALIZE_SENT_RUN,
                    runId = run.runId,
                    reason = "all external effects are terminal; only local " +
                        "AgentRun completion was interrupted",
                )
            }
        }

        return RecoveryPlan(
            items = items.sortedWith(
                compareBy<RecoveryItem>(
                    { it.runId },
                    { it.outboxId.orEmpty() },
                    { it.action.name },
                ),
            ),
            interruptedSendsReclassified = interrupted.map { it.outboxId },
        )
    }
}
