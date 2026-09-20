package dev.qbot.android.runtime

import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport

enum class RecoveryMode {
    OBSERVE,
    ASSIST,
}

enum class RecoveryOutcome {
    REPORTED,
    DEFERRED,
    SENT,
    RECONCILED,
    FINALIZED,
    SEND_UNKNOWN,
}

data class RecoveryExecution(
    val item: RecoveryItem,
    val outcome: RecoveryOutcome,
    val detail: String = "",
)

data class RecoveryReport(
    val mode: RecoveryMode,
    val plan: RecoveryPlan,
    val executions: List<RecoveryExecution>,
)

class RecoveryExecutor(
    private val planner: RecoveryPlanner,
    private val runs: AgentRunRepository,
    private val outbox: OutboxRepository,
    private val transport: QQTransport,
    private val sender: SendExecutor = SendExecutor(
        outbox = outbox,
        transport = transport,
    ),
) {
    suspend fun run(
        mode: RecoveryMode = RecoveryMode.ASSIST,
    ): RecoveryReport {
        val plan = planner.plan()
        if (mode == RecoveryMode.OBSERVE) {
            return RecoveryReport(
                mode = mode,
                plan = plan,
                executions = plan.items.map {
                    RecoveryExecution(
                        item = it,
                        outcome = RecoveryOutcome.REPORTED,
                        detail = it.reason,
                    )
                },
            )
        }

        val executions = plan.items.map { item ->
            execute(item)
        }
        return RecoveryReport(
            mode = mode,
            plan = plan,
            executions = executions,
        )
    }

    private suspend fun execute(
        item: RecoveryItem,
    ): RecoveryExecution =
        when (item.action) {
            RecoveryAction.SEND_PENDING ->
                executePending(item)

            RecoveryAction.RECONCILE_UNKNOWN ->
                executeReconcile(item)

            RecoveryAction.FINALIZE_SENT_RUN ->
                executeFinalize(item)

            RecoveryAction.RESUME_RUN ->
                RecoveryExecution(
                    item = item,
                    outcome = RecoveryOutcome.DEFERRED,
                    detail = "decision runtime resume is not enabled in Android v0.5 yet",
                )

            RecoveryAction.MANUAL_REVIEW ->
                RecoveryExecution(
                    item = item,
                    outcome = RecoveryOutcome.DEFERRED,
                    detail = item.reason,
                )

            RecoveryAction.WAITING_USER ->
                RecoveryExecution(
                    item = item,
                    outcome = RecoveryOutcome.DEFERRED,
                    detail = item.reason,
                )
        }

    private suspend fun executePending(
        item: RecoveryItem,
    ): RecoveryExecution {
        val outboxId = requireNotNull(item.outboxId)
        val record = outbox.load(outboxId)
        if (record.status != "PENDING") {
            return RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = "Outbox is no longer PENDING: " + record.status,
            )
        }

        val message = OutgoingMessage(
            accountId = record.accountId,
            conversationId = record.conversationId,
            dedupeKey = record.dedupeKey,
            text = record.payloadText.orEmpty(),
            replyToMessageId = record.replyToMessageId,
        )
        val readiness = transport.checkSendReadiness(message)
        if (!readiness.ready) {
            return RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = readiness.reason
                    ?: "transport is not currently ready to send",
            )
        }

        val sent = sender.send(outboxId)
        return when (sent.status) {
            "SENT" -> {
                val finalized = finalizeRunIfEffectsTerminal(item.runId)
                RecoveryExecution(
                    item = item,
                    outcome = RecoveryOutcome.SENT,
                    detail = if (finalized) {
                        "durable PENDING effect sent once; AgentRun finalized locally"
                    } else {
                        "durable PENDING effect sent once"
                    },
                )
            }

            "SENDING_UNKNOWN" -> RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.SEND_UNKNOWN,
                detail = sent.lastError.orEmpty(),
            )

            else -> RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = "send completed in state " + sent.status,
            )
        }
    }

    private suspend fun executeReconcile(
        item: RecoveryItem,
    ): RecoveryExecution {
        val outboxId = requireNotNull(item.outboxId)
        val reconciled = sender.reconcile(outboxId)
        return if (reconciled.status == "SENT") {
            val finalized = finalizeRunIfEffectsTerminal(item.runId)
            RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.RECONCILED,
                detail = if (finalized) {
                    "unknown delivery reconciled without resend; AgentRun finalized locally"
                } else {
                    "unknown delivery reconciled without resend"
                },
            )
        } else {
            RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = "delivery remains unresolved",
            )
        }
    }

    private suspend fun finalizeRunIfEffectsTerminal(
        runId: String,
    ): Boolean {
        val run = runs.load(runId) ?: return false
        if (run.status != "EXECUTING") {
            return false
        }

        val effects = outbox.listForRun(runId)
        if (
            effects.isEmpty() ||
            effects.any {
                it.status != "SENT" && it.status != "CANCELLED"
            }
        ) {
            return false
        }

        runs.transition(runId, "SUCCEEDED")
        return true
    }

    private suspend fun executeFinalize(
        item: RecoveryItem,
    ): RecoveryExecution {
        val run = runs.load(item.runId)
            ?: return RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = "AgentRun no longer exists",
            )
        if (run.status != "EXECUTING") {
            return RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = "AgentRun is no longer EXECUTING: " + run.status,
            )
        }

        runs.transition(item.runId, "SUCCEEDED")
        return RecoveryExecution(
            item = item,
            outcome = RecoveryOutcome.FINALIZED,
            detail = "external effects were already terminal; finalized locally",
        )
    }
}
