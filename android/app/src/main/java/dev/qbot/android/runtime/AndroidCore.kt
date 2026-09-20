package dev.qbot.android.runtime

import dev.qbot.android.data.AdmissionResult
import dev.qbot.android.data.InboundAdmissionRepository
import dev.qbot.android.transport.QQTransport

class AndroidCore(
    private val transport: QQTransport,
    private val admission: InboundAdmissionRepository,
    private val locks: ConversationLockManager = ConversationLockManager(),
    private val normalizer: EventNormalizer = EventNormalizer(
        transportName = transport.name,
    ),
) {
    suspend fun processOne(): AdmissionResult {
        val incoming = transport.receive()
        val event = normalizer.normalize(incoming)

        return locks.serial(
            accountId = event.accountId,
            conversationId = event.conversationId,
        ) {
            admission.admit(event)
        }
    }
}
