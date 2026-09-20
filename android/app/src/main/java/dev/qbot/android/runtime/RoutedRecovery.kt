package dev.qbot.android.runtime

import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.transport.TransportCapability
import dev.qbot.android.transport.routing.TransportRegistry

class RoutedRecoveryPlanner(
    private val runs: AgentRunRepository,
    private val outbox: OutboxRepository,
    private val registry: TransportRegistry,
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
                val adapterId =
                    outbox.lastAttemptTransportId(effect.outboxId)
                val binding = adapterId?.let(registry::binding)
                val canLookup =
                    binding != null &&
                        TransportCapability.DELIVERY_LOOKUP in
                        binding.transport.capabilities

                items += RecoveryItem(
                    action = if (canLookup) {
                        RecoveryAction.RECONCILE_UNKNOWN
                    } else {
                        RecoveryAction.MANUAL_REVIEW
                    },
                    runId = run.runId,
                    outboxId = effect.outboxId,
                    transportId = adapterId,
                    reason = when {
                        adapterId == null ->
                            "delivery outcome is unknown and the original " +
                                "adapter id is unavailable; manual review required"
                        binding == null ->
                            "delivery outcome is unknown and original adapter " +
                                adapterId + " is not registered"
                        canLookup ->
                            "delivery outcome is unknown; original adapter " +
                                adapterId + " supports lookup"
                        else ->
                            "delivery outcome is unknown and original adapter " +
                                adapterId + " cannot reconcile safely; blind " +
                                "replay/cross-adapter lookup is forbidden"
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
                effects.all {
                    it.status == "SENT" || it.status == "CANCELLED"
                }
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
            interruptedSendsReclassified =
                interrupted.map { it.outboxId },
        )
    }
}

class RoutedRecoveryExecutor(
    private val planner: RoutedRecoveryPlanner,
    private val runs: AgentRunRepository,
    private val outbox: OutboxRepository,
    private val registry: TransportRegistry,
) {
    private val routedSender =
        RoutedSendExecutor(
            outbox = outbox,
            selector = registry.selector,
        )

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

        return RecoveryReport(
            mode = mode,
            plan = plan,
            executions = plan.items.map { execute(it) },
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
                    detail = "decision runtime resume is not enabled in Android v0.6 yet",
                )

            RecoveryAction.MANUAL_REVIEW,
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

        val result = routedSender.send(outboxId)
        return when (result.outcome) {
            RoutedSendOutcome.SENT -> {
                val finalized = finalizeRunIfEffectsTerminal(item.runId)
                RecoveryExecution(
                    item = item,
                    outcome = RecoveryOutcome.SENT,
                    detail = if (finalized) {
                        "routed effect sent by " + result.adapterId +
                            "; AgentRun finalized locally"
                    } else {
                        "routed effect sent by " + result.adapterId
                    },
                )
            }

            RoutedSendOutcome.SEND_UNKNOWN ->
                RecoveryExecution(
                    item = item,
                    outcome = RecoveryOutcome.SEND_UNKNOWN,
                    detail = result.detail.orEmpty(),
                )

            RoutedSendOutcome.DEFERRED,
            RoutedSendOutcome.FAILED ->
                RecoveryExecution(
                    item = item,
                    outcome = RecoveryOutcome.DEFERRED,
                    detail = result.detail
                        ?: "routed send did not complete",
                )
        }
    }

    private suspend fun executeReconcile(
        item: RecoveryItem,
    ): RecoveryExecution {
        val outboxId = requireNotNull(item.outboxId)
        val adapterId = item.transportId
            ?: return RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = "original adapter id is missing",
            )
        val binding = registry.binding(adapterId)
            ?: return RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.DEFERRED,
                detail = "original adapter is not registered: " + adapterId,
            )

        val reconciled = SendExecutor(
            outbox = outbox,
            transport = binding.transport,
        ).reconcile(outboxId)

        return if (reconciled.status == "SENT") {
            val finalized = finalizeRunIfEffectsTerminal(item.runId)
            RecoveryExecution(
                item = item,
                outcome = RecoveryOutcome.RECONCILED,
                detail = if (finalized) {
                    "original adapter reconciled without resend; AgentRun finalized"
                } else {
                    "original adapter reconciled without resend"
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
