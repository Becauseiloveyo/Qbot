package dev.qbot.android.transport.experimental

import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.routing.AdapterHealth
import dev.qbot.android.transport.routing.AdapterTier
import dev.qbot.android.transport.routing.TransportAdapterBinding
import dev.qbot.android.transport.routing.TransportAdapterSnapshot

/**
 * Boundary for optional root/LSPosed/hook transports.
 *
 * The standard Android artifact has no dependency on a hook framework.
 * A future expert module can supply a QQTransport through this interface only
 * when the user explicitly enables it.
 */
interface ExperimentalTransportProvider {
    fun bindingOrNull(): TransportAdapterBinding?
}

class DisabledExperimentalTransportProvider :
    ExperimentalTransportProvider {
    override fun bindingOrNull(): TransportAdapterBinding? = null
}

class ExplicitExperimentalTransportProvider(
    private val adapterId: String,
    private val transport: QQTransport,
    private val enabled: () -> Boolean,
    private val healthy: () -> Boolean,
    private val priority: Int = 100,
) : ExperimentalTransportProvider {
    override fun bindingOrNull(): TransportAdapterBinding? {
        if (!enabled()) {
            return null
        }

        return TransportAdapterBinding(
            transport = transport,
            snapshot = {
                TransportAdapterSnapshot(
                    adapterId = adapterId,
                    tier = AdapterTier.EXPERIMENTAL,
                    health = if (healthy()) {
                        AdapterHealth.READY
                    } else {
                        AdapterHealth.DEGRADED
                    },
                    capabilities = if (healthy()) {
                        transport.capabilities
                    } else {
                        emptySet()
                    },
                    priority = priority,
                    detail = if (healthy()) {
                        "explicitly enabled experimental transport"
                    } else {
                        "experimental transport is enabled but not healthy"
                    },
                )
            },
        )
    }
}
