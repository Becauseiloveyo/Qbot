from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from .database import Database
from .tables import event_journal


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
