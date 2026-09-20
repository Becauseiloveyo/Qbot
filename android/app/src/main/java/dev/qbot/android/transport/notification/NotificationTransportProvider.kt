package dev.qbot.android.transport.notification

import android.content.Context

object NotificationTransportProvider {
    @Volatile
    private var instance: NotificationQQTransport? = null

    fun get(context: Context): NotificationQQTransport {
        instance?.let { return it }

        return synchronized(this) {
            instance ?: NotificationQQTransport(
                context.applicationContext,
            ).also { created ->
                instance = created
            }
        }
    }
}
