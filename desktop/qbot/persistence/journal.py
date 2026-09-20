from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from .database import Database
from .tables import event_journal


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class JournalRecord:
    journal_id: str
    schema_version: str
    event_type: str
    actor: str
    account_id: str | None
    conversation_id: str | None
    task_id: str | None
    run_id: str | None
    related_id: str | None
    payload: dict[str, object]
    occurred_at: str


class JournalRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def append(
        self,
        *,
        event_type: str,
        actor: str,
        account_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        related_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> str:
        journal_id = f"journal-{uuid4()}"
        with self.database.transaction() as conn:
            conn.execute(
                event_journal.insert().values(
                    journal_id=journal_id,
                    schema_version="0.1.0",
                    event_type=event_type,
                    actor=actor,
                    account_id=account_id,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    run_id=run_id,
                    related_id=related_id,
                    payload_json=json.dumps(
                        payload or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    occurred_at=_now(),
                )
            )
        return journal_id

    def query(
        self,
        *,
        run_id: str | None = None,
        task_id: str | None = None,
        conversation_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[JournalRecord]:
        if limit < 1 or limit > 1000:
            raise ValueError("journal limit must be between 1 and 1000")

        statement = select(event_journal)
        if run_id is not None:
            statement = statement.where(event_journal.c.run_id == run_id)
        if task_id is not None:
            statement = statement.where(event_journal.c.task_id == task_id)
        if conversation_id is not None:
            statement = statement.where(
                event_journal.c.conversation_id == conversation_id
            )
        if event_type is not None:
            statement = statement.where(
                event_journal.c.event_type == event_type
            )

        statement = statement.order_by(
            event_journal.c.occurred_at.asc(),
            event_journal.c.journal_id.asc(),
        ).limit(limit)

        with self.database.engine.connect() as conn:
            rows = conn.execute(statement).mappings().all()

        records: list[JournalRecord] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {"_invalid_payload_json": row["payload_json"]}
            if not isinstance(payload, dict):
                payload = {"value": payload}
            records.append(
                JournalRecord(
                    journal_id=row["journal_id"],
                    schema_version=row["schema_version"],
                    event_type=row["event_type"],
                    actor=row["actor"],
                    account_id=row["account_id"],
                    conversation_id=row["conversation_id"],
                    task_id=row["task_id"],
                    run_id=row["run_id"],
                    related_id=row["related_id"],
                    payload=payload,
                    occurred_at=row["occurred_at"],
                )
            )
        return records
