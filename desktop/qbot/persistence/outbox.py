from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .database import Database
from .tables import event_journal, outbox_messages


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"SENDING", "CANCELLED"}),
    "SENDING": frozenset({"SENT", "FAILED", "SENDING_UNKNOWN"}),
    "SENDING_UNKNOWN": frozenset({"SENT", "FAILED", "SENDING"}),
    "FAILED": frozenset({"PENDING", "CANCELLED"}),
    "SENT": frozenset(),
    "CANCELLED": frozenset(),
}


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    outbox_id: str
    schema_version: str
    run_id: str
    account_id: str
    conversation_id: str
    dedupe_key: str
    status: str
    payload_kind: str
    payload_text: str | None
    content_ref: str | None
    reply_to_message_id: str | None
    platform_message_id: str | None
    transport_attempts: int
    last_error: str | None
    writer_epoch: int
    created_at: str
    sent_at: str | None


class DuplicateOutboxEffect(ValueError):
    pass


class InvalidOutboxTransition(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class OutboxRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_text(
        self,
        *,
        run_id: str,
        account_id: str,
        conversation_id: str,
        dedupe_key: str,
        text: str,
        reply_to_message_id: str | None = None,
        writer_epoch: int = 0,
    ) -> OutboxRecord:
        outbox_id = f"out-{uuid4()}"
        now = _now()
        try:
            with self.database.transaction() as conn:
                conn.execute(
                    outbox_messages.insert().values(
                        outbox_id=outbox_id,
                        schema_version="0.1.0",
                        run_id=run_id,
                        account_id=account_id,
                        conversation_id=conversation_id,
                        dedupe_key=dedupe_key,
                        status="PENDING",
                        payload_kind="TEXT",
                        payload_text=text,
                        content_ref=None,
                        reply_to_message_id=reply_to_message_id,
                        platform_message_id=None,
                        transport_attempts=0,
                        last_error=None,
                        writer_epoch=writer_epoch,
                        created_at=now,
                        sent_at=None,
                    )
                )
                conn.execute(
                    event_journal.insert().values(
                        journal_id=f"journal-{uuid4()}",
                        schema_version="0.1.0",
                        event_type="OUTBOX_CREATED",
                        actor="SYSTEM",
                        account_id=account_id,
                        conversation_id=conversation_id,
                        task_id=None,
                        run_id=run_id,
                        related_id=outbox_id,
                        payload_json=json.dumps(
                            {"dedupe_key": dedupe_key},
                            sort_keys=True,
                        ),
                        occurred_at=now,
                    )
                )
        except IntegrityError as exc:
            raise DuplicateOutboxEffect(
                f"duplicate Outbox effect for account={account_id!r}, "
                f"dedupe_key={dedupe_key!r}"
            ) from exc
        return self.load(outbox_id)

    def list_by_status(
        self,
        statuses: tuple[str, ...] | list[str] | set[str],
    ) -> list[OutboxRecord]:
        values = tuple(statuses)
        if not values:
            return []
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                select(outbox_messages)
                .where(outbox_messages.c.status.in_(values))
                .order_by(
                    outbox_messages.c.created_at.asc(),
                    outbox_messages.c.outbox_id.asc(),
                )
            ).mappings().all()
        return [OutboxRecord(**dict(row)) for row in rows]

    def recover_interrupted_sends(self) -> list[OutboxRecord]:
        """Convert crash-left SENDING records to explicit uncertainty."""

        interrupted = self.list_by_status(("SENDING",))
        recovered: list[OutboxRecord] = []
        for record in interrupted:
            recovered.append(
                self.transition(
                    record.outbox_id,
                    "SENDING_UNKNOWN",
                    error="process restarted while transport send was in flight",
                )
            )
        return recovered

    def find_by_dedupe(
        self,
        *,
        account_id: str,
        dedupe_key: str,
    ) -> OutboxRecord | None:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                select(outbox_messages).where(
                    outbox_messages.c.account_id == account_id,
                    outbox_messages.c.dedupe_key == dedupe_key,
                )
            ).mappings().one_or_none()
        return OutboxRecord(**dict(row)) if row is not None else None

    def load(self, outbox_id: str) -> OutboxRecord:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                select(outbox_messages).where(
                    outbox_messages.c.outbox_id == outbox_id
                )
            ).mappings().one_or_none()
        if row is None:
            raise KeyError(f"unknown Outbox record: {outbox_id}")
        return OutboxRecord(**dict(row))

    def transition(
        self,
        outbox_id: str,
        target: str,
        *,
        platform_message_id: str | None = None,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> OutboxRecord:
        with self.database.transaction() as conn:
            row = conn.execute(
                select(outbox_messages).where(
                    outbox_messages.c.outbox_id == outbox_id
                )
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(f"unknown Outbox record: {outbox_id}")

            current = str(row["status"])
            if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
                raise InvalidOutboxTransition(
                    f"illegal Outbox transition: {current} -> {target}"
                )

            values: dict[str, object] = {
                "status": target,
                "last_error": error,
            }
            if platform_message_id is not None:
                values["platform_message_id"] = platform_message_id
            if increment_attempt:
                values["transport_attempts"] = int(row["transport_attempts"]) + 1
            if target == "SENT":
                values["sent_at"] = _now()

            conn.execute(
                update(outbox_messages)
                .where(
                    outbox_messages.c.outbox_id == outbox_id,
                    outbox_messages.c.status == current,
                )
                .values(**values)
            )

            journal_type = None
            if target == "SENT":
                journal_type = "MESSAGE_SENT"
            elif target == "SENDING_UNKNOWN":
                journal_type = "SEND_UNKNOWN"

            if journal_type is not None:
                conn.execute(
                    event_journal.insert().values(
                        journal_id=f"journal-{uuid4()}",
                        schema_version="0.1.0",
                        event_type=journal_type,
                        actor="TRANSPORT",
                        account_id=row["account_id"],
                        conversation_id=row["conversation_id"],
                        task_id=None,
                        run_id=row["run_id"],
                        related_id=outbox_id,
                        payload_json=json.dumps(
                            {"platform_message_id": platform_message_id},
                            sort_keys=True,
                        ),
                        occurred_at=_now(),
                    )
                )

        return self.load(outbox_id)
