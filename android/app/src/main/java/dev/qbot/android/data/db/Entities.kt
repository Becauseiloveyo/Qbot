package dev.qbot.android.data.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "qbot_meta")
data class MetaEntity(
    @PrimaryKey val key: String,
    val value: String,
)

@Entity(
    tableName = "inbound_events",
    indices = [
        Index(value = ["fingerprint"], unique = true),
        Index(value = ["account_id", "conversation_id", "occurred_at"]),
    ],
)
data class InboundEventEntity(
    @PrimaryKey
    @ColumnInfo(name = "event_id")
    val eventId: String,
    val fingerprint: String,
    @ColumnInfo(name = "schema_version")
    val schemaVersion: String,
    val platform: String,
    val transport: String?,
    @ColumnInfo(name = "account_id")
    val accountId: String,
    @ColumnInfo(name = "conversation_id")
    val conversationId: String,
    @ColumnInfo(name = "sender_id")
    val senderId: String?,
    @ColumnInfo(name = "platform_message_id")
    val platformMessageId: String?,
    @ColumnInfo(name = "event_type")
    val eventType: String,
    @ColumnInfo(name = "message_type")
    val messageType: String?,
    val text: String?,
    @ColumnInfo(name = "content_ref")
    val contentRef: String?,
    @ColumnInfo(name = "reply_to_message_id")
    val replyToMessageId: String?,
    @ColumnInfo(name = "occurred_at")
    val occurredAt: String,
    @ColumnInfo(name = "received_at")
    val receivedAt: String,
    @ColumnInfo(name = "raw_ref")
    val rawRef: String?,
    @ColumnInfo(name = "metadata_json")
    val metadataJson: String = "{}",
)

@Entity(
    tableName = "agent_runs",
    foreignKeys = [
        ForeignKey(
            entity = InboundEventEntity::class,
            parentColumns = ["event_id"],
            childColumns = ["trigger_event_id"],
            onDelete = ForeignKey.RESTRICT,
        ),
    ],
    indices = [
        Index(value = ["trigger_event_id"], unique = true),
        Index(value = ["conversation_id", "created_at"]),
    ],
)
data class AgentRunEntity(
    @PrimaryKey
    @ColumnInfo(name = "run_id")
    val runId: String,
    @ColumnInfo(name = "schema_version")
    val schemaVersion: String,
    @ColumnInfo(name = "conversation_id")
    val conversationId: String,
    @ColumnInfo(name = "trigger_event_id")
    val triggerEventId: String,
    @ColumnInfo(name = "task_id")
    val taskId: String?,
    val status: String,
    @ColumnInfo(name = "model_profile")
    val modelProfile: String?,
    @ColumnInfo(name = "writer_epoch")
    val writerEpoch: Long = 0,
    @ColumnInfo(name = "created_at")
    val createdAt: String,
    @ColumnInfo(name = "updated_at")
    val updatedAt: String,
)

@Entity(
    tableName = "tasks",
    indices = [
        Index(value = ["conversation_id", "updated_at"]),
    ],
)
data class TaskEntity(
    @PrimaryKey
    @ColumnInfo(name = "task_id")
    val taskId: String,
    @ColumnInfo(name = "schema_version")
    val schemaVersion: String,
    @ColumnInfo(name = "conversation_id")
    val conversationId: String,
    @ColumnInfo(name = "parent_task_id")
    val parentTaskId: String?,
    val goal: String,
    val status: String,
    val phase: String,
    @ColumnInfo(name = "constraints_json")
    val constraintsJson: String = "[]",
    @ColumnInfo(name = "decisions_json")
    val decisionsJson: String = "[]",
    @ColumnInfo(name = "blockers_json")
    val blockersJson: String = "[]",
    @ColumnInfo(name = "next_action")
    val nextAction: String?,
    @ColumnInfo(name = "writer_epoch")
    val writerEpoch: Long = 0,
    val version: Long,
    @ColumnInfo(name = "created_at")
    val createdAt: String,
    @ColumnInfo(name = "updated_at")
    val updatedAt: String,
)

