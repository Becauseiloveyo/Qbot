package dev.qbot.android.transport.accessibility

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.view.accessibility.AccessibilityEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class QbotAccessibilityService : AccessibilityService() {
    private val scope =
        CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private val transport: AccessibilityQQTransport by lazy {
        AccessibilityTransportProvider.get()
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        scope.launch {
            transport.start()
            transport.onServiceConnected()
        }
    }

    override fun onAccessibilityEvent(
        event: AccessibilityEvent,
    ) {
        val packageName = event.packageName?.toString()
        if (packageName !in SUPPORTED_PACKAGES) {
            // A reply session is valid only for the positively recognized
            // QQ/TIM foreground UI that created it.
            transport.updateReplySession(null)
        }

        // v0.6 intentionally does not infer SEND_TEXT from permission alone.
        // A later recognizer must prove an exact conversation + composer +
        // send action before installing a short-lived reply session.
    }

    override fun onInterrupt() {
        transport.updateReplySession(null)
    }

    override fun onUnbind(intent: Intent?): Boolean {
        transport.onServiceDisconnected()
        scope.launch {
            transport.stop()
        }
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        transport.onServiceDisconnected()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        val SUPPORTED_PACKAGES: Set<String> = setOf(
            "com.tencent.mobileqq",
            "com.tencent.tim",
        )
    }
}
