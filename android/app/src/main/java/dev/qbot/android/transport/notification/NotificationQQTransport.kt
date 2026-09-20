package dev.qbot.android.transport.notification

import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.service.notification.StatusBarNotification
import dev.qbot.android.transport.IncomingTransportEvent
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.SendResult
import dev.qbot.android.transport.TransportCapability
import java.security.MessageDigest
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.channels.Channel

enum class NotificationTransportHealth {
    STOPPED,
    WAITING_FOR_LISTENER,
    CONNECTED,
}

class NotificationQQTransport(
    context: Context,
    private val allowedPackages: Set<String> = DEFAULT_ALLOWED_PACKAGES,
    private val identityResolver: NotificationConversationIdentityResolver =
        NotificationConversationIdentityResolver(),
) : QQTransport {
    private data class LiveReplyAction(
        val notificationKey: String,
        val packageName: String,
        val remoteInputs: List<RemoteInput>,
        val pendingIntent: PendingIntent,
    )

    private val applicationContext = context.applicationContext
    private val incoming = Channel<IncomingTransportEvent>(Channel.UNLIMITED)
    private val replyActions =
        ConcurrentHashMap<String, LiveReplyAction>()

    @Volatile
    private var started = false

    @Volatile
    private var listenerConnected = false

    override val name: String = "android-notification"

    override val capabilities: Set<TransportCapability> = setOf(
        TransportCapability.READ_TEXT,
        TransportCapability.SEND_TEXT,
    )

    val health: NotificationTransportHealth
        get() = when {
            !started -> NotificationTransportHealth.STOPPED
            listenerConnected -> NotificationTransportHealth.CONNECTED
            else -> NotificationTransportHealth.WAITING_FOR_LISTENER
        }

    override suspend fun start() {
        started = true
    }

    override suspend fun stop() {
        started = false
    }

    override suspend fun receive(): IncomingTransportEvent {
        check(started) {
            "notification transport is not started"
        }
        return incoming.receive()
    }

    override suspend fun send(message: OutgoingMessage): SendResult {
        check(started) {
            "notification transport is not started"
        }

        val action = replyActions[message.conversationId]
            ?: return SendResult(
                accepted = false,
                error = "no live notification RemoteInput reply action",
            )

        val expectedAccountId = accountIdForPackage(action.packageName)
        if (message.accountId != expectedAccountId) {
            return SendResult(
                accepted = false,
                error = "notification account identity does not match live reply action",
            )
        }

        val results = Bundle()
        action.remoteInputs.forEach { remoteInput ->
            results.putCharSequence(remoteInput.resultKey, message.text)
        }
        val fillInIntent = Intent()
        RemoteInput.addResultsToIntent(
            action.remoteInputs.toTypedArray(),
            fillInIntent,
            results,
        )

        return try {
            action.pendingIntent.send(
                applicationContext,
                0,
                fillInIntent,
            )
            SendResult(
                accepted = true,
                platformMessageId = null,
            )
        } catch (_: PendingIntent.CanceledException) {
            replyActions.remove(
                message.conversationId,
                action,
            )
            SendResult(
                accepted = false,
                error = "notification reply action expired or was cancelled",
            )
        }
    }

    fun onListenerConnectionChanged(connected: Boolean) {
        listenerConnected = connected
        if (!connected) {
            replyActions.clear()
        }
    }

    fun onNotificationPosted(
        sbn: StatusBarNotification,
    ): Boolean {
        if (sbn.packageName !in allowedPackages) {
            return false
        }

        val text = extractText(sbn.notification)
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?: return false

        val identity = identityResolver.resolve(sbn)
        findReplyAction(sbn.notification)?.let { candidate ->
            replyActions[identity.conversationId] = LiveReplyAction(
                notificationKey = sbn.key,
                packageName = sbn.packageName,
                remoteInputs = candidate.first,
                pendingIntent = candidate.second,
            )
        }

        val title = extractTitle(sbn.notification)
        val event = IncomingTransportEvent(
            accountId = accountIdForPackage(sbn.packageName),
            conversationId = identity.conversationId,
            senderId = null,
            platformMessageId = notificationMessageId(
                sbn = sbn,
                text = text,
            ),
            messageType = "system",
            text = text,
            occurredAt = Instant.ofEpochMilli(sbn.postTime),
            metadata = buildMap {
                put(
                    "identity_quality",
                    identity.quality.name,
                )
                put(
                    "account_identity_quality",
                    "PACKAGE_ONLY",
                )
                put("source_package", sbn.packageName)
                put("notification_key", sbn.key)
                put(
                    "reply_available",
                    replyActions.containsKey(
                        identity.conversationId,
                    ).toString(),
                )
                if (!title.isNullOrBlank()) {
                    put("display_title", title)
                }
            },
        )

        return incoming.trySend(event).isSuccess
    }

    fun onNotificationRemoved(
        sbn: StatusBarNotification,
    ) {
        if (sbn.packageName !in allowedPackages) {
            return
        }

        val identity = identityResolver.resolve(sbn)
        val current = replyActions[identity.conversationId]
        if (current?.notificationKey == sbn.key) {
            replyActions.remove(
                identity.conversationId,
                current,
            )
        }
    }

    private fun findReplyAction(
        notification: Notification,
    ): Pair<List<RemoteInput>, PendingIntent>? {
        val candidates = notification.actions
            ?.mapNotNull { action ->
                val pendingIntent = action.actionIntent
                    ?: return@mapNotNull null
                val freeFormInputs = action.remoteInputs
                    ?.filter { it.allowFreeFormInput }
                    .orEmpty()
                if (freeFormInputs.isEmpty()) {
                    return@mapNotNull null
                }
                Triple(
                    Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
                        action.semanticAction ==
                            Notification.Action.SEMANTIC_ACTION_REPLY,
                    freeFormInputs,
                    pendingIntent,
                )
            }
            .orEmpty()

        val candidate = candidates.firstOrNull { it.first }
            ?: candidates.firstOrNull()
            ?: return null

        return candidate.second to candidate.third
    }

    private fun extractText(
        notification: Notification,
    ): String? =
        notification.extras
            .getCharSequence(Notification.EXTRA_BIG_TEXT)
            ?.toString()
            ?.takeIf { it.isNotBlank() }
            ?: notification.extras
                .getCharSequence(Notification.EXTRA_TEXT)
                ?.toString()
                ?.takeIf { it.isNotBlank() }

    private fun extractTitle(
        notification: Notification,
    ): String? =
        notification.extras
            .getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)
            ?.toString()
            ?.takeIf { it.isNotBlank() }
            ?: notification.extras
                .getCharSequence(Notification.EXTRA_TITLE)
                ?.toString()
                ?.takeIf { it.isNotBlank() }

    private fun notificationMessageId(
        sbn: StatusBarNotification,
        text: String,
    ): String {
        val material = listOf(
            sbn.packageName,
            sbn.key,
            sbn.postTime.toString(),
            text,
        ).joinToString("\u001f")
        return "notification-" + sha256(material).take(32)
    }

    private fun sha256(value: String): String =
        MessageDigest.getInstance("SHA-256")
            .digest(value.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }

    companion object {
        val DEFAULT_ALLOWED_PACKAGES: Set<String> = setOf(
            "com.tencent.mobileqq",
            "com.tencent.tim",
        )

        fun accountIdForPackage(packageName: String): String =
            "android-notification:" + packageName
    }
}
