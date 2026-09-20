package dev.qbot.android.transport.notification

import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Looper
import android.os.UserHandle
import android.service.notification.StatusBarNotification
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.TransportCapability
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [37])
class NotificationQQTransportTest {
    private lateinit var context: Context

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
    }

    @After
    fun tearDown() = Unit

    @Test
    fun titleFallbackIsStableAcrossNotificationSlotsAndQualityIsExplicit() {
        val resolver = NotificationConversationIdentityResolver()
        val first = statusBarNotification(
            packageName = "com.tencent.mobileqq",
            id = 1,
            title = "Alice",
            text = "hello",
        )
        val second = statusBarNotification(
            packageName = "com.tencent.mobileqq",
            id = 99,
            title = "Alice",
            text = "new message",
        )
        val other = statusBarNotification(
            packageName = "com.tencent.mobileqq",
            id = 2,
            title = "Bob",
            text = "hello",
        )

        val firstIdentity = resolver.resolve(first)
        val secondIdentity = resolver.resolve(second)
        val otherIdentity = resolver.resolve(other)

        assertEquals(
            ConversationIdentityQuality.TITLE_FALLBACK,
            firstIdentity.quality,
        )
        assertEquals(
            firstIdentity.conversationId,
            secondIdentity.conversationId,
        )
        assertNotEquals(
            firstIdentity.conversationId,
            otherIdentity.conversationId,
        )
    }

    @Test
    fun transportAcceptsOnlyQqTimAndNeverAdvertisesDeliveryLookup() = runBlocking {
        val transport = NotificationQQTransport(context)
        transport.start()
        transport.onListenerConnectionChanged(true)

        assertFalse(
            TransportCapability.DELIVERY_LOOKUP in transport.capabilities,
        )
        assertEquals(
            NotificationTransportHealth.CONNECTED,
            transport.health,
        )

        val rejected = transport.onNotificationPosted(
            statusBarNotification(
                packageName = "com.example.other",
                id = 1,
                title = "Other",
                text = "ignored",
            ),
        )
        assertFalse(rejected)

        val accepted = transport.onNotificationPosted(
            statusBarNotification(
                packageName = "com.tencent.mobileqq",
                id = 2,
                title = "Alice",
                text = "hello from QQ",
            ),
        )
        assertTrue(accepted)

        val event = transport.receive()
        assertEquals(
            NotificationQQTransport.accountIdForPackage(
                "com.tencent.mobileqq",
            ),
            event.accountId,
        )
        assertEquals("hello from QQ", event.text)
        assertEquals(
            "TITLE_FALLBACK",
            event.metadata["identity_quality"],
        )
        assertEquals(
            "PACKAGE_ONLY",
            event.metadata["account_identity_quality"],
        )
        assertEquals("system", event.messageType)
        transport.stop()
    }

    @Test
    fun liveRemoteInputActionDispatchesTextAndRemovalExpiresCapability() =
        runBlocking {
            val actionName = "dev.qbot.android.TEST_REMOTE_REPLY"
            val receivedText = AtomicReference<String?>()
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(context: Context?, intent: Intent?) {
                    receivedText.set(
                        RemoteInput.getResultsFromIntent(intent)
                            ?.getCharSequence("reply_text")
                            ?.toString(),
                    )
                }
            }
            context.registerReceiver(
                receiver,
                IntentFilter(actionName),
                Context.RECEIVER_NOT_EXPORTED,
            )

            try {
                val pendingIntent = PendingIntent.getBroadcast(
                    context,
                    7,
                    Intent(actionName).setPackage(context.packageName),
                    PendingIntent.FLAG_UPDATE_CURRENT or
                        PendingIntent.FLAG_MUTABLE,
                )
                val remoteInput = RemoteInput.Builder("reply_text")
                    .setAllowFreeFormInput(true)
                    .build()
                val replyAction = Notification.Action.Builder(
                    android.R.drawable.ic_menu_send,
                    "Reply",
                    pendingIntent,
                )
                    .addRemoteInput(remoteInput)
                    .setSemanticAction(
                        Notification.Action.SEMANTIC_ACTION_REPLY,
                    )
                    .build()

                val sbn = statusBarNotification(
                    packageName = "com.tencent.mobileqq",
                    id = 10,
                    title = "Alice",
                    text = "ping",
                    shortcutId = "qq-conversation-alice",
                    action = replyAction,
                )

                val transport = NotificationQQTransport(context)
                transport.start()
                transport.onListenerConnectionChanged(true)
                assertTrue(transport.onNotificationPosted(sbn))

                val event = transport.receive()
                assertEquals(
                    "APP_SHORTCUT",
                    event.metadata["identity_quality"],
                )
                assertEquals(
                    "true",
                    event.metadata["reply_available"],
                )

                val result = transport.send(
                    OutgoingMessage(
                        accountId = event.accountId,
                        conversationId = event.conversationId,
                        dedupeKey = "reply-test-0001",
                        text = "pong",
                    ),
                )
                shadowOf(Looper.getMainLooper()).idle()

                assertTrue(result.accepted)
                assertNull(result.platformMessageId)
                assertEquals("pong", receivedText.get())

                transport.onNotificationRemoved(sbn)
                val expired = transport.send(
                    OutgoingMessage(
                        accountId = event.accountId,
                        conversationId = event.conversationId,
                        dedupeKey = "reply-test-0002",
                        text = "must not dispatch",
                    ),
                )
                assertFalse(expired.accepted)
                assertTrue(expired.error!!.contains("no live"))
                transport.stop()
            } finally {
                context.unregisterReceiver(receiver)
            }
        }

    private fun statusBarNotification(
        packageName: String,
        id: Int,
        title: String,
        text: String,
        shortcutId: String? = null,
        action: Notification.Action? = null,
    ): StatusBarNotification {
        val builder = Notification.Builder(context, "test-channel")
            .setSmallIcon(android.R.drawable.ic_dialog_email)
            .setContentTitle(title)
            .setContentText(text)

        if (shortcutId != null) {
            builder.setShortcutId(shortcutId)
        }
        if (action != null) {
            builder.addAction(action)
        }

        return StatusBarNotification(
            packageName,
            packageName,
            id,
            "tag-" + id,
            1000,
            2000,
            builder.build(),
            UserHandle.of(0),
            null,
            1_789_900_000_000L + id,
        )
    }
}
