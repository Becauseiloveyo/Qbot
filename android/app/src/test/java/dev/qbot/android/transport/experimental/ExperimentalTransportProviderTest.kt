package dev.qbot.android.transport.experimental

import dev.qbot.android.transport.DeliveryLookupResult
import dev.qbot.android.transport.IncomingTransportEvent
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.SendResult
import dev.qbot.android.transport.TransportCapability
import dev.qbot.android.transport.routing.AdapterHealth
import dev.qbot.android.transport.routing.AdapterTier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ExperimentalTransportProviderTest {
    @Test
    fun disabledProviderDoesNotCreateBinding() {
        assertNull(
            DisabledExperimentalTransportProvider()
                .bindingOrNull(),
        )
    }

    @Test
    fun explicitlyEnabledButUnhealthyProviderAdvertisesNoCapability() {
        val provider = ExplicitExperimentalTransportProvider(
            adapterId = "hook-test",
            transport = ProbeTransport(),
            enabled = { true },
            healthy = { false },
        )

        val snapshot = provider.bindingOrNull()!!.snapshot()

        assertEquals(AdapterTier.EXPERIMENTAL, snapshot.tier)
        assertEquals(AdapterHealth.DEGRADED, snapshot.health)
        assertTrue(snapshot.capabilities.isEmpty())
    }

    @Test
    fun healthyExperimentalProviderStillRequiresExplicitEnablement() {
        val transport = ProbeTransport()
        val disabled = ExplicitExperimentalTransportProvider(
            adapterId = "hook-test",
            transport = transport,
            enabled = { false },
            healthy = { true },
        )
        assertNull(disabled.bindingOrNull())

        val enabled = ExplicitExperimentalTransportProvider(
            adapterId = "hook-test",
            transport = transport,
            enabled = { true },
            healthy = { true },
        )
        val snapshot = enabled.bindingOrNull()!!.snapshot()

        assertEquals(AdapterHealth.READY, snapshot.health)
        assertEquals(
            setOf(TransportCapability.SEND_TEXT),
            snapshot.capabilities,
        )
    }

    private class ProbeTransport : QQTransport {
        override val name: String = "probe-experimental"
        override val capabilities: Set<TransportCapability> =
            setOf(TransportCapability.SEND_TEXT)

        override suspend fun start() = Unit
        override suspend fun stop() = Unit

        override suspend fun receive(): IncomingTransportEvent =
            error("receive not used")

        override suspend fun send(
            message: OutgoingMessage,
        ): SendResult =
            SendResult(accepted = true)

        override suspend fun lookupDelivery(
            accountId: String,
            dedupeKey: String,
        ): DeliveryLookupResult =
            DeliveryLookupResult(found = false)
    }
}
