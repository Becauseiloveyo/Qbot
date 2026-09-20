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
        CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val transport: AccessibilityQQTransport by lazy {
        AccessibilityTransportProvider.get()
    }

    private val uiDriver: AccessibilityUiDriver by lazy {
        AndroidAccessibilityUiDriver(this)
    }

    private var lifecycleReady = false
    private var activeReadyKey: String? = null

    override fun onServiceConnected() {
        super.onServiceConnected()

        scope.launch {
            transport.start()
            transport.onServiceConnected()
            lifecycleReady = true
            refreshReplySession()
        }
    }

    override fun onAccessibilityEvent(
        event: AccessibilityEvent,
    ) {
        if (!lifecycleReady) {
            return
        }

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
        lifecycleReady = false
        clearReplySession()
        transport.onServiceDisconnected()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        lifecycleReady = false
        clearReplySession()
        transport.onServiceDisconnected()
        scope.cancel()
        super.onDestroy()
    }

    private fun refreshReplySession() {
        if (!lifecycleReady) {
            clearReplySession()
            return
        }

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
            // accessibility session existed. Revisit it only after transport
            // lifecycle + exact UI validation have both reached READY.
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
