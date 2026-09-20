from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update

from .database import Database
from .tables import event_journal, task_checkpoints, task_steps, tasks


class TaskConcurrencyError(RuntimeError):
    pass


class TaskStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TaskMutationResult:
    task_id: str
    task_version: int
    task_status: str
    checkpoint_id: str


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TaskRepository:
    """Authoritative TaskStep mutations with checkpoint+journal atomicity."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def start_step(
        self,
        *,
        task_id: str,
        step_id: str,
        expected_version: int,
        writer_epoch: int,
        agent_run_id: str | None = None,
        summary: str | None = None,
    ) -> TaskMutationResult:
        now = _now()
        with self.database.transaction() as conn:
            task = self._guarded_task(
                conn,
                task_id=task_id,
                expected_version=expected_version,
                writer_epoch=writer_epoch,
            )
            step = conn.execute(
                select(task_steps).where(
                    task_steps.c.task_id == task_id,
                    task_steps.c.step_id == step_id,
                )
            ).mappings().one_or_none()
            if step is None:
                raise KeyError(f"unknown task step: {step_id}")
            if step["status"] != "PENDING":
                raise TaskStateError(
                    f"step {step_id} must be PENDING, got {step['status']}"
                )

            other_running = conn.execute(
                select(task_steps.c.step_id).where(
                    task_steps.c.task_id == task_id,
                    task_steps.c.status == "RUNNING",
                    task_steps.c.step_id != step_id,
                )
            ).first()
            if other_running is not None:
                raise TaskStateError(
                    f"task {task_id} already has RUNNING step {other_running[0]}"
                )

            conn.execute(
                update(task_steps)
                .where(task_steps.c.step_id == step_id)
                .values(
                    status="RUNNING",
                    started_at=now,
                    completed_at=None,
                    result=None,
                    error=None,
                )
            )

            new_version = expected_version + 1
            affected = conn.execute(
                update(tasks)
                .where(
                    tasks.c.task_id == task_id,
                    tasks.c.version == expected_version,
                    tasks.c.writer_epoch == writer_epoch,
                )
                .values(
                    status="RUNNING",
                    version=new_version,
                    next_action=step["description"],
                    updated_at=now,
                )
            ).rowcount
            if affected != 1:
                raise TaskConcurrencyError(
                    "task changed while starting step; mutation rolled back"
                )

            checkpoint_id = self._insert_checkpoint(
                conn,
                task_id=task_id,
                task_version=new_version,
                writer_epoch=writer_epoch,
                agent_run_id=agent_run_id,
                summary=summary or f"Started step: {step['description']}",
                current_step_id=step_id,
                next_action=step["description"],
                decisions_json=task["decisions_json"],
                blockers_json=task["blockers_json"],
                created_at=now,
            )
            self._journal(
                conn,
                event_type="STEP_STARTED",
                task_id=task_id,
                run_id=agent_run_id,
                related_id=step_id,
                payload={"task_version": new_version},
                occurred_at=now,
            )
            self._journal(
                conn,
                event_type="CHECKPOINT_COMMITTED",
                task_id=task_id,
                run_id=agent_run_id,
                related_id=checkpoint_id,
                payload={"task_version": new_version},
                occurred_at=now,
            )

        return TaskMutationResult(
            task_id=task_id,
            task_version=new_version,
            task_status="RUNNING",
            checkpoint_id=checkpoint_id,
        )

    def complete_step(
        self,
        *,
        task_id: str,
        step_id: str,
        expected_version: int,
        writer_epoch: int,
        result: str | None = None,
        next_action: str | None = None,
        agent_run_id: str | None = None,
        summary: str | None = None,
    ) -> TaskMutationResult:
        now = _now()
        with self.database.transaction() as conn:
            task = self._guarded_task(
                conn,
                task_id=task_id,
                expected_version=expected_version,
                writer_epoch=writer_epoch,
            )
            step = conn.execute(
                select(task_steps).where(
                    task_steps.c.task_id == task_id,
                    task_steps.c.step_id == step_id,
                )
            ).mappings().one_or_none()
            if step is None:
                raise KeyError(f"unknown task step: {step_id}")
            if step["status"] != "RUNNING":
                raise TaskStateError(
                    f"step {step_id} must be RUNNING, got {step['status']}"
                )

            conn.execute(
                update(task_steps)
                .where(task_steps.c.step_id == step_id)
                .values(
                    status="SUCCEEDED",
                    result=result,
                    error=None,
                    completed_at=now,
                )
            )

            refreshed_steps = conn.execute(
                select(task_steps)
                .where(task_steps.c.task_id == task_id)
                .order_by(task_steps.c.sequence.asc())
            ).mappings().all()
            unfinished = [
                item
                for item in refreshed_steps
                if item["status"] not in {"SUCCEEDED", "CANCELLED"}
            ]
            if unfinished:
                task_status = "RUNNING"
                derived_next = next_action or unfinished[0]["description"]
            else:
                task_status = "COMPLETED"
                derived_next = None

            new_version = expected_version + 1
            affected = conn.execute(
                update(tasks)
                .where(
                    tasks.c.task_id == task_id,
                    tasks.c.version == expected_version,
                    tasks.c.writer_epoch == writer_epoch,
                )
                .values(
                    status=task_status,
                    version=new_version,
                    next_action=derived_next,
                    updated_at=now,
                )
            ).rowcount
            if affected != 1:
                raise TaskConcurrencyError(
                    "task changed while completing step; mutation rolled back"
                )

            checkpoint_id = self._insert_checkpoint(
                conn,
                task_id=task_id,
                task_version=new_version,
                writer_epoch=writer_epoch,
                agent_run_id=agent_run_id,
                summary=summary or f"Completed step: {step['description']}",
                current_step_id=None,
                next_action=derived_next,
                decisions_json=task["decisions_json"],
                blockers_json=task["blockers_json"],
                created_at=now,
            )
            self._journal(
                conn,
                event_type="CHECKPOINT_COMMITTED",
                task_id=task_id,
                run_id=agent_run_id,
                related_id=checkpoint_id,
                payload={"task_version": new_version},
                occurred_at=now,
            )
            if task_status == "COMPLETED":
                self._journal(
                    conn,
                    event_type="TASK_COMPLETED",
                    task_id=task_id,
                    run_id=agent_run_id,
                    related_id=task_id,
                    payload={"task_version": new_version},
                    occurred_at=now,
                )

        return TaskMutationResult(
            task_id=task_id,
            task_version=new_version,
            task_status=task_status,
            checkpoint_id=checkpoint_id,
        )

    def _guarded_task(
        self,
        conn,
        *,
        task_id: str,
        expected_version: int,
        writer_epoch: int,
    ):
        task = conn.execute(
            select(tasks).where(tasks.c.task_id == task_id)
        ).mappings().one_or_none()
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        if int(task["writer_epoch"]) != writer_epoch:
            raise TaskConcurrencyError(
                f"stale writer epoch: expected {task['writer_epoch']}, got {writer_epoch}"
            )
        if int(task["version"]) != expected_version:
            raise TaskConcurrencyError(
                f"stale task version: expected {task['version']}, got {expected_version}"
            )
        return task

    def _insert_checkpoint(
        self,
        conn,
        *,
        task_id: str,
        task_version: int,
        writer_epoch: int,
        agent_run_id: str | None,
        summary: str,
        current_step_id: str | None,
        next_action: str | None,
        decisions_json: str,
        blockers_json: str,
        created_at: str,
    ) -> str:
        steps = conn.execute(
            select(task_steps)
            .where(task_steps.c.task_id == task_id)
            .order_by(task_steps.c.sequence.asc())
        ).mappings().all()
        completed = [
            step["step_id"]
            for step in steps
            if step["status"] in {"SUCCEEDED", "CANCELLED"}
        ]
        pending = [
            step["step_id"]
            for step in steps
            if step["status"] not in {"SUCCEEDED", "CANCELLED"}
        ]
        checkpoint_id = f"cp-{uuid4()}"
        conn.execute(
            task_checkpoints.insert().values(
                checkpoint_id=checkpoint_id,
                schema_version="0.1.0",
                task_id=task_id,
                agent_run_id=agent_run_id,
                task_version=task_version,
                summary=summary,
                completed_step_ids_json=json.dumps(completed),
                pending_step_ids_json=json.dumps(pending),
                current_step_id=current_step_id,
                decisions_json=decisions_json or "[]",
                blockers_json=blockers_json or "[]",
                next_action=next_action,
                context_digest=None,
                writer_epoch=writer_epoch,
                created_at=created_at,
            )
        )
        return checkpoint_id

    @staticmethod
    def _journal(
        conn,
        *,
        event_type: str,
        task_id: str,
        run_id: str | None,
        related_id: str,
        payload: dict[str, object],
        occurred_at: str,
    ) -> None:
        conn.execute(
            event_journal.insert().values(
                journal_id=f"journal-{uuid4()}",
                schema_version="0.1.0",
                event_type=event_type,
                actor="SYSTEM",
                account_id=None,
                conversation_id=None,
                task_id=task_id,
                run_id=run_id,
                related_id=related_id,
                payload_json=json.dumps(payload, sort_keys=True),
                occurred_at=occurred_at,
            )
        )
