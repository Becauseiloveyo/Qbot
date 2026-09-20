package dev.qbot.android.transport.accessibility

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.view.accessibility.AccessibilityManager

object AccessibilityAccessController {
    fun isServiceEnabled(
        context: Context,
    ): Boolean {
        val manager = context.getSystemService(
            AccessibilityManager::class.java,
        ) ?: return false
        val target = ComponentName(
            context,
            QbotAccessibilityService::class.java,
        )

        return manager
            .getEnabledAccessibilityServiceList(
                AccessibilityServiceInfo.FEEDBACK_ALL_MASK,
            )
            .any { info ->
                val serviceInfo = info.resolveInfo?.serviceInfo
                serviceInfo != null &&
                    ComponentName(
                        serviceInfo.packageName,
                        serviceInfo.name,
                    ) == target
            }
    }

    fun settingsIntent(): Intent =
        Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
}
