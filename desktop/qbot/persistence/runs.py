from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update

from .database import Database
from .tables import agent_runs


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"RESTORING"}),
    "RESTORING": frozenset({"REASONING", "FAILED"}),
    "REASONING": frozenset({"WAITING_USER", "EXECUTING", "SUCCEEDED", "FAILED"}),
    "WAITING_USER": frozenset({"REASONING", "CANCELLED"}),
    "EXECUTING": frozenset({"REASONING", "SUCCEEDED", "FAILED"}),
    "SUCCEEDED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    run_id: str
    schema_version: str
    conversation_id: str
    trigger_event_id: str
    task_id: str | None
    status: str
    model_profile: str | None
    writer_epoch: int
    created_at: str
    updated_at: str


class InvalidAgentRunTransition(ValueError):
    pass


class AgentRunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_by_status(
        self,
        statuses: tuple[str, ...] | list[str] | set[str],
    ) -> list[AgentRunRecord]:
        values = tuple(statuses)
        if not values:
            return []
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                select(agent_runs)
                .where(agent_runs.c.status.in_(values))
                .order_by(agent_runs.c.created_at.asc(), agent_runs.c.run_id.asc())
            ).mappings().all()
        return [AgentRunRecord(**dict(row)) for row in rows]

    def load(self, run_id: str) -> AgentRunRecord | None:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                select(agent_runs).where(agent_runs.c.run_id == run_id)
            ).mappings().one_or_none()
        return AgentRunRecord(**dict(row)) if row is not None else None

    def transition(self, run_id: str, target: str) -> AgentRunRecord:
        with self.database.transaction() as conn:
            row = conn.execute(
                select(agent_runs).where(agent_runs.c.run_id == run_id)
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(f"unknown AgentRun: {run_id}")

            current = str(row["status"])
            if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
                raise InvalidAgentRunTransition(
                    f"illegal AgentRun transition: {current} -> {target}"
                )

            now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            conn.execute(
                update(agent_runs)
                .where(
                    agent_runs.c.run_id == run_id,
                    agent_runs.c.status == current,
                )
                .values(status=target, updated_at=now)
            )

            updated = conn.execute(
                select(agent_runs).where(agent_runs.c.run_id == run_id)
            ).mappings().one()

        return AgentRunRecord(**dict(updated))
