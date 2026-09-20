package dev.qbot.android.transport.routing

import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.SendAvailability
import dev.qbot.android.transport.SendReadiness
import dev.qbot.android.transport.TransportCapability

enum class AdapterTier {
    STANDARD,
    ENHANCED,
    EXPERIMENTAL,
}

enum class AdapterHealth {
    READY,
    DEGRADED,
    STOPPED,
    PERMISSION_REQUIRED,
    UNAVAILABLE,
}

data class TransportAdapterSnapshot(
    val adapterId: String,
    val tier: AdapterTier,
    val health: AdapterHealth,
    val capabilities: Set<TransportCapability>,
    val priority: Int,
    val detail: String? = null,
)

data class TransportAdapterBinding(
    val transport: QQTransport,
    val snapshot: () -> TransportAdapterSnapshot,
)

data class CandidateEvaluation(
    val adapterId: String,
    val health: AdapterHealth,
    val readiness: SendAvailability?,
    val reason: String?,
)

data class TransportSelection(
    val binding: TransportAdapterBinding,
    val snapshot: TransportAdapterSnapshot,
    val readiness: SendReadiness,
    val evaluations: List<CandidateEvaluation>,
)

class TransportSelector(
    private val bindings: List<TransportAdapterBinding>,
) {
    suspend fun selectTextSend(
        message: OutgoingMessage,
    ): TransportSelection? {
        val evaluations = mutableListOf<CandidateEvaluation>()

        val candidates = bindings
            .map { binding -> binding to binding.snapshot() }
            .sortedWith(
                compareBy<Pair<TransportAdapterBinding, TransportAdapterSnapshot>>(
                    { healthRank(it.second.health) },
                    { it.second.priority },
                    { it.second.adapterId },
                ),
            )

        for ((binding, snapshot) in candidates) {
            if (TransportCapability.SEND_TEXT !in snapshot.capabilities) {
                evaluations += CandidateEvaluation(
                    adapterId = snapshot.adapterId,
                    health = snapshot.health,
                    readiness = SendAvailability.UNSUPPORTED,
                    reason = "adapter does not advertise SEND_TEXT",
                )
                continue
            }

            if (snapshot.health !in USABLE_HEALTH) {
                evaluations += CandidateEvaluation(
                    adapterId = snapshot.adapterId,
                    health = snapshot.health,
                    readiness = null,
                    reason = snapshot.detail
                        ?: "adapter health does not permit sending",
                )
                continue
            }

            val readiness = binding.transport.checkSendReadiness(message)
            evaluations += CandidateEvaluation(
                adapterId = snapshot.adapterId,
                health = snapshot.health,
                readiness = readiness.availability,
                reason = readiness.reason,
            )

            if (readiness.ready) {
                return TransportSelection(
                    binding = binding,
                    snapshot = snapshot,
                    readiness = readiness,
                    evaluations = evaluations.toList(),
                )
            }
        }

        return null
    }

    fun snapshots(): List<TransportAdapterSnapshot> =
        bindings
            .map { it.snapshot() }
            .sortedWith(
                compareBy<TransportAdapterSnapshot>(
                    { healthRank(it.health) },
                    { it.priority },
                    { it.adapterId },
                ),
            )

    companion object {
        private val USABLE_HEALTH = setOf(
            AdapterHealth.READY,
            AdapterHealth.DEGRADED,
        )

        private fun healthRank(health: AdapterHealth): Int =
            when (health) {
                AdapterHealth.READY -> 0
                AdapterHealth.DEGRADED -> 1
                AdapterHealth.PERMISSION_REQUIRED -> 2
                AdapterHealth.STOPPED -> 3
                AdapterHealth.UNAVAILABLE -> 4
            }
    }
}
