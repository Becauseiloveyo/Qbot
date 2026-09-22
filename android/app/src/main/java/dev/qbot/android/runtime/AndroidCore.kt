package dev.qbot.android.runtime

import dev.qbot.android.data.AdmissionResult
import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.DurableStateRepository
import dev.qbot.android.data.InboundAdmissionRepository
import dev.qbot.android.data.RestoredRunState
import dev.qbot.android.transport.QQTransport

data class AndroidProcessResult(
    val admission: AdmissionResult,
    val restored: RestoredRunState,
)

class AndroidCore(
    private val transport: QQTransport,
    private val admission: InboundAdmissionRepository,
    private val runRepository: AgentRunRepository,
    private val stateRepository: DurableStateRepository,
    private val memoryMaintenanceScheduler: MemoryMaintenanceScheduler? = null,
    private val locks: ConversationLockManager = ConversationLockManager(),
    private val normalizer: EventNormalizer = EventNormalizer(
        transportName = transport.name,
    ),
) {
    suspend fun processOne(): AndroidProcessResult {
        val incoming = transport.receive()
        val event = normalizer.normalize(incoming)

        return locks.serial(
            accountId = event.accountId,
            conversationId = event.conversationId,
        ) {
            val admitted = admission.admit(event)
            runRepository.beginRestore(admitted.runId)
            val restored = stateRepository.restore(admitted.runId)
            if (admitted.isNew) {
                memoryMaintenanceScheduler?.enqueue(admitted.eventId)
            }
            AndroidProcessResult(
                admission = admitted,
                restored = restored,
            )
        }
    }
}
