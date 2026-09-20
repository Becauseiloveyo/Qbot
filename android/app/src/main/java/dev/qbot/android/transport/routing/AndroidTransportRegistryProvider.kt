package dev.qbot.android.transport.routing

import android.content.Context
import dev.qbot.android.transport.accessibility.AccessibilityTransportProvider
import dev.qbot.android.transport.experimental.DisabledExperimentalTransportProvider
import dev.qbot.android.transport.experimental.ExperimentalTransportProvider
import dev.qbot.android.transport.notification.NotificationTransportHealth
import dev.qbot.android.transport.notification.NotificationTransportProvider

object AndroidTransportRegistryProvider {
    @Volatile
    private var instance: TransportRegistry? = null

    @Volatile
    private var experimentalProvider: ExperimentalTransportProvider =
        DisabledExperimentalTransportProvider()

    fun configureExperimental(
        provider: ExperimentalTransportProvider,
    ) {
        synchronized(this) {
            check(instance == null) {
                "experimental transport must be configured before registry initialization"
            }
            experimentalProvider = provider
        }
    }

    fun get(
        context: Context,
    ): TransportRegistry {
        instance?.let { return it }

        return synchronized(this) {
            instance ?: create(
                context.applicationContext,
                experimentalProvider,
            ).also { created ->
                instance = created
            }
        }
    }

    private fun create(
        context: Context,
        experimentalProvider: ExperimentalTransportProvider,
    ): TransportRegistry {
        val notification =
            NotificationTransportProvider.get(context)
        val accessibility =
            AccessibilityTransportProvider.get()

        val bindings = mutableListOf(
                TransportAdapterBinding(
                    transport = notification,
                    snapshot = {
                        TransportAdapterSnapshot(
                            adapterId = notification.name,
                            tier = AdapterTier.STANDARD,
                            health = when (notification.health) {
                                NotificationTransportHealth.STOPPED ->
                                    AdapterHealth.STOPPED
                                NotificationTransportHealth.WAITING_FOR_LISTENER ->
                                    AdapterHealth.DEGRADED
                                NotificationTransportHealth.CONNECTED ->
                                    AdapterHealth.READY
                            },
                            capabilities = notification.capabilities,
                            priority = 10,
                            detail = when (notification.health) {
                                NotificationTransportHealth.STOPPED ->
                                    "notification transport is stopped"
                                NotificationTransportHealth.WAITING_FOR_LISTENER ->
                                    "waiting for notification listener connection"
                                NotificationTransportHealth.CONNECTED ->
                                    "notification listener is connected"
                            },
                        )
                    },
                ),
                TransportAdapterBinding(
                    transport = accessibility,
                    snapshot = {
                        accessibility.snapshot(
                            priority = 20,
                        )
                    },
                ),
            )

        experimentalProvider.bindingOrNull()?.let(bindings::add)

        return TransportRegistry(bindings)
    }
}
