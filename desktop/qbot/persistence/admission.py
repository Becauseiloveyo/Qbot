from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from qbot.domain import NormalizedEvent

from .database import Database
from .tables import agent_runs, event_journal, inbound_events


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    is_new: bool
    event_id: str
    run_id: str


class InboundAdmissionRepository:
    """Atomic inbound idempotency barrier and primary AgentRun creation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def admit(self, event: NormalizedEvent) -> AdmissionResult:
        with self.database.transaction() as conn:
            insert_event = (
                sqlite_insert(inbound_events)
                .values(
                    event_id=event.event_id,
                    fingerprint=event.fingerprint,
                    schema_version=event.schema_version,
                    platform=event.platform,
                    transport=event.transport,
                    account_id=event.account_id,
                    conversation_id=event.conversation_id,
                    sender_id=event.sender_id,
                    platform_message_id=event.platform_message_id,
                    event_type=event.event_type,
                    message_type=event.message_type,
                    text=event.text,
                    content_ref=event.content_ref,
                    reply_to_message_id=event.reply_to_message_id,
                    occurred_at=event.occurred_at,
                    received_at=event.received_at,
                    raw_ref=event.raw_ref,
                    metadata_json=json.dumps(
                        event.metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
                .on_conflict_do_nothing(index_elements=["fingerprint"])
            )
            result = conn.execute(insert_event)

            if result.rowcount == 0:
                existing_event_id = conn.execute(
                    select(inbound_events.c.event_id).where(
                        inbound_events.c.fingerprint == event.fingerprint
                    )
                ).scalar_one()
                run_id = conn.execute(
                    select(agent_runs.c.run_id).where(
                        agent_runs.c.trigger_event_id == existing_event_id
                    )
                ).scalar_one()
                return AdmissionResult(
                    is_new=False,
                    event_id=existing_event_id,
                    run_id=run_id,
                )

            run_id = f"run-{uuid4()}"
            conn.execute(
                event_journal.insert().values(
                    journal_id=f"journal-{uuid4()}",
                    schema_version=event.schema_version,
                    event_type="MESSAGE_RECEIVED",
                    actor="TRANSPORT",
                    account_id=event.account_id,
                    conversation_id=event.conversation_id,
                    task_id=None,
                    run_id=None,
                    related_id=event.event_id,
                    payload_json="{}",
                    occurred_at=event.received_at,
                )
            )
            conn.execute(
                agent_runs.insert().values(
                    run_id=run_id,
                    schema_version=event.schema_version,
                    conversation_id=event.conversation_id,
                    trigger_event_id=event.event_id,
                    task_id=None,
                    status="CREATED",
                    model_profile=None,
                    writer_epoch=0,
                    created_at=event.received_at,
                    updated_at=event.received_at,
                )
            )
            conn.execute(
                event_journal.insert().values(
                    journal_id=f"journal-{uuid4()}",
                    schema_version=event.schema_version,
                    event_type="RUN_CREATED",
                    actor="SYSTEM",
                    account_id=event.account_id,
                    conversation_id=event.conversation_id,
                    task_id=None,
                    run_id=run_id,
                    related_id=event.event_id,
                    payload_json="{}",
                    occurred_at=event.received_at,
                )
            )

            return AdmissionResult(
                is_new=True,
                event_id=event.event_id,
                run_id=run_id,
            )
