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
import dev.qbot.android.transport.routing.AdapterHealth
import dev.qbot.android.transport.routing.AdapterTier
import dev.qbot.android.transport.routing.TransportAdapterBinding
import dev.qbot.android.transport.routing.TransportAdapterSnapshot
import dev.qbot.android.transport.routing.TransportRegistry
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [37], application = Application::class)
class RoutedRecoveryRoomTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private val databaseName = "qbot-routed-recovery-test.db"
    private val ids = AtomicInteger(0)
    private val clock = Clock.fixed(
        Instant.parse("2026-09-20T08:00:00Z"),
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
    fun lookupOnDifferentAdapterCannotReconcileUnknownEffect() = runBlocking {
        val runId = createExecutingRun("cross-adapter")
        val outbox = OutboxRepository(
            database = database,
            clock = clock,
            idFactory = ::nextId,
        )
        val effect = outbox.createText(
            runId = runId,
            accountId = "acc-1",
            conversationId = "private:cross-adapter",
            dedupeKey = "cross-adapter-unknown",
            text = "send once",
        )
        outbox.transition(
            outboxId = effect.outboxId,
            targetStatus = "SENDING",
            incrementAttempt = true,
            attemptTransportId = "notification",
        )
        outbox.transition(
            outboxId = effect.outboxId,
            targetStatus = "SENDING_UNKNOWN",
            error = "ack lost",
        )

        val original = ProbeTransport(
            adapterName = "notification",
            lookupSupported = false,
            deliveryFound = false,
        )
        val other = ProbeTransport(
            adapterName = "accessibility",
            lookupSupported = true,
            deliveryFound = true,
        )
        val registry = registry(original, other)
        val plan = RoutedRecoveryPlanner(
            runs = AgentRunRepository(database.qbotDao(), clock),
            outbox = outbox,
            registry = registry,
        ).plan()

        val item = plan.items.single {
            it.outboxId == effect.outboxId
        }
        assertEquals(RecoveryAction.MANUAL_REVIEW, item.action)
        assertEquals("notification", item.transportId)
        assertEquals(0, original.lookupCalls)
        assertEquals(0, other.lookupCalls)
    }

    @Test
    fun reconciliationCallsOnlyOriginalAdapterRecordedAtSendBoundary() =
        runBlocking {
            val runId = createExecutingRun("exact-adapter")
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val effect = outbox.createText(
                runId = runId,
                accountId = "acc-1",
                conversationId = "private:exact-adapter",
                dedupeKey = "exact-adapter-unknown",
                text = "send once",
            )
            outbox.transition(
                outboxId = effect.outboxId,
                targetStatus = "SENDING",
                incrementAttempt = true,
                attemptTransportId = "origin",
            )
            outbox.transition(
                outboxId = effect.outboxId,
                targetStatus = "SENDING_UNKNOWN",
                error = "ack lost",
            )

            val origin = ProbeTransport(
                adapterName = "origin",
                lookupSupported = true,
                deliveryFound = true,
            )
            val alternate = ProbeTransport(
                adapterName = "alternate",
                lookupSupported = true,
                deliveryFound = true,
            )
            val runs = AgentRunRepository(database.qbotDao(), clock)
            val registry = registry(origin, alternate)
            val report = RoutedRecoveryExecutor(
                planner = RoutedRecoveryPlanner(
                    runs = runs,
                    outbox = outbox,
                    registry = registry,
                ),
                runs = runs,
                outbox = outbox,
                registry = registry,
            ).run(RecoveryMode.ASSIST)

            assertEquals(
                RecoveryOutcome.RECONCILED,
                report.executions.single {
                    it.item.outboxId == effect.outboxId
                }.outcome,
            )
            assertEquals("SENT", outbox.load(effect.outboxId).status)
            assertEquals("SUCCEEDED", runs.load(runId)?.status)
            assertEquals(1, origin.lookupCalls)
            assertEquals(0, alternate.lookupCalls)
            assertEquals(0, origin.sendCalls)
            assertEquals(0, alternate.sendCalls)
        }

    private fun registry(
        vararg transports: ProbeTransport,
    ): TransportRegistry =
        TransportRegistry(
            transports.mapIndexed { index, transport ->
                TransportAdapterBinding(
                    transport = transport,
                    snapshot = {
                        TransportAdapterSnapshot(
                            adapterId = transport.name,
                            tier = if (index == 0) {
                                AdapterTier.STANDARD
                            } else {
                                AdapterTier.ENHANCED
                            },
                            health = AdapterHealth.READY,
                            capabilities = transport.capabilities,
                            priority = 10 + index * 10,
                        )
                    },
                )
            },
        )

    private suspend fun createExecutingRun(
        suffix: String,
    ): String {
        val event = NormalizedEvent(
            eventId = "evt-" + nextId(),
            fingerprint = "fingerprint-routed-recovery-" +
                suffix + "-" + nextId(),
            platform = "qq",
            transport = "routing-test",
            accountId = "acc-1",
            conversationId = "private:" + suffix,
            senderId = "contact",
            platformMessageId = "msg-" + suffix,
            messageType = "private",
            text = "trigger",
            occurredAt = "2026-09-20T07:59:00Z",
            receivedAt = "2026-09-20T08:00:00Z",
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

    private class ProbeTransport(
        private val adapterName: String,
        private val lookupSupported: Boolean,
        private val deliveryFound: Boolean,
    ) : QQTransport {
        var lookupCalls = 0
        var sendCalls = 0

        override val name: String = adapterName

        override val capabilities: Set<TransportCapability> =
            buildSet {
                add(TransportCapability.SEND_TEXT)
                if (lookupSupported) {
                    add(TransportCapability.DELIVERY_LOOKUP)
                }
            }

        override suspend fun start() = Unit
        override suspend fun stop() = Unit

        override suspend fun receive(): IncomingTransportEvent =
            error("receive not used")

        override suspend fun send(
            message: OutgoingMessage,
        ): SendResult {
            sendCalls += 1
            return SendResult(
                accepted = true,
                platformMessageId = adapterName + "-sent",
            )
        }

        override suspend fun lookupDelivery(
            accountId: String,
            dedupeKey: String,
        ): DeliveryLookupResult {
            lookupCalls += 1
            return DeliveryLookupResult(
                found = deliveryFound,
                platformMessageId = if (deliveryFound) {
                    adapterName + "-existing"
                } else {
                    null
                },
            )
        }
    }
}
