package dev.qbot.android.runtime

import android.content.Context
import androidx.room.Room
import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.InboundAdmissionRepository
import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.data.db.QbotDatabase
import dev.qbot.android.data.db.QbotMigrations
import dev.qbot.android.domain.NormalizedEvent
import dev.qbot.android.transport.FakeTransport
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [37])
class SendExecutorRoomTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private val databaseName = "qbot-send-test.db"
    private val ids = AtomicInteger(0)
    private val clock = Clock.fixed(
        Instant.parse("2026-09-20T04:00:00Z"),
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
    fun deliveredButUnacknowledgedMessageReconcilesWithoutSecondAttempt() =
        runBlocking {
            val runId = createExecutingRun()
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val effect = outbox.createText(
                runId = runId,
                accountId = "acc-1",
                conversationId = "private:send",
                dedupeKey = "run-send:primary-reply",
                text = "reply exactly once",
            )

            val transport = FakeTransport()
            transport.start()
            transport.makeNextSendUncertainAfterDelivery()
            val sender = SendExecutor(outbox, transport)

            val uncertain = sender.send(effect.outboxId)
            assertEquals("SENDING_UNKNOWN", uncertain.status)
            assertEquals(1, uncertain.transportAttempts)
            assertNotNull(uncertain.platformMessageId)

            val reconciled = sender.reconcile(effect.outboxId)
            assertEquals("SENT", reconciled.status)
            assertEquals(1, reconciled.transportAttempts)
            assertEquals(
                uncertain.platformMessageId,
                reconciled.platformMessageId,
            )

            val repeatedReconcile = sender.reconcile(effect.outboxId)
            assertEquals("SENT", repeatedReconcile.status)
            assertEquals(1, repeatedReconcile.transportAttempts)

            transport.stop()
        }

    private suspend fun createExecutingRun(): String {
        val event = NormalizedEvent(
            eventId = "evt-" + nextId(),
            fingerprint = "fingerprint-send-0123456789abcdef",
            platform = "qq",
            transport = "fake",
            accountId = "acc-1",
            conversationId = "private:send",
            senderId = "contact",
            platformMessageId = "msg-send",
            messageType = "private",
            text = "trigger",
            occurredAt = "2026-09-20T03:59:00Z",
            receivedAt = "2026-09-20T04:00:00Z",
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

    private fun nextId(): String =
        "id-" + ids.incrementAndGet()
}