@Entity(
    tableName = "task_steps",
    foreignKeys = [
        ForeignKey(
            entity = TaskEntity::class,
            parentColumns = ["task_id"],
            childColumns = ["task_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [
        Index(value = ["task_id", "sequence"], unique = true),
        Index(value = ["task_id", "status"]),
    ],
)
data class TaskStepEntity(
    @PrimaryKey
    @ColumnInfo(name = "step_id")
    val stepId: String,
    @ColumnInfo(name = "task_id")
    val taskId: String,
    val sequence: Int,
    val description: String,
    val status: String,
    val result: String?,
    val error: String?,
    @ColumnInfo(name = "started_at")
    val startedAt: String?,
    @ColumnInfo(name = "completed_at")
    val completedAt: String?,
)

@Entity(
    tableName = "task_checkpoints",
    foreignKeys = [
        ForeignKey(
            entity = TaskEntity::class,
            parentColumns = ["task_id"],
            childColumns = ["task_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [
        Index(value = ["task_id", "created_at"]),
        Index(value = ["task_id", "task_version"]),
    ],
)
data class TaskCheckpointEntity(
    @PrimaryKey
    @ColumnInfo(name = "checkpoint_id")
    val checkpointId: String,
    @ColumnInfo(name = "schema_version")
    val schemaVersion: String,
    @ColumnInfo(name = "task_id")
    val taskId: String,
    @ColumnInfo(name = "agent_run_id")
    val agentRunId: String?,
    @ColumnInfo(name = "task_version")
    val taskVersion: Long,
    val summary: String,
    @ColumnInfo(name = "completed_step_ids_json")
    val completedStepIdsJson: String = "[]",
    @ColumnInfo(name = "pending_step_ids_json")
    val pendingStepIdsJson: String = "[]",
    @ColumnInfo(name = "current_step_id")
    val currentStepId: String?,
    @ColumnInfo(name = "decisions_json")
    val decisionsJson: String = "[]",
    @ColumnInfo(name = "blockers_json")
    val blockersJson: String = "[]",
    @ColumnInfo(name = "next_action")
    val nextAction: String?,
    @ColumnInfo(name = "context_digest")
    val contextDigest: String?,
    @ColumnInfo(name = "writer_epoch")
    val writerEpoch: Long = 0,
    @ColumnInfo(name = "created_at")
    val createdAt: String,
)

@Entity(
    tableName = "outbox_messages",
    foreignKeys = [
        ForeignKey(
            entity = AgentRunEntity::class,
            parentColumns = ["run_id"],
            childColumns = ["run_id"],
            onDelete = ForeignKey.RESTRICT,
        ),
    ],
    indices = [
        Index(value = ["account_id", "dedupe_key"], unique = true),
        Index(value = ["run_id"]),
        Index(value = ["status", "created_at"]),
    ],
)
data class OutboxMessageEntity(
    @PrimaryKey
    @ColumnInfo(name = "outbox_id")
    val outboxId: String,
    @ColumnInfo(name = "schema_version")
    val schemaVersion: String,
    @ColumnInfo(name = "run_id")
    val runId: String,
    @ColumnInfo(name = "account_id")
    val accountId: String,
    @ColumnInfo(name = "conversation_id")
    val conversationId: String,
    @ColumnInfo(name = "dedupe_key")
    val dedupeKey: String,
    val status: String,
    @ColumnInfo(name = "payload_kind")
    val payloadKind: String,
    @ColumnInfo(name = "payload_text")
    val payloadText: String?,
    @ColumnInfo(name = "content_ref")
    val contentRef: String?,
    @ColumnInfo(name = "reply_to_message_id")
    val replyToMessageId: String?,
    @ColumnInfo(name = "platform_message_id")
    val platformMessageId: String?,
    @ColumnInfo(name = "transport_attempts")
    val transportAttempts: Int = 0,
    @ColumnInfo(name = "last_error")
    val lastError: String?,
    @ColumnInfo(name = "writer_epoch")
    val writerEpoch: Long = 0,
    @ColumnInfo(name = "created_at")
    val createdAt: String,
    @ColumnInfo(name = "sent_at")
    val sentAt: String?,
)

@Entity(
    tableName = "event_journal",
    indices = [
        Index(value = ["conversation_id", "occurred_at"]),
        Index(value = ["task_id", "occurred_at"]),
        Index(value = ["run_id", "occurred_at"]),
    ],
)
data class JournalEntity(
    @PrimaryKey
    @ColumnInfo(name = "journal_id")
    val journalId: String,
    @ColumnInfo(name = "schema_version")
    val schemaVersion: String,
    @ColumnInfo(name = "event_type")
    val eventType: String,
    val actor: String,
    @ColumnInfo(name = "account_id")
    val accountId: String?,
    @ColumnInfo(name = "conversation_id")
    val conversationId: String?,
    @ColumnInfo(name = "task_id")
    val taskId: String?,
    @ColumnInfo(name = "run_id")
    val runId: String?,
    @ColumnInfo(name = "related_id")
    val relatedId: String?,
    @ColumnInfo(name = "payload_json")
    val payloadJson: String = "{}",
    @ColumnInfo(name = "occurred_at")
    val occurredAt: String,
)

@Entity(tableName = "personas")
data class PersonaEntity(
    @PrimaryKey
    @ColumnInfo(name = "persona_id")
    val personaId: String,
    @ColumnInfo(name = "identity_summary")
    val identitySummary: String = "",
    @ColumnInfo(name = "style_rules_json")
    val styleRulesJson: String = "[]",
    @ColumnInfo(name = "hard_constraints_json")
    val hardConstraintsJson: String = "[]",
    val version: Long = 1,
    @ColumnInfo(name = "updated_at")
    val updatedAt: String,
)

@Entity(
    tableName = "contact_profiles",
    foreignKeys = [
        ForeignKey(
            entity = PersonaEntity::class,
            parentColumns = ["persona_id"],
            childColumns = ["persona_id"],
            onDelete = ForeignKey.SET_NULL,
        ),
    ],
    indices = [
        Index(value = ["persona_id"]),
    ],
)
data class ContactProfileEntity(
    @PrimaryKey
    @ColumnInfo(name = "contact_id")
    val contactId: String,
    val relation: String = "",
    @ColumnInfo(name = "stable_facts_json")
    val stableFactsJson: String = "[]",
    @ColumnInfo(name = "style_overrides_json")
    val styleOverridesJson: String = "[]",
    @ColumnInfo(name = "persona_id")
    val personaId: String?,
    val version: Long = 1,
    @ColumnInfo(name = "updated_at")
    val updatedAt: String,
)
