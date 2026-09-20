package dev.qbot.android.runtime

import android.app.Application
import android.content.Context
import androidx.room.Room
import dev.qbot.android.data.AgentRunRepository
import dev.qbot.android.data.InboundAdmissionRepository
import dev.qbot.android.data.OutboxRepository
import dev.qbot.android.data.db.QbotDatabase
import dev.qbot.android.data.db.QbotMigrations
import dev.qbot.android.domain.NormalizedEvent
import dev.qbot.android.transport.DeliveryLookupResult
import dev.qbot.android.transport.IncomingTransportEvent
import dev.qbot.android.transport.OutgoingMessage
import dev.qbot.android.transport.QQTransport
import dev.qbot.android.transport.SendAvailability
import dev.qbot.android.transport.SendReadiness
import dev.qbot.android.transport.SendResult
import dev.qbot.android.transport.TransportCapability
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [37], application = Application::class)
class RecoveryExecutorRoomTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private val databaseName = "qbot-recovery-executor-test.db"
    private val ids = AtomicInteger(0)
    private val clock = Clock.fixed(
        Instant.parse("2026-09-20T05:00:00Z"),
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
    fun pendingEffectStaysPendingWhenTransportIsTemporarilyUnavailable() =
        runBlocking {
            val runId = createExecutingRun("unavailable")
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val effect = outbox.createText(
                runId = runId,
                accountId = "acc-1",
                conversationId = "private:unavailable",
                dedupeKey = "pending-unavailable",
                text = "reply later",
            )
            val transport = UnavailableTransport()

            val report = RecoveryExecutor(
                planner = RecoveryPlanner(
                    runs = AgentRunRepository(database.qbotDao(), clock),
                    outbox = outbox,
                    transport = transport,
                ),
                runs = AgentRunRepository(database.qbotDao(), clock),
                outbox = outbox,
                transport = transport,
            ).run(RecoveryMode.ASSIST)

            val execution = report.executions.single {
                it.item.outboxId == effect.outboxId
            }
            assertEquals(RecoveryOutcome.DEFERRED, execution.outcome)
            assertTrue(execution.detail.contains("live reply action"))
            assertEquals("PENDING", outbox.load(effect.outboxId).status)
            assertEquals(0, outbox.load(effect.outboxId).transportAttempts)
            assertEquals(0, transport.sendCalls)
        }

    @Test
    fun sentExecutingRunFinalizesLocallyWithoutCallingTransport() = runBlocking {
        val runId = createExecutingRun("finalize")
        val outbox = OutboxRepository(
            database = database,
            clock = clock,
            idFactory = ::nextId,
        )
        val effect = outbox.createText(
            runId = runId,
            accountId = "acc-1",
            conversationId = "private:finalize",
            dedupeKey = "already-sent-effect",
            text = "already delivered",
        )
        outbox.transition(
            effect.outboxId,
            "SENDING",
            incrementAttempt = true,
        )
        outbox.transition(
            effect.outboxId,
            "SENT",
            platformMessageId = "platform-42",
        )

        val transport = UnavailableTransport()
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

        assertEquals(
            RecoveryOutcome.FINALIZED,
            report.executions.single().outcome,
        )
        assertEquals("SUCCEEDED", runs.load(runId)?.status)
        assertEquals(1, outbox.load(effect.outboxId).transportAttempts)
        assertEquals(0, transport.sendCalls)
    }

    @Test
    fun observeModeReportsButDoesNotSendPendingEffect() = runBlocking {
        val runId = createExecutingRun("observe")
        val outbox = OutboxRepository(
            database = database,
            clock = clock,
            idFactory = ::nextId,
        )
        val effect = outbox.createText(
            runId = runId,
            accountId = "acc-1",
            conversationId = "private:observe",
            dedupeKey = "observe-only-effect",
            text = "do not send",
        )
        val transport = ReadyTransport()

        val report = RecoveryExecutor(
            planner = RecoveryPlanner(
                runs = AgentRunRepository(database.qbotDao(), clock),
                outbox = outbox,
                transport = transport,
            ),
            runs = AgentRunRepository(database.qbotDao(), clock),
            outbox = outbox,
            transport = transport,
        ).run(RecoveryMode.OBSERVE)

        assertEquals(
            RecoveryOutcome.REPORTED,
            report.executions.single {
                it.item.outboxId == effect.outboxId
            }.outcome,
        )
        assertEquals("PENDING", outbox.load(effect.outboxId).status)
        assertEquals(0, outbox.load(effect.outboxId).transportAttempts)
        assertEquals(0, transport.sendCalls)
    }

    private suspend fun createExecutingRun(suffix: String): String {
        val event = NormalizedEvent(
            eventId = "evt-" + nextId(),
            fingerprint = "fingerprint-executor-" + suffix + "-0123456789",
            platform = "qq",
            transport = "fake",
            accountId = "acc-1",
            conversationId = "private:" + suffix,
            senderId = "contact",
            platformMessageId = "msg-" + suffix,
            messageType = "private",
            text = "trigger",
            occurredAt = "2026-09-20T04:59:00Z",
            receivedAt = "2026-09-20T05:00:00Z",
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

    private open class ReadyTransport : QQTransport {
        var sendCalls: Int = 0

        override val name: String = "ready-test"
        override val capabilities: Set<TransportCapability> =
            setOf(TransportCapability.SEND_TEXT)

        override suspend fun start() = Unit
        override suspend fun stop() = Unit

        override suspend fun receive(): IncomingTransportEvent =
            error("receive is not used")

        override suspend fun send(message: OutgoingMessage): SendResult {
            sendCalls += 1
            return SendResult(
                accepted = true,
                platformMessageId = "sent-" + sendCalls,
            )
        }

        override suspend fun lookupDelivery(
            accountId: String,
            dedupeKey: String,
        ): DeliveryLookupResult =
            DeliveryLookupResult(found = false)
    }

    private class UnavailableTransport : ReadyTransport() {
        override suspend fun checkSendReadiness(
            message: OutgoingMessage,
        ): SendReadiness =
            SendReadiness(
                SendAvailability.TEMPORARILY_UNAVAILABLE,
                "no live reply action",
            )
    }
}
