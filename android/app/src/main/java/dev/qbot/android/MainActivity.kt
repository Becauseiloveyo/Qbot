package dev.qbot.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.qbot.android.transport.accessibility.AccessibilityAccessController
import dev.qbot.android.transport.accessibility.AccessibilityTransportProvider
import dev.qbot.android.transport.notification.NotificationAccessController
import dev.qbot.android.transport.notification.NotificationQQTransport
import dev.qbot.android.transport.notification.NotificationTransportHealth
import dev.qbot.android.transport.notification.NotificationTransportProvider
import dev.qbot.android.transport.routing.AdapterHealth
import dev.qbot.android.transport.shizuku.ShizukuCapabilityProvider
import dev.qbot.android.transport.shizuku.ShizukuCapabilityProviderHolder
import dev.qbot.android.transport.shizuku.ShizukuCapabilitySnapshot
import dev.qbot.android.transport.shizuku.ShizukuPermissionRequestResult
import dev.qbot.android.transport.shizuku.ShizukuProviderState

class MainActivity : ComponentActivity() {
    private var notificationAccessGranted by mutableStateOf(false)
    private var accessibilityEnabled by mutableStateOf(false)
    private var accessibilityHealth by mutableStateOf(AdapterHealth.STOPPED)
    private var shizukuSnapshot by mutableStateOf(
        ShizukuCapabilitySnapshot(
            state = ShizukuProviderState.NOT_INSTALLED,
            capabilities = emptySet(),
        ),
    )
    private var shizukuRequestStatus by mutableStateOf<String?>(null)

    private lateinit var shizukuProvider: ShizukuCapabilityProvider

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val notificationTransport =
            NotificationTransportProvider.get(applicationContext)
        shizukuProvider =
            ShizukuCapabilityProviderHolder.get(applicationContext)

        setContent {
            val notificationHealth by
                notificationTransport.healthFlow.collectAsState()
            val listenerConnected by
                notificationTransport.listenerConnected.collectAsState()

            QbotRoot(
                notificationAccessGranted = notificationAccessGranted,
                listenerConnected = listenerConnected,
                notificationHealth = notificationHealth,
                accessibilityEnabled = accessibilityEnabled,
                accessibilityHealth = accessibilityHealth,
                shizukuSnapshot = shizukuSnapshot,
                shizukuRequestStatus = shizukuRequestStatus,
                onOpenNotificationSettings = {
                    startActivity(
                        NotificationAccessController.settingsIntent(this),
                    )
                },
                onOpenAccessibilitySettings = {
                    startActivity(
                        AccessibilityAccessController.settingsIntent(),
                    )
                },
                onRequestShizukuPermission = {
                    shizukuRequestStatus =
                        shizukuProvider
                            .requestPermission(SHIZUKU_PERMISSION_REQUEST)
                            .displayName()
                    refreshCapabilityState()
                },
                onRefresh = ::refreshCapabilityState,
            )
        }
    }

    override fun onResume() {
        super.onResume()
        refreshCapabilityState()
    }

    private fun refreshCapabilityState() {
        notificationAccessGranted =
            NotificationAccessController.isAccessGranted(this)

        accessibilityEnabled =
            AccessibilityAccessController.isServiceEnabled(this)
        accessibilityHealth =
            AccessibilityTransportProvider.get().snapshot().health

        shizukuSnapshot = shizukuProvider.snapshot()
    }

    companion object {
        private const val SHIZUKU_PERMISSION_REQUEST = 60
    }
}

@Composable
private fun QbotRoot(
    notificationAccessGranted: Boolean,
    listenerConnected: Boolean,
    notificationHealth: NotificationTransportHealth,
    accessibilityEnabled: Boolean,
    accessibilityHealth: AdapterHealth,
    shizukuSnapshot: ShizukuCapabilitySnapshot,
    shizukuRequestStatus: String?,
    onOpenNotificationSettings: () -> Unit,
    onOpenAccessibilitySettings: () -> Unit,
    onRequestShizukuPermission: () -> Unit,
    onRefresh: () -> Unit,
) {
    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier.padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    text = "Qbot",
                    style = MaterialTheme.typography.headlineMedium,
                )
                Text(
                    text = "Android enhanced transport runtime v0.6",
                    style = MaterialTheme.typography.bodyMedium,
                )

                Text(
                    text = "Standard notification transport",
                    style = MaterialTheme.typography.titleMedium,
                )
                StatusLine(
                    label = "Notification access",
                    value = if (notificationAccessGranted) {
                        "Granted"
                    } else {
                        "Not granted"
                    },
                )
                StatusLine(
                    label = "Listener service",
                    value = if (listenerConnected) {
                        "Connected"
                    } else {
                        "Disconnected"
                    },
                )
                StatusLine(
                    label = "Notification adapter",
                    value = notificationHealth.displayName(),
                )

                Button(onClick = onOpenNotificationSettings) {
                    Text("Open notification access settings")
                }

                Text(
                    text = "Enhanced accessibility transport",
                    style = MaterialTheme.typography.titleMedium,
                )
                StatusLine(
                    label = "Accessibility permission",
                    value = if (accessibilityEnabled) {
                        "Enabled"
                    } else {
                        "Disabled"
                    },
                )
                StatusLine(
                    label = "Accessibility adapter",
                    value = accessibilityHealth.name,
                )
                Text(
                    text = "Accessibility permission alone does not enable " +
                        "sending. Qbot requires an exact, currently valid " +
                        "QQ/TIM conversation reply session.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Button(onClick = onOpenAccessibilitySettings) {
                    Text("Open accessibility settings")
                }

                Text(
                    text = "Optional Shizuku provider",
                    style = MaterialTheme.typography.titleMedium,
                )
                StatusLine(
                    label = "Shizuku",
                    value = shizukuSnapshot.state.name,
                )
                StatusLine(
                    label = "System capabilities",
                    value = shizukuSnapshot.capabilities
                        .map { it.name }
                        .sorted()
                        .joinToString()
                        .ifBlank { "None" },
                )
                shizukuSnapshot.detail?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                shizukuRequestStatus?.let {
                    StatusLine(
                        label = "Permission request",
                        value = it,
                    )
                }
                Button(onClick = onRequestShizukuPermission) {
                    Text("Request Shizuku permission")
                }

                StatusLine(
                    label = "Supported QQ packages",
                    value = NotificationQQTransport.DEFAULT_ALLOWED_PACKAGES
                        .sorted()
                        .joinToString(),
                )

                Button(onClick = onRefresh) {
                    Text("Refresh status")
                }
            }
        }
    }
}

@Composable
private fun StatusLine(
    label: String,
    value: String,
) {
    Text(
        text = "$label: $value",
        style = MaterialTheme.typography.bodyMedium,
    )
}

private fun NotificationTransportHealth.displayName(): String =
    when (this) {
        NotificationTransportHealth.STOPPED -> "Stopped"
        NotificationTransportHealth.WAITING_FOR_LISTENER ->
            "Waiting for listener"
        NotificationTransportHealth.CONNECTED -> "Connected"
    }

private fun ShizukuPermissionRequestResult.displayName(): String =
    when (this) {
        ShizukuPermissionRequestResult.ALREADY_GRANTED ->
            "Already granted"
        ShizukuPermissionRequestResult.REQUESTED ->
            "Requested"
        ShizukuPermissionRequestResult.SERVICE_UNAVAILABLE ->
            "Service unavailable"
        ShizukuPermissionRequestResult.DENIED_WITH_RATIONALE ->
            "Permission previously denied"
        ShizukuPermissionRequestResult.FAILED ->
            "Request failed"
    }
