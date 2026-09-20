package dev.qbot.android.transport.notification

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat

object NotificationAccessController {
    fun isAccessGranted(context: Context): Boolean =
        context.packageName in
            NotificationManagerCompat.getEnabledListenerPackages(context)

    fun settingsIntent(context: Context): Intent {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val component = ComponentName(
                context,
                QbotNotificationListenerService::class.java,
            )
            val detail = Intent(
                Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS,
            ).putExtra(
                Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME,
                component.flattenToString(),
            )
            if (detail.resolveActivity(context.packageManager) != null) {
                return detail
            }
        }

        return Intent(
            Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS,
        )
    }
}
