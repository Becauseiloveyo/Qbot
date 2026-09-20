from __future__ import annotations

from sqlalchemy import (
    Column,
    ForeignKey,
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
