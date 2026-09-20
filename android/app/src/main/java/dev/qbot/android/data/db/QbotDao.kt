package dev.qbot.android.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Upsert

@Dao
interface QbotDao {
    @Query("SELECT value FROM qbot_meta WHERE qbot_meta.key = :key LIMIT 1")
    suspend fun meta(key: String): String?

    @Upsert
    suspend fun upsertMeta(value: MetaEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertInboundIfAbsent(event: InboundEventEntity): Long

    @Query("SELECT * FROM inbound_events WHERE fingerprint = :fingerprint LIMIT 1")
    suspend fun inboundByFingerprint(fingerprint: String): InboundEventEntity?

    @Query("SELECT * FROM inbound_events WHERE event_id = :eventId LIMIT 1")
    suspend fun inboundById(eventId: String): InboundEventEntity?

    @Query("SELECT COUNT(*) FROM inbound_events")
    suspend fun inboundCount(): Int

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertAgentRun(run: AgentRunEntity)

    @Query("SELECT * FROM agent_runs WHERE run_id = :runId LIMIT 1")
    suspend fun agentRun(runId: String): AgentRunEntity?

    @Query(
        "SELECT * FROM agent_runs WHERE trigger_event_id = :eventId LIMIT 1",
    )
    suspend fun agentRunByTriggerEvent(eventId: String): AgentRunEntity?

    @Query("SELECT COUNT(*) FROM agent_runs")
    suspend fun agentRunCount(): Int

    @Query(
        """
        SELECT * FROM agent_runs
        WHERE status IN (:statuses)
        ORDER BY created_at, run_id
        """,
    )
    suspend fun agentRunsByStatus(statuses: List<String>): List<AgentRunEntity>

    @Query(
        """
        UPDATE agent_runs
        SET status = :targetStatus, updated_at = :updatedAt
        WHERE run_id = :runId AND status = :expectedStatus
        """,
    )
    suspend fun transitionAgentRun(
        runId: String,
        expectedStatus: String,
        targetStatus: String,
        updatedAt: String,
    ): Int

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertTask(task: TaskEntity)

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertTaskSteps(steps: List<TaskStepEntity>)

    @Query(
        """
        SELECT * FROM tasks
        WHERE conversation_id = :conversationId
          AND status NOT IN ('COMPLETED', 'CANCELLED')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
    )
    suspend fun activeTask(conversationId: String): TaskEntity?

    @Query("SELECT * FROM task_steps WHERE task_id = :taskId ORDER BY sequence")
    suspend fun taskSteps(taskId: String): List<TaskStepEntity>

    @Query("SELECT * FROM tasks WHERE task_id = :taskId LIMIT 1")
    suspend fun task(taskId: String): TaskEntity?

    @Query(
        """
        UPDATE tasks
        SET status = :status,
            phase = :phase,
            next_action = :nextAction,
            version = version + 1,
            updated_at = :updatedAt
        WHERE task_id = :taskId
          AND version = :expectedVersion
          AND writer_epoch = :writerEpoch
        """,
    )
    suspend fun updateTaskGuarded(
        taskId: String,
        expectedVersion: Long,
        writerEpoch: Long,
        status: String,
        phase: String,
        nextAction: String?,
        updatedAt: String,
    ): Int

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertCheckpoint(checkpoint: TaskCheckpointEntity)

    @Query(
        """
        SELECT * FROM task_checkpoints
        WHERE task_id = :taskId AND task_version = :taskVersion
        ORDER BY created_at DESC
        LIMIT 1
        """,
    )
    suspend fun checkpointForVersion(
        taskId: String,
        taskVersion: Long,
    ): TaskCheckpointEntity?

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertOutboxIfAbsent(message: OutboxMessageEntity): Long

    @Query("SELECT * FROM outbox_messages WHERE outbox_id = :outboxId LIMIT 1")
    suspend fun outbox(outboxId: String): OutboxMessageEntity?

    @Query(
        """
        SELECT * FROM outbox_messages
        WHERE run_id = :runId
        ORDER BY created_at, outbox_id
        """,
    )
    suspend fun outboxForRun(runId: String): List<OutboxMessageEntity>

    @Query(
        """
        SELECT * FROM outbox_messages
        WHERE account_id = :accountId AND dedupe_key = :dedupeKey
        LIMIT 1
        """,
    )
    suspend fun outboxByDedupe(
        accountId: String,
        dedupeKey: String,
    ): OutboxMessageEntity?

    @Query(
        """
        SELECT * FROM outbox_messages
        WHERE status IN (:statuses)
        ORDER BY created_at, outbox_id
        """,
    )
    suspend fun outboxByStatus(statuses: List<String>): List<OutboxMessageEntity>

    @Query(
        """
        UPDATE outbox_messages
        SET status = :targetStatus,
            last_error = :error,
            platform_message_id = CASE
                WHEN :platformMessageId IS NULL THEN platform_message_id
                ELSE :platformMessageId
            END,
            transport_attempts = transport_attempts + :attemptDelta,
            sent_at = CASE
                WHEN :targetStatus = 'SENT' THEN :sentAt
                ELSE sent_at
            END
        WHERE outbox_id = :outboxId
          AND status = :expectedStatus
        """,
    )
    suspend fun transitionOutbox(
        outboxId: String,
        expectedStatus: String,
        targetStatus: String,
        platformMessageId: String?,
        error: String?,
        attemptDelta: Int,
        sentAt: String?,
    ): Int

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertJournal(event: JournalEntity)

    @Query("SELECT COUNT(*) FROM event_journal")
    suspend fun journalCount(): Int

    @Query(
        """
        SELECT * FROM event_journal
        WHERE (:runId IS NULL OR run_id = :runId)
        ORDER BY occurred_at, journal_id
        LIMIT :limit
        """,
    )
    suspend fun journalByRun(runId: String?, limit: Int = 100): List<JournalEntity>

    @Upsert
    suspend fun upsertPersona(persona: PersonaEntity)

    @Query("SELECT * FROM personas WHERE persona_id = :personaId LIMIT 1")
    suspend fun persona(personaId: String): PersonaEntity?

    @Upsert
    suspend fun upsertContact(profile: ContactProfileEntity)

    @Query("SELECT * FROM contact_profiles WHERE contact_id = :contactId LIMIT 1")
    suspend fun contact(contactId: String): ContactProfileEntity?
}
