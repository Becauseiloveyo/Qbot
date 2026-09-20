package dev.qbot.android.transport

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.channels.Channel

class FakeTransport : QQTransport {
    private val incoming = Channel<IncomingTransportEvent>(Channel.UNLIMITED)
    private val deliveries = ConcurrentHashMap<Pair<String, String>, String>()
    private val counter = AtomicLong(0)

    @Volatile
    private var started = false

    @Volatile
    private var uncertainAfterNextDelivery = false

    override val name: String = "fake"

    override val capabilities: Set<TransportCapability> = setOf(
        TransportCapability.READ_TEXT,
        TransportCapability.SEND_TEXT,
        TransportCapability.READ_HISTORY,
        TransportCapability.QUOTE_REPLY,
        TransportCapability.DELIVERY_LOOKUP,
    )

    override suspend fun start() {
        started = true
    }

    override suspend fun stop() {
        started = false
    }

    suspend fun inject(event: IncomingTransportEvent) {
        incoming.send(event)
    }

    fun makeNextSendUncertainAfterDelivery() {
        uncertainAfterNextDelivery = true
    }

    override suspend fun receive(): IncomingTransportEvent {
        requireStarted()
        return incoming.receive()
    }

    override suspend fun send(message: OutgoingMessage): SendResult {
        requireStarted()
        val key = message.accountId to message.dedupeKey
        val id = deliveries.computeIfAbsent(key) {
            "fake-msg-" + counter.incrementAndGet()
        }

        if (uncertainAfterNextDelivery) {
            uncertainAfterNextDelivery = false
            return SendResult(
                accepted = false,
                platformMessageId = id,
                uncertain = true,
                error = "simulated acknowledgement loss after delivery",
            )
        }

        return SendResult(
            accepted = true,
            platformMessageId = id,
        )
    }

    override suspend fun lookupDelivery(
        accountId: String,
        dedupeKey: String,
    ): DeliveryLookupResult {
        requireStarted()
        val id = deliveries[accountId to dedupeKey]
        return DeliveryLookupResult(
            found = id != null,
            platformMessageId = id,
        )
    }

    private fun requireStarted() {
        check(started) { "transport is not started" }
    }
}
