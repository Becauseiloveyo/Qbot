package dev.qbot.android.transport.accessibility

enum class AccessibilityAdapterState {
    DISABLED,
    CONNECTED_UNRECOGNIZED,
    READY,
    DEGRADED,
}

data class AccessibilityUiCapabilitySnapshot(
    val state: AccessibilityAdapterState,
    val qqWindowRecognized: Boolean,
    val composerRecognized: Boolean,
    val sendActionRecognized: Boolean,
    val detail: String? = null,
) {
    val canSendText: Boolean
        get() =
            state == AccessibilityAdapterState.READY &&
                qqWindowRecognized &&
                composerRecognized &&
                sendActionRecognized
}
