package dev.qbot.android.runtime

import android.content.Context
import androidx.room.Room
import dev.qbot.android.data.DurableStateRepository
import dev.qbot.android.data.InboundAdmissionRepository
import dev.qbot.android.data.db.QbotDatabase
import dev.qbot.android.data.db.QbotMigrations
import dev.qbot.android.data.db.TaskCheckpointEntity
import dev.qbot.android.data.db.TaskEntity
import dev.qbot.android.transport.FakeTransport
import dev.qbot.android.transport.IncomingTransportEvent
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [37])
class AndroidCoreRoomIntegrationTest {
    private lateinit var context: Context
    private lateinit var database: QbotDatabase
    private val databaseName = "qbot-room-e2e.db"

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
    fun duplicateTransportEventCreatesOneEventOneRunAndSurvivesReopen() = runBlocking {
        val transport = FakeTransport()
        val incoming = IncomingTransportEvent(
            accountId = "acc-1",
            conversationId = "private:42",
            senderId = "contact-42",
            platformMessageId = "msg-42",
            text = "hello",
            occurredAt = Instant.parse("2026-09-20T00:00:00Z"),
        )
        transport.inject(incoming)
        transport.inject(incoming)
        transport.start()

        val ids = AtomicInteger(0)
        val core = AndroidCore(
            transport = transport,
            admission = InboundAdmissionRepository(
                database = database,
                idFactory = { "id-" + ids.incrementAndGet() },
            ),
            stateRepository = DurableStateRepository(database.qbotDao()),
            normalizer = EventNormalizer(
                transportName = transport.name,
                clock = Clock.fixed(
                    Instant.parse("2026-09-20T00:00:10Z"),
                    ZoneOffset.UTC,
                ),
                idFactory = { "event-" + ids.incrementAndGet() },
            ),
        )

        val first = core.processOne()
        val duplicate = core.processOne()
        transport.stop()

        assertTrue(first.admission.isNew)
        assertFalse(duplicate.admission.isNew)
        assertEquals(first.admission.eventId, duplicate.admission.eventId)
        assertEquals(first.admission.runId, duplicate.admission.runId)
        assertEquals(1, database.qbotDao().inboundCount())
        assertEquals(1, database.qbotDao().agentRunCount())
        assertEquals(2, database.qbotDao().journalCount())
        assertEquals("CREATED", first.restored.run.status)
        assertNull(first.restored.activeTask)
        assertNull(first.restored.checkpoint)

        val runId = first.admission.runId
        val eventId = first.admission.eventId
        database.close()

        database = openDatabase()
        val restored = DurableStateRepository(database.qbotDao()).restore(runId)

        assertEquals(runId, restored.run.runId)
        assertEquals(eventId, restored.triggerEvent.eventId)
        assertEquals("hello", restored.triggerEvent.text)
        assertEquals(1, database.qbotDao().inboundCount())
        assertEquals(1, database.qbotDao().agentRunCount())
    }

    @Test
    fun restartRestoresOnlyCheckpointMatchingCurrentTaskVersion() = runBlocking {
        val transport = FakeTransport()
        val incoming = IncomingTransportEvent(
            accountId = "acc-1",
            conversationId = "private:task",
            senderId = "contact-task",
            platformMessageId = "msg-task",
            text = "continue task",
            occurredAt = Instant.parse("2026-09-20T01:00:00Z"),
        )
        transport.inject(incoming)
        transport.start()

        val ids = AtomicInteger(100)
        val core = AndroidCore(
            transport = transport,
            admission = InboundAdmissionRepository(
                database = database,
                idFactory = { "id-" + ids.incrementAndGet() },
            ),
            stateRepository = DurableStateRepository(database.qbotDao()),
            normalizer = EventNormalizer(
                transportName = transport.name,
                clock = Clock.fixed(
                    Instant.parse("2026-09-20T01:00:10Z"),
                    ZoneOffset.UTC,
                ),
                idFactory = { "event-" + ids.incrementAndGet() },
            ),
        )
        val admitted = core.processOne()
        transport.stop()

        val now = "2026-09-20T01:01:00Z"
        database.qbotDao().insertTask(
            TaskEntity(
                taskId = "task-1",
                schemaVersion = "0.1.0",
                conversationId = "private:task",
                parentTaskId = null,
                goal = "finish durable work",
                status = "RUNNING",
                phase = "phase-2",
                constraintsJson = "[]",
                decisionsJson = "[\"keep state durable\"]",
                blockersJson = "[]",
                nextAction = "resume phase 2",
                writerEpoch = 0,
                version = 2,
                createdAt = now,
                updatedAt = now,
            ),
        )
        database.qbotDao().insertCheckpoint(
            TaskCheckpointEntity(
                checkpointId = "checkpoint-old",
                schemaVersion = "0.1.0",
                taskId = "task-1",
                agentRunId = admitted.admission.runId,
                taskVersion = 1,
                summary = "stale checkpoint",
                completedStepIdsJson = "[]",
                pendingStepIdsJson = "[]",
                currentStepId = null,
                decisionsJson = "[]",
                blockersJson = "[]",
                nextAction = "old next action",
                contextDigest = null,
                writerEpoch = 0,
                createdAt = "2026-09-20T01:00:30Z",
            ),
        )
        database.qbotDao().insertCheckpoint(
            TaskCheckpointEntity(
                checkpointId = "checkpoint-current",
                schemaVersion = "0.1.0",
                taskId = "task-1",
                agentRunId = admitted.admission.runId,
                taskVersion = 2,
                summary = "current checkpoint",
                completedStepIdsJson = "[\"step-1\"]",
                pendingStepIdsJson = "[\"step-2\"]",
                currentStepId = "step-2",
                decisionsJson = "[\"keep state durable\"]",
                blockersJson = "[]",
                nextAction = "resume phase 2",
                contextDigest = "digest-v2",
                writerEpoch = 0,
                createdAt = now,
            ),
        )

        val runId = admitted.admission.runId
        database.close()
        database = openDatabase()

        val restored = DurableStateRepository(database.qbotDao()).restore(runId)

        assertEquals("task-1", restored.activeTask?.taskId)
        assertEquals(2L, restored.activeTask?.version)
        assertEquals("checkpoint-current", restored.checkpoint?.checkpointId)
        assertEquals("current checkpoint", restored.checkpoint?.summary)
        assertEquals("resume phase 2", restored.checkpoint?.nextAction)
    }

    private fun openDatabase(): QbotDatabase =
        Room.databaseBuilder(
            context,
            QbotDatabase::class.java,
            databaseName,
        )
            .allowMainThreadQueries()
            .addMigrations(*QbotMigrations.ALL)
            .build()
}
