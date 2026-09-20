package dev.qbot.android.transport.notification

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import dev.qbot.android.work.StartupRecoveryWorker

class QbotNotificationListenerService : NotificationListenerService() {
    private val transport: NotificationQQTransport by lazy {
        NotificationTransportProvider.get(applicationContext)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        transport.onListenerConnectionChanged(true)

        // RemoteInput/PendingIntent handles are intentionally not persisted.
        // Rehydrate them from notifications that are still active after a
        // process restart before asking recovery to revisit deferred Outbox.
        runCatching {
            activeNotifications?.toList().orEmpty()
        }.getOrDefault(emptyList()).forEach { notification ->
            transport.onNotificationPosted(notification)
        }

        StartupRecoveryWorker.enqueue(this)
    }

    override fun onListenerDisconnected() {
        transport.onListenerConnectionChanged(false)
        super.onListenerDisconnected()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (transport.onNotificationPosted(sbn)) {
            // A fresh notification may restore a previously unavailable live
            // RemoteInput action. Unique work + KEEP avoids parallel recovery.
            StartupRecoveryWorker.enqueue(this)
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        transport.onNotificationRemoved(sbn)
    }
}
