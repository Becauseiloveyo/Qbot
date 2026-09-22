from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import Database
from .tables import conversation_summaries


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RollingSummaryRecord:
    conversation_id: str
    schema_version: str
    summary: str
    source_digest: str
    source_event_count: int
    source_from_at: str | None
    source_to_at: str | None
    provider: str | None
    model: str | None
    updated_at: str


class RollingSummaryRepository:
    """Derived rolling-summary state below durable Task/Checkpoint authority."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def load(self, conversation_id: str) -> RollingSummaryRecord | None:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                select(conversation_summaries).where(
                    conversation_summaries.c.conversation_id == conversation_id
                )
            ).mappings().one_or_none()
        return None if row is None else self._record(row)

    def upsert_if_changed(
        self,
        *,
        conversation_id: str,
        summary: str,
        source_digest: str,
        source_event_count: int,
        source_from_at: str | None,
        source_to_at: str | None,
        provider: str | None,
        model: str | None,
    ) -> tuple[RollingSummaryRecord, bool]:
        normalized = summary.strip()
        if not normalized:
            raise ValueError("rolling summary must not be blank")
        if source_event_count < 1:
            raise ValueError("rolling summary requires at least one source event")
        if not source_digest:
            raise ValueError("rolling summary source_digest is required")

        existing = self.load(conversation_id)
        if existing is not None and existing.source_digest == source_digest:
            return existing, False

        updated_at = _now()
        statement = (
            sqlite_insert(conversation_summaries)
            .values(
                conversation_id=conversation_id,
                schema_version="0.1.0",
                summary=normalized,
                source_digest=source_digest,
                source_event_count=source_event_count,
                source_from_at=source_from_at,
                source_to_at=source_to_at,
                provider=provider,
                model=model,
                updated_at=updated_at,
            )
            .on_conflict_do_update(
                index_elements=["conversation_id"],
                set_={
                    "schema_version": "0.1.0",
                    "summary": normalized,
                    "source_digest": source_digest,
                    "source_event_count": source_event_count,
                    "source_from_at": source_from_at,
                    "source_to_at": source_to_at,
                    "provider": provider,
                    "model": model,
                    "updated_at": updated_at,
                },
            )
        )
        with self.database.transaction() as conn:
            conn.execute(statement)
            row = conn.execute(
                select(conversation_summaries).where(
                    conversation_summaries.c.conversation_id == conversation_id
                )
            ).mappings().one()
        return self._record(row), True

    @staticmethod
    def _record(row) -> RollingSummaryRecord:
        return RollingSummaryRecord(
            conversation_id=row["conversation_id"],
            schema_version=row["schema_version"],
            summary=row["summary"],
            source_digest=row["source_digest"],
            source_event_count=int(row["source_event_count"]),
            source_from_at=row["source_from_at"],
            source_to_at=row["source_to_at"],
            provider=row["provider"],
            model=row["model"],
            updated_at=row["updated_at"],
        )
