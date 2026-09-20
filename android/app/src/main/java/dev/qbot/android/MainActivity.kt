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
import dev.qbot.android.transport.notification.NotificationAccessController
import dev.qbot.android.transport.notification.NotificationQQTransport
import dev.qbot.android.transport.notification.NotificationTransportHealth
import dev.qbot.android.transport.notification.NotificationTransportProvider

class MainActivity : ComponentActivity() {
    private var notificationAccessGranted by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val notificationTransport =
            NotificationTransportProvider.get(applicationContext)

        setContent {
            val health by notificationTransport.healthFlow.collectAsState()
            val listenerConnected by
                notificationTransport.listenerConnected.collectAsState()

            QbotRoot(
                accessGranted = notificationAccessGranted,
                listenerConnected = listenerConnected,
                health = health,
                onOpenNotificationSettings = {
                    startActivity(
                        NotificationAccessController.settingsIntent(this),
                    )
                },
            )
        }
    }

    override fun onResume() {
        super.onResume()
        notificationAccessGranted =
            NotificationAccessController.isAccessGranted(this)
    }
}

@Composable
private fun QbotRoot(
    accessGranted: Boolean,
    listenerConnected: Boolean,
    health: NotificationTransportHealth,
    onOpenNotificationSettings: () -> Unit,
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
                    text = "Android durable runtime v0.5",
                    style = MaterialTheme.typography.bodyMedium,
                )

                Text(
                    text = "Standard QQ/TIM notification transport",
                    style = MaterialTheme.typography.titleMedium,
                )
                StatusLine(
                    label = "Notification access",
                    value = if (accessGranted) "Granted" else "Not granted",
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
                    label = "Transport runtime",
                    value = health.displayName(),
                )
                StatusLine(
                    label = "Supported packages",
                    value = NotificationQQTransport.DEFAULT_ALLOWED_PACKAGES
                        .sorted()
                        .joinToString(),
                )

                Text(
                    text = "Standard mode only observes notification text and " +
                        "can reply while the current QQ/TIM notification exposes " +
                        "a live RemoteInput action. It does not provide delivery " +
                        "history lookup.",
                    style = MaterialTheme.typography.bodySmall,
                )

                Button(
                    onClick = onOpenNotificationSettings,
                ) {
                    Text("Open notification access settings")
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
