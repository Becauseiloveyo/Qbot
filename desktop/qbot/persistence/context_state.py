from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select

from .database import Database
from .tables import (
    conversation_summaries,
    inbound_events,
    task_checkpoints,
    task_steps,
    tasks,
)


@dataclass(frozen=True, slots=True)
class DurableContextSnapshot:
    active_task: str | None
    checkpoint: str | None
    important_decisions: tuple[str, ...]
    rolling_summary: str | None
    recent_messages: tuple[str, ...]


class ContextStateRepository:
    """Read-only durable state loader used before every model decision."""

    def __init__(self, database: Database, *, recent_limit: int = 12) -> None:
        self.database = database
        self.recent_limit = recent_limit

    def load(
        self,
        *,
        conversation_id: str,
        current_event_id: str,
    ) -> DurableContextSnapshot:
        with self.database.engine.connect() as conn:
            task = conn.execute(
                select(tasks)
                .where(
                    tasks.c.conversation_id == conversation_id,
                    tasks.c.status.not_in(["COMPLETED", "CANCELLED"]),
                )
                .order_by(tasks.c.updated_at.desc())
                .limit(1)
            ).mappings().one_or_none()

            task_text: str | None = None
            checkpoint_text: str | None = None
            decisions: list[str] = []

            if task is not None:
                steps = conn.execute(
                    select(task_steps)
                    .where(task_steps.c.task_id == task["task_id"])
                    .order_by(task_steps.c.sequence.asc())
                ).mappings().all()

                task_text = self._render_task(task, steps)
                decisions.extend(self._json_string_list(task["decisions_json"]))

                checkpoint = conn.execute(
                    select(task_checkpoints)
                    .where(
                        task_checkpoints.c.task_id == task["task_id"],
                        task_checkpoints.c.task_version == task["version"],
                    )
                    .order_by(task_checkpoints.c.created_at.desc())
                    .limit(1)
                ).mappings().one_or_none()

                if checkpoint is not None:
                    checkpoint_text = self._render_checkpoint(checkpoint)
                    decisions.extend(
                        self._json_string_list(checkpoint["decisions_json"])
                    )

            summary_row = conn.execute(
                select(conversation_summaries.c.summary).where(
                    conversation_summaries.c.conversation_id == conversation_id
                )
            ).scalar_one_or_none()

            recent_rows = conn.execute(
                select(
                    inbound_events.c.sender_id,
                    inbound_events.c.text,
                )
                .where(
                    inbound_events.c.conversation_id == conversation_id,
                    inbound_events.c.event_id != current_event_id,
                    inbound_events.c.event_type == "MESSAGE_RECEIVED",
                    inbound_events.c.text.is_not(None),
                )
                .order_by(inbound_events.c.received_at.desc())
                .limit(self.recent_limit)
            ).all()

        recent = tuple(
            f"{sender or 'unknown'}: {text}"
            for sender, text in reversed(recent_rows)
        )
        return DurableContextSnapshot(
            active_task=task_text,
            checkpoint=checkpoint_text,
            important_decisions=tuple(dict.fromkeys(decisions)),
            rolling_summary=summary_row,
            recent_messages=recent,
        )

    @staticmethod
    def _json_string_list(raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    @staticmethod
    def _render_task(task, steps) -> str:
        lines = [
            f"task_id: {task['task_id']}",
            f"goal: {task['goal']}",
            f"status: {task['status']}",
            f"phase: {task['phase']}",
            f"version: {task['version']}",
            f"next_action: {task['next_action'] or '(none)'}",
        ]
        constraints = ContextStateRepository._json_string_list(
            task["constraints_json"]
        )
        if constraints:
            lines.append("constraints:")
            lines.extend(f"- {item}" for item in constraints)
        if steps:
            lines.append("steps:")
            lines.extend(
                f"- [{step['status']}] {step['description']}"
                for step in steps
            )
        return "\n".join(lines)

    @staticmethod
    def _render_checkpoint(checkpoint) -> str:
        lines = [
            f"checkpoint_id: {checkpoint['checkpoint_id']}",
            f"task_version: {checkpoint['task_version']}",
            f"summary: {checkpoint['summary']}",
            f"current_step_id: {checkpoint['current_step_id'] or '(none)'}",
            f"next_action: {checkpoint['next_action'] or '(none)'}",
        ]
        completed = ContextStateRepository._json_string_list(
            checkpoint["completed_step_ids_json"]
        )
        pending = ContextStateRepository._json_string_list(
            checkpoint["pending_step_ids_json"]
        )
        if completed:
            lines.append("completed_step_ids: " + ", ".join(completed))
        if pending:
            lines.append("pending_step_ids: " + ", ".join(pending))
        blockers = ContextStateRepository._json_string_list(
            checkpoint["blockers_json"]
        )
        if blockers:
            lines.append("blockers:")
            lines.extend(f"- {item}" for item in blockers)
        return "\n".join(lines)
