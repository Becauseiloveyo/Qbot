from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

qbot_meta = Table(
    "qbot_meta",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)

inbound_events = Table(
    "inbound_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("fingerprint", String, nullable=False, unique=True),
    Column("schema_version", String, nullable=False),
    Column("platform", String, nullable=False),
    Column("transport", String),
    Column("account_id", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("sender_id", String),
    Column("platform_message_id", String),
    Column("event_type", String, nullable=False),
    Column("message_type", String),
    Column("text", Text),
    Column("content_ref", String),
    Column("reply_to_message_id", String),
    Column("occurred_at", String, nullable=False),
    Column("received_at", String, nullable=False),
    Column("raw_ref", String),
    Column("metadata_json", Text, nullable=False, default="{}"),
    UniqueConstraint(
        "account_id",
        "conversation_id",
        "event_id",
        name="uq_inbound_event_identity",
    ),
)

agent_runs = Table(
    "agent_runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("schema_version", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column(
        "trigger_event_id",
        String,
        ForeignKey("inbound_events.event_id"),
        nullable=False,
        unique=True,
    ),
    Column("task_id", String),
    Column("status", String, nullable=False),
    Column("model_profile", String),
    Column("writer_epoch", Integer, nullable=False, default=0),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

outbox_messages = Table(
    "outbox_messages",
    metadata,
    Column("outbox_id", String, primary_key=True),
    Column("schema_version", String, nullable=False),
    Column("run_id", String, ForeignKey("agent_runs.run_id"), nullable=False),
    Column("account_id", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("dedupe_key", String, nullable=False),
    Column("status", String, nullable=False),
    Column("payload_kind", String, nullable=False),
    Column("payload_text", Text),
    Column("content_ref", String),
    Column("reply_to_message_id", String),
    Column("platform_message_id", String),
    Column("transport_attempts", Integer, nullable=False, default=0),
    Column("last_error", Text),
    Column("writer_epoch", Integer, nullable=False, default=0),
    Column("created_at", String, nullable=False),
    Column("sent_at", String),
    UniqueConstraint(
        "account_id",
        "dedupe_key",
        name="uq_outbox_account_dedupe",
    ),
)

event_journal = Table(
    "event_journal",
    metadata,
    Column("journal_id", String, primary_key=True),
    Column("schema_version", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("account_id", String),
    Column("conversation_id", String),
    Column("task_id", String),
    Column("run_id", String),
    Column("related_id", String),
    Column("payload_json", Text, nullable=False, default="{}"),
    Column("occurred_at", String, nullable=False),
)


tasks = Table(
    "tasks",
    metadata,
    Column("task_id", String, primary_key=True),
    Column("schema_version", String, nullable=False),
    Column("conversation_id", String, nullable=False),
    Column("parent_task_id", String),
    Column("goal", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("phase", String, nullable=False),
    Column("constraints_json", Text, nullable=False, default="[]"),
    Column("decisions_json", Text, nullable=False, default="[]"),
    Column("blockers_json", Text, nullable=False, default="[]"),
    Column("next_action", Text),
    Column("writer_epoch", Integer, nullable=False, default=0),
    Column("version", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)

task_steps = Table(
    "task_steps",
    metadata,
    Column("step_id", String, primary_key=True),
    Column("task_id", String, ForeignKey("tasks.task_id"), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("description", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("result", Text),
    Column("error", Text),
    Column("started_at", String),
    Column("completed_at", String),
    UniqueConstraint("task_id", "sequence", name="uq_task_step_sequence"),
)

task_checkpoints = Table(
    "task_checkpoints",
    metadata,
    Column("checkpoint_id", String, primary_key=True),
    Column("schema_version", String, nullable=False),
    Column("task_id", String, ForeignKey("tasks.task_id"), nullable=False),
    Column("agent_run_id", String),
    Column("task_version", Integer, nullable=False),
    Column("summary", Text, nullable=False),
    Column("completed_step_ids_json", Text, nullable=False, default="[]"),
    Column("pending_step_ids_json", Text, nullable=False, default="[]"),
    Column("current_step_id", String),
    Column("decisions_json", Text, nullable=False, default="[]"),
    Column("blockers_json", Text, nullable=False, default="[]"),
    Column("next_action", Text),
    Column("context_digest", String),
    Column("writer_epoch", Integer, nullable=False, default=0),
    Column("created_at", String, nullable=False),
)


personas = Table(
    "personas",
    metadata,
    Column("persona_id", String, primary_key=True),
    Column("identity_summary", Text, nullable=False, default=""),
    Column("style_rules_json", Text, nullable=False, default="[]"),
    Column("hard_constraints_json", Text, nullable=False, default="[]"),
    Column("version", Integer, nullable=False, default=1),
    Column("updated_at", String, nullable=False),
)

contact_profiles = Table(
    "contact_profiles",
    metadata,
    Column("contact_id", String, primary_key=True),
    Column("relation", Text, nullable=False, default=""),
    Column("stable_facts_json", Text, nullable=False, default="[]"),
    Column("style_overrides_json", Text, nullable=False, default="[]"),
    Column("persona_id", String, ForeignKey("personas.persona_id")),
    Column("version", Integer, nullable=False, default=1),
    Column("updated_at", String, nullable=False),
)


memories = Table(
    "memories",
    metadata,
    Column("memory_id", String, primary_key=True),
    Column("schema_version", String, nullable=False),
    Column("state", String, nullable=False),
    Column("scope", String, nullable=False),
    Column("owner_id", String),
    Column("conversation_id", String),
    Column("task_id", String),
    Column("content", Text, nullable=False),
    Column("entities_json", Text, nullable=False, default="[]"),
    Column("importance", Float),
    Column("trust", Float, nullable=False),
    Column("confidence", Float),
    Column("source_type", String, nullable=False),
    Column("source_message_id", String),
    Column("source_event_id", String),
    Column("valid_from", String),
    Column("valid_to", String),
    Column(
        "supersedes",
        String,
        ForeignKey("memories.memory_id"),
    ),
    Column("created_at", String, nullable=False),
)

Index(
    "ix_memories_conversation_state_created",
    memories.c.conversation_id,
    memories.c.state,
    memories.c.created_at,
)
Index(
    "ix_memories_task_state_created",
    memories.c.task_id,
    memories.c.state,
    memories.c.created_at,
)
Index(
    "ix_memories_scope_owner_state",
    memories.c.scope,
    memories.c.owner_id,
    memories.c.state,
)
Index(
    "ix_memories_source_event",
    memories.c.source_event_id,
)


conversation_summaries = Table(
    "conversation_summaries",
    metadata,
    Column("conversation_id", String, primary_key=True),
    Column("schema_version", String, nullable=False),
    Column("summary", Text, nullable=False),
    Column("source_digest", String, nullable=False),
    Column("source_event_count", Integer, nullable=False),
    Column("source_from_at", String),
    Column("source_to_at", String),
    Column("provider", String),
    Column("model", String),
    Column("updated_at", String, nullable=False),
)
