package dev.qbot.android.transport.accessibility

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.view.accessibility.AccessibilityEvent
import dev.qbot.android.work.StartupRecoveryWorker
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

    private val uiDriver: AccessibilityUiDriver by lazy {
        AndroidAccessibilityUiDriver(this)
    }

    private var activeReadyKey: String? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        scope.launch {
            transport.start()
            transport.onServiceConnected()
        }
        refreshReplySession()
    }

    override fun onAccessibilityEvent(
        event: AccessibilityEvent,
    ) {
        val packageName = event.packageName?.toString()
        if (packageName !in SUPPORTED_PACKAGES) {
            clearReplySession()
            return
        }

        refreshReplySession()
    }

    override fun onInterrupt() {
        clearReplySession()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        clearReplySession()
        transport.onServiceDisconnected()
        scope.launch {
            transport.stop()
        }
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        clearReplySession()
        transport.onServiceDisconnected()
        scope.cancel()
        super.onDestroy()
    }

    private fun refreshReplySession() {
        val spec = AccessibilitySessionSpecProvider.current()
        if (
            spec == null ||
            spec.profile.packageName !in SUPPORTED_PACKAGES
        ) {
            clearReplySession()
            return
        }

        val session = ProfileBoundAccessibilityReplySession(
            spec = spec,
            driver = uiDriver,
        )
        if (!session.isValid()) {
            clearReplySession()
            return
        }

        transport.updateReplySession(session)

        val readyKey = listOf(
            spec.binding.accountId,
            spec.binding.conversationId,
            spec.binding.profileId,
            spec.binding.expectedConversationToken,
        ).joinToString("\u001f")

        if (activeReadyKey != readyKey) {
            activeReadyKey = readyKey
            // A PENDING Outbox effect may have been deferred while no exact
            // accessibility session existed. Revisit it only when the exact
            // bound session transitions into READY.
            StartupRecoveryWorker.enqueue(this)
        }
    }

    private fun clearReplySession() {
        activeReadyKey = null
        transport.updateReplySession(null)
    }

    companion object {
        val SUPPORTED_PACKAGES: Set<String> = setOf(
            "com.tencent.mobileqq",
            "com.tencent.tim",
        )
    }
}
