package dev.qbot.android.runtime

import android.app.Application
import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Process
import android.service.notification.StatusBarNotification
import androidx.room.Room
import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.InboundAdmissionRepository
import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.data.db.QbotDatabase
import dev.qbot.android.data.db.QbotMigrations
import dev.qbot.android.domain.NormalizedEvent
import dev.qbot.android.transport.notification.NotificationQQTransport
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [37], application = Application::class)
class NotificationRecoveryRoomTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private val databaseName = "qbot-notification-recovery.db"
    private val ids = AtomicInteger(0)
    private val clock = Clock.fixed(
        Instant.parse("2026-09-20T06:00:00Z"),
        ZoneOffset.UTC,
    )

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
        context.deleteDatabase(databaseName)
        database = Room.databaseBuilder(
            context,
            QbotDatabase::class.java,
            databaseName,
        )
            .allowMainThreadQueries()
            .addMigrations(*QbotMigrations.ALL)
            .build()
    }

    @After
    fun tearDown() {
        database.close()
        context.deleteDatabase(databaseName)
    }

    @Test
    fun recoverySendsOnceOnlyWhileLiveReplyActionExists() = runBlocking {
        val actionName = "dev.qbot.android.TEST_RECOVERY_REMOTE_REPLY"
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
                41,
                Intent(actionName).setPackage(context.packageName),
                PendingIntent.FLAG_UPDATE_CURRENT or
                    PendingIntent.FLAG_MUTABLE,
            )
            val remoteInput = RemoteInput.Builder("reply_text")
                .setAllowFreeFormInput(true)
                .build()
            val action = Notification.Action.Builder(
                android.R.drawable.ic_menu_send,
                "Reply",
                pendingIntent,
            )
                .addRemoteInput(remoteInput)
                .setSemanticAction(
                    Notification.Action.SEMANTIC_ACTION_REPLY,
                )
                .build()
            val sbn = statusBarNotification(action)

            val transport = NotificationQQTransport(context)
            transport.start()
            transport.onListenerConnectionChanged(true)
            assertTrue(transport.onNotificationPosted(sbn))
            val notificationEvent = transport.receive()

            val runId = createExecutingRun(
                accountId = notificationEvent.accountId,
                conversationId = notificationEvent.conversationId,
            )
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val liveEffect = outbox.createText(
                runId = runId,
                accountId = notificationEvent.accountId,
                conversationId = notificationEvent.conversationId,
                dedupeKey = "notification-live-effect",
                text = "reply through live action",
            )

            val runs = AgentRunRepository(database.qbotDao(), clock)
            val report = RecoveryExecutor(
                planner = RecoveryPlanner(
                    runs = runs,
                    outbox = outbox,
                    transport = transport,
                ),
                runs = runs,
                outbox = outbox,
                transport = transport,
            ).run(RecoveryMode.ASSIST)

            shadowOf(android.os.Looper.getMainLooper()).idle()

            assertEquals(
                RecoveryOutcome.SENT,
                report.executions.single {
                    it.item.outboxId == liveEffect.outboxId
                }.outcome,
            )
            assertEquals("SENT", outbox.load(liveEffect.outboxId).status)
            assertEquals(1, outbox.load(liveEffect.outboxId).transportAttempts)
            assertEquals("reply through live action", receivedText.get())

            val expiredEffect = outbox.createText(
                runId = runId,
                accountId = notificationEvent.accountId,
                conversationId = notificationEvent.conversationId,
                dedupeKey = "notification-expired-effect",
                text = "must stay pending",
            )
            transport.onNotificationRemoved(sbn)

            val secondReport = RecoveryExecutor(
                planner = RecoveryPlanner(
                    runs = runs,
                    outbox = outbox,
                    transport = transport,
                ),
                runs = runs,
                outbox = outbox,
                transport = transport,
            ).run(RecoveryMode.ASSIST)

            assertEquals(
                RecoveryOutcome.DEFERRED,
                secondReport.executions.single {
                    it.item.outboxId == expiredEffect.outboxId
                }.outcome,
            )
            assertEquals(
                "PENDING",
                outbox.load(expiredEffect.outboxId).status,
            )
            assertEquals(
                0,
                outbox.load(expiredEffect.outboxId).transportAttempts,
            )
            transport.stop()
        } finally {
            context.unregisterReceiver(receiver)
        }
    }

    private suspend fun createExecutingRun(
        accountId: String,
        conversationId: String,
    ): String {
        val event = NormalizedEvent(
            eventId = "evt-" + nextId(),
            fingerprint = "fingerprint-notification-recovery-" + nextId(),
            platform = "qq",
            transport = "android-notification",
            accountId = accountId,
            conversationId = conversationId,
            senderId = null,
            platformMessageId = "notification-trigger-" + nextId(),
            messageType = "system",
            text = "trigger",
            occurredAt = "2026-09-20T05:59:00Z",
            receivedAt = "2026-09-20T06:00:00Z",
        )
        val admitted = InboundAdmissionRepository(
            database = database,
            idFactory = ::nextId,
        ).admit(event)
        val runs = AgentRunRepository(database.qbotDao(), clock)
        runs.transition(admitted.runId, "RESTORING")
        runs.transition(admitted.runId, "REASONING")
        runs.transition(admitted.runId, "EXECUTING")
        return admitted.runId
    }

    private fun statusBarNotification(
        action: Notification.Action,
    ): StatusBarNotification {
        val notification = Notification.Builder(
            context,
            "test-channel",
        )
            .setSmallIcon(android.R.drawable.ic_dialog_email)
            .setContentTitle("Alice")
            .setContentText("ping")
            .setShortcutId("qq-conversation-recovery")
            .addAction(action)
            .build()

        return StatusBarNotification(
            "com.tencent.mobileqq",
            "com.tencent.mobileqq",
            41,
            "tag-41",
            1000,
            2000,
            0,
            notification,
            Process.myUserHandle(),
            1_789_900_000_041L,
        )
    }

    private fun nextId(): String =
        "id-" + ids.incrementAndGet()
}
