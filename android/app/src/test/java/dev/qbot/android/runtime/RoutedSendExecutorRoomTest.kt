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
import dev.qbot.android.transport.routing.AdapterHealth
import dev.qbot.android.transport.routing.AdapterTier
import dev.qbot.android.transport.routing.TransportAdapterBinding
import dev.qbot.android.transport.routing.TransportAdapterSnapshot
import dev.qbot.android.transport.routing.TransportSelector
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
class RoutedSendExecutorRoomTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private val databaseName = "qbot-routed-send-test.db"
    private val ids = AtomicInteger(0)
    private val clock = Clock.fixed(
        Instant.parse("2026-09-20T07:00:00Z"),
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
    fun fallsBackBeforeAttemptAndSendsThroughExactlyOneReadyAdapter() =
        runBlocking {
            val runId = createExecutingRun("pre-send-fallback")
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val effect = outbox.createText(
                runId = runId,
                accountId = "acc-1",
                conversationId = "private:fallback",
                dedupeKey = "fallback-before-send",
                text = "hello",
            )

            val standard = ProbeTransport(
                adapterName = "notification",
                readiness = SendReadiness(
                    SendAvailability.TEMPORARILY_UNAVAILABLE,
                    "no live RemoteInput",
                ),
                result = SendResult(accepted = true),
            )
            val accessibility = ProbeTransport(
                adapterName = "accessibility",
                readiness = SendReadiness(SendAvailability.READY),
                result = SendResult(
                    accepted = true,
                    platformMessageId = "accessibility-1",
                ),
            )
            val sender = RoutedSendExecutor(
                outbox = outbox,
                selector = TransportSelector(
                    listOf(
                        binding(
                            id = "notification",
                            tier = AdapterTier.STANDARD,
                            priority = 10,
                            transport = standard,
                        ),
                        binding(
                            id = "accessibility",
                            tier = AdapterTier.ENHANCED,
                            priority = 20,
                            transport = accessibility,
                        ),
                    ),
                ),
            )

            val result = sender.send(effect.outboxId)

            assertEquals(RoutedSendOutcome.SENT, result.outcome)
            assertEquals("accessibility", result.adapterId)
            assertEquals("SENT", result.outbox.status)
            assertEquals(1, result.outbox.transportAttempts)
            assertEquals(0, standard.sendCalls)
            assertEquals(1, accessibility.sendCalls)
            assertEquals(
                "accessibility",
                outbox.lastAttemptTransportId(effect.outboxId),
            )
        }

    @Test
    fun uncertainPrimaryAttemptNeverFallsThroughToSecondReadyAdapter() =
        runBlocking {
            val runId = createExecutingRun("unknown-no-fallback")
            val outbox = OutboxRepository(
                database = database,
                clock = clock,
                idFactory = ::nextId,
            )
            val effect = outbox.createText(
                runId = runId,
                accountId = "acc-1",
                conversationId = "private:unknown",
                dedupeKey = "unknown-no-fallback",
                text = "send once",
            )

            val primary = ProbeTransport(
                adapterName = "accessibility",
                readiness = SendReadiness(SendAvailability.READY),
                result = SendResult(
                    accepted = false,
                    platformMessageId = "possibly-delivered-1",
                    uncertain = true,
                    error = "acknowledgement lost",
                ),
            )
            val secondary = ProbeTransport(
                adapterName = "experimental",
                readiness = SendReadiness(SendAvailability.READY),
                result = SendResult(
                    accepted = true,
                    platformMessageId = "must-not-send",
                ),
            )
            val sender = RoutedSendExecutor(
                outbox = outbox,
                selector = TransportSelector(
                    listOf(
                        binding(
                            id = "accessibility",
                            tier = AdapterTier.ENHANCED,
                            priority = 10,
                            transport = primary,
                        ),
                        binding(
                            id = "experimental",
                            tier = AdapterTier.EXPERIMENTAL,
                            priority = 20,
                            transport = secondary,
                        ),
                    ),
                ),
            )

            val result = sender.send(effect.outboxId)

            assertEquals(RoutedSendOutcome.SEND_UNKNOWN, result.outcome)
            assertEquals("accessibility", result.adapterId)
            assertEquals("SENDING_UNKNOWN", result.outbox.status)
            assertEquals(1, result.outbox.transportAttempts)
            assertEquals(1, primary.sendCalls)
            assertEquals(0, secondary.sendCalls)
            assertEquals(
                "accessibility",
                outbox.lastAttemptTransportId(effect.outboxId),
            )
        }

    private fun binding(
        id: String,
        tier: AdapterTier,
        priority: Int,
        transport: QQTransport,
    ): TransportAdapterBinding =
        TransportAdapterBinding(
            transport = transport,
            snapshot = {
                TransportAdapterSnapshot(
                    adapterId = id,
                    tier = tier,
                    health = AdapterHealth.READY,
                    capabilities = setOf(TransportCapability.SEND_TEXT),
                    priority = priority,
                )
            },
        )

    private suspend fun createExecutingRun(suffix: String): String {
        val event = NormalizedEvent(
            eventId = "evt-" + nextId(),
            fingerprint = "fingerprint-routed-" + suffix + "-" + nextId(),
            platform = "qq",
            transport = "routing-test",
            accountId = "acc-1",
            conversationId = "private:" + suffix,
            senderId = "contact",
            platformMessageId = "msg-" + suffix,
            messageType = "private",
            text = "trigger",
            occurredAt = "2026-09-20T06:59:00Z",
            receivedAt = "2026-09-20T07:00:00Z",
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
        private val readiness: SendReadiness,
        private val result: SendResult,
    ) : QQTransport {
        var sendCalls = 0

        override val name: String = adapterName
        override val capabilities: Set<TransportCapability> =
            setOf(TransportCapability.SEND_TEXT)

        override suspend fun start() = Unit
        override suspend fun stop() = Unit

        override suspend fun receive(): IncomingTransportEvent =
            error("receive not used")

        override suspend fun checkSendReadiness(
            message: OutgoingMessage,
        ): SendReadiness = readiness

        override suspend fun send(
            message: OutgoingMessage,
        ): SendResult {
            sendCalls += 1
            return result
        }

        override suspend fun lookupDelivery(
            accountId: String,
            dedupeKey: String,
        ): DeliveryLookupResult =
            DeliveryLookupResult(found = false)
    }
}
