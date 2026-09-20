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
class RecoveryPlannerRoomTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private val databaseName = "qbot-recovery-test.db"
    private val ids = AtomicInteger(0)
    private val clock = Clock.fixed(
        Instant.parse("2026-09-20T03:00:00Z"),
        ZoneOffset.UTC,
    )

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
        context.deleteDatabase(databaseName)
        database = openDatabase()
    }

    @After
    fun tearDown() {
        database.close()
        context.deleteDatabase(databaseName)
    }

    @Test
    fun interruptedSendingBecomesUnknownAndPlansReconcileWhenLookupExists() =
        runBlocking {
            val runId = createExecutingRun("lookup")
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val effect = outbox.createText(
                runId = runId,
                accountId = "acc-1",
                conversationId = "private:lookup",
                dedupeKey = "dedupe-lookup",
                text = "hello",
            )
            outbox.transition(
                effect.outboxId,
                "SENDING",
                incrementAttempt = true,
            )

            val planner = RecoveryPlanner(
                runs = AgentRunRepository(database.qbotDao(), clock),
                outbox = outbox,
                transport = CapabilityTransport(
                    setOf(TransportCapability.DELIVERY_LOOKUP),
                ),
            )
            val plan = planner.plan()

            val recovered = outbox.load(effect.outboxId)
            assertEquals("SENDING_UNKNOWN", recovered.status)
            assertEquals(1, recovered.transportAttempts)
            assertEquals(
                listOf(effect.outboxId),
                plan.interruptedSendsReclassified,
            )
            assertEquals(
                RecoveryAction.RECONCILE_UNKNOWN,
                plan.items.single { it.outboxId == effect.outboxId }.action,
            )
        }

    @Test
    fun unknownWithoutLookupRequiresManualReviewAndNeverReturnsSendPending() =
        runBlocking {
            val runId = createExecutingRun("manual")
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val effect = outbox.createText(
                runId = runId,
                accountId = "acc-1",
                conversationId = "private:manual",
                dedupeKey = "dedupe-manual",
                text = "hello",
            )
            outbox.transition(
                effect.outboxId,
                "SENDING",
                incrementAttempt = true,
            )
            outbox.transition(
                effect.outboxId,
                "SENDING_UNKNOWN",
                error = "lost acknowledgement",
            )

            val plan = RecoveryPlanner(
                runs = AgentRunRepository(database.qbotDao(), clock),
                outbox = outbox,
                transport = CapabilityTransport(emptySet()),
            ).plan()

            val item = plan.items.single { it.outboxId == effect.outboxId }
            assertEquals(RecoveryAction.MANUAL_REVIEW, item.action)
            assertTrue(
                plan.items.none {
                    it.outboxId == effect.outboxId &&
                        it.action == RecoveryAction.SEND_PENDING
                },
            )
            assertEquals(1, outbox.load(effect.outboxId).transportAttempts)
        }

    @Test
    fun sentExecutingRunPlansLocalFinalizeWithoutAnyNewSend() = runBlocking {
        val runId = createExecutingRun("sent")
        val outbox = OutboxRepository(
            database = database,
            clock = clock,
            idFactory = ::nextId,
        )
        val effect = outbox.createText(
            runId = runId,
            accountId = "acc-1",
            conversationId = "private:sent",
            dedupeKey = "dedupe-sent",
            text = "hello",
        )
        outbox.transition(
            effect.outboxId,
            "SENDING",
            incrementAttempt = true,
        )
        outbox.transition(
            effect.outboxId,
            "SENT",
            platformMessageId = "platform-1",
        )

        val plan = RecoveryPlanner(
            runs = AgentRunRepository(database.qbotDao(), clock),
            outbox = outbox,
            transport = CapabilityTransport(emptySet()),
        ).plan()

        assertEquals(
            RecoveryAction.FINALIZE_SENT_RUN,
            plan.items.single().action,
        )
        assertEquals(runId, plan.items.single().runId)
        assertEquals(1, outbox.load(effect.outboxId).transportAttempts)
    }

    @Test
    fun pendingEffectIsEligibleForOneSafeSendAttempt() = runBlocking {
        val runId = createExecutingRun("pending")
        val outbox = OutboxRepository(
            database = database,
            clock = clock,
            idFactory = ::nextId,
        )
        val effect = outbox.createText(
            runId = runId,
            accountId = "acc-1",
            conversationId = "private:pending",
            dedupeKey = "dedupe-pending",
            text = "hello",
        )

        val plan = RecoveryPlanner(
            runs = AgentRunRepository(database.qbotDao(), clock),
            outbox = outbox,
            transport = CapabilityTransport(emptySet()),
        ).plan()

        assertEquals(
            RecoveryAction.SEND_PENDING,
            plan.items.single { it.outboxId == effect.outboxId }.action,
        )
        assertEquals("PENDING", outbox.load(effect.outboxId).status)
        assertEquals(0, outbox.load(effect.outboxId).transportAttempts)
    }

    private suspend fun createExecutingRun(suffix: String): String {
        val event = NormalizedEvent(
            eventId = "evt-" + nextId(),
            fingerprint = "fingerprint-" + suffix + "-0123456789abcdef",
            platform = "qq",
            transport = "fake",
            accountId = "acc-1",
            conversationId = "private:" + suffix,
            senderId = "contact",
            platformMessageId = "msg-" + suffix,
            messageType = "private",
            text = "hello",
            occurredAt = "2026-09-20T02:59:00Z",
            receivedAt = "2026-09-20T03:00:00Z",
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

    private fun openDatabase(): QbotDatabase =
        Room.databaseBuilder(
            context,
            QbotDatabase::class.java,
            databaseName,
        )
            .allowMainThreadQueries()
            .addMigrations(*QbotMigrations.ALL)
            .build()

    private class CapabilityTransport(
        override val capabilities: Set<TransportCapability>,
    ) : QQTransport {
        override val name: String = "capability-test"

        override suspend fun start() = Unit
        override suspend fun stop() = Unit

        override suspend fun receive(): IncomingTransportEvent =
            error("receive is not used")

        override suspend fun send(message: OutgoingMessage): SendResult =
            error("send must not be called by RecoveryPlanner")

        override suspend fun lookupDelivery(
            accountId: String,
            dedupeKey: String,
        ): DeliveryLookupResult =
            error("lookup is not called during planning")
    }
}
