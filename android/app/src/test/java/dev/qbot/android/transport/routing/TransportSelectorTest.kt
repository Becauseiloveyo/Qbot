package dev.qbot.android.transport.routing

import dev.qbot.android.transport.DeliveryLookupResult
import dev.qbot.android.transport.IncomingTransportEvent
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.SendAvailability
import dev.qbot.android.transport.SendReadiness
import dev.qbot.android.transport.SendResult
import dev.qbot.android.transport.TransportCapability
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TransportSelectorTest {
    @Test
    fun fallsBackBeforeSendWhenPreferredAdapterIsTemporarilyUnavailable() =
        runTest {
            val standard = ProbeTransport(
                readiness = SendReadiness(
                    SendAvailability.TEMPORARILY_UNAVAILABLE,
                    "no live RemoteInput",
                ),
            )
            val accessibility = ProbeTransport(
                readiness = SendReadiness(SendAvailability.READY),
            )
            val selector = TransportSelector(
                listOf(
                    binding(
                        id = "notification",
                        tier = AdapterTier.STANDARD,
                        priority = 10,
                        health = AdapterHealth.READY,
                        transport = standard,
                    ),
                    binding(
                        id = "accessibility",
                        tier = AdapterTier.ENHANCED,
                        priority = 20,
                        health = AdapterHealth.READY,
                        transport = accessibility,
                    ),
                ),
            )

            val selected = selector.selectTextSend(message())

            assertEquals("accessibility", selected?.snapshot?.adapterId)
            assertEquals(1, standard.readinessChecks)
            assertEquals(1, accessibility.readinessChecks)
            assertEquals(0, standard.sendCalls)
            assertEquals(0, accessibility.sendCalls)
        }

    @Test
    fun readyAdapterBeatsDegradedAdapterEvenWhenDegradedHasLowerPriority() =
        runTest {
            val degraded = ProbeTransport(
                readiness = SendReadiness(SendAvailability.READY),
            )
            val ready = ProbeTransport(
                readiness = SendReadiness(SendAvailability.READY),
            )
            val selector = TransportSelector(
                listOf(
                    binding(
                        id = "degraded-standard",
                        tier = AdapterTier.STANDARD,
                        priority = 1,
                        health = AdapterHealth.DEGRADED,
                        transport = degraded,
                    ),
                    binding(
                        id = "ready-enhanced",
                        tier = AdapterTier.ENHANCED,
                        priority = 100,
                        health = AdapterHealth.READY,
                        transport = ready,
                    ),
                ),
            )

            assertEquals(
                "ready-enhanced",
                selector.selectTextSend(message())?.snapshot?.adapterId,
            )
        }

    @Test
    fun permissionRequiredAdapterIsNeverSelected() = runTest {
        val blocked = ProbeTransport(
            readiness = SendReadiness(SendAvailability.READY),
        )
        val selector = TransportSelector(
            listOf(
                binding(
                    id = "accessibility",
                    tier = AdapterTier.ENHANCED,
                    priority = 1,
                    health = AdapterHealth.PERMISSION_REQUIRED,
                    transport = blocked,
                ),
            ),
        )

        assertNull(selector.selectTextSend(message()))
        assertEquals(0, blocked.readinessChecks)
        assertEquals(0, blocked.sendCalls)
    }

    private fun binding(
        id: String,
        tier: AdapterTier,
        priority: Int,
        health: AdapterHealth,
        transport: QQTransport,
    ): TransportAdapterBinding =
        TransportAdapterBinding(
            transport = transport,
            snapshot = {
                TransportAdapterSnapshot(
                    adapterId = id,
                    tier = tier,
                    health = health,
                    capabilities = setOf(TransportCapability.SEND_TEXT),
                    priority = priority,
                )
            },
        )

    private fun message(): OutgoingMessage =
        OutgoingMessage(
            accountId = "acc-1",
            conversationId = "conv-1",
            dedupeKey = "dedupe-12345678",
            text = "hello",
        )

    private class ProbeTransport(
        private val readiness: SendReadiness,
    ) : QQTransport {
        var readinessChecks = 0
        var sendCalls = 0

        override val name: String = "probe"
        override val capabilities: Set<TransportCapability> =
            setOf(TransportCapability.SEND_TEXT)

        override suspend fun start() = Unit
        override suspend fun stop() = Unit

        override suspend fun receive(): IncomingTransportEvent =
            error("receive not used")

        override suspend fun checkSendReadiness(
            message: OutgoingMessage,
        ): SendReadiness {
            readinessChecks += 1
            return readiness
        }

        override suspend fun send(message: OutgoingMessage): SendResult {
            sendCalls += 1
            return SendResult(
                accepted = true,
                platformMessageId = "probe-" + sendCalls,
            )
        }

        override suspend fun lookupDelivery(
            accountId: String,
            dedupeKey: String,
        ): DeliveryLookupResult =
            DeliveryLookupResult(found = false)
    }
}
