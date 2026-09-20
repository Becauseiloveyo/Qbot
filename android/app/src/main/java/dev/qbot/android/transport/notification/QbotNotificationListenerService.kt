package dev.qbot.android.transport.notification

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class QbotNotificationListenerService : NotificationListenerService() {
    private val transport: NotificationQQTransport by lazy {
        NotificationTransportProvider.get(applicationContext)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        transport.onListenerConnectionChanged(true)
    }

    override fun onListenerDisconnected() {
        transport.onListenerConnectionChanged(false)
        super.onListenerDisconnected()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        transport.onNotificationPosted(sbn)
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        transport.onNotificationRemoved(sbn)
    }
}
