from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import func, select

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.tables import event_journal, task_checkpoints, task_steps, tasks
from qbot.persistence.tasks import (
    TaskConcurrencyError,
    TaskRepository,
    TaskStateError,
)


class TaskRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        self.repo = TaskRepository(self.db)
        with self.db.transaction() as conn:
            conn.execute(
                tasks.insert().values(
                    task_id="task-1",
                    schema_version="0.1.0",
                    conversation_id="conv-1",
                    parent_task_id=None,
                    goal="finish report",
                    status="READY",
                    phase="draft",
                    constraints_json="[]",
                    decisions_json=json.dumps(["keep durable state"]),
                    blockers_json="[]",
                    next_action="step one",
                    writer_epoch=7,
                    version=1,
                    created_at="2026-09-20T00:00:00Z",
                    updated_at="2026-09-20T00:00:00Z",
                )
            )
            conn.execute(
                task_steps.insert(),
                [
                    {
                        "step_id": "step-1",
                        "task_id": "task-1",
                        "sequence": 1,
                        "description": "step one",
                        "status": "PENDING",
                        "result": None,
                        "error": None,
                        "started_at": None,
                        "completed_at": None,
                    },
                    {
                        "step_id": "step-2",
                        "task_id": "task-1",
                        "sequence": 2,
                        "description": "step two",
                        "status": "PENDING",
                        "result": None,
                        "error": None,
                        "started_at": None,
                        "completed_at": None,
                    },
                ],
            )

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_start_and_complete_are_checkpointed_atomically(self) -> None:
        started = self.repo.start_step(
            task_id="task-1",
            step_id="step-1",
            expected_version=1,
            writer_epoch=7,
        )
        self.assertEqual(started.task_version, 2)
        self.assertEqual(started.task_status, "RUNNING")

        completed = self.repo.complete_step(
            task_id="task-1",
            step_id="step-1",
            expected_version=2,
            writer_epoch=7,
            result="done",
        )
        self.assertEqual(completed.task_version, 3)
        self.assertEqual(completed.task_status, "RUNNING")

        with self.db.engine.connect() as conn:
            task = conn.execute(
                select(tasks).where(tasks.c.task_id == "task-1")
            ).mappings().one()
            step = conn.execute(
                select(task_steps).where(task_steps.c.step_id == "step-1")
            ).mappings().one()
            checkpoints = conn.execute(
                select(task_checkpoints)
                .where(task_checkpoints.c.task_id == "task-1")
                .order_by(task_checkpoints.c.task_version)
            ).mappings().all()

        self.assertEqual(task["version"], 3)
        self.assertEqual(task["next_action"], "step two")
        self.assertEqual(step["status"], "SUCCEEDED")
        self.assertEqual([cp["task_version"] for cp in checkpoints], [2, 3])
        self.assertEqual(
            json.loads(checkpoints[-1]["completed_step_ids_json"]),
            ["step-1"],
        )
        self.assertEqual(
            json.loads(checkpoints[-1]["pending_step_ids_json"]),
            ["step-2"],
        )

    def test_last_step_completion_completes_task(self) -> None:
        self.repo.start_step(
            task_id="task-1",
            step_id="step-1",
            expected_version=1,
            writer_epoch=7,
        )
        self.repo.complete_step(
            task_id="task-1",
            step_id="step-1",
            expected_version=2,
            writer_epoch=7,
        )
        self.repo.start_step(
            task_id="task-1",
            step_id="step-2",
            expected_version=3,
            writer_epoch=7,
        )
        result = self.repo.complete_step(
            task_id="task-1",
            step_id="step-2",
            expected_version=4,
            writer_epoch=7,
        )

        self.assertEqual(result.task_status, "COMPLETED")
        self.assertEqual(result.task_version, 5)
        with self.db.engine.connect() as conn:
            task = conn.execute(
                select(tasks).where(tasks.c.task_id == "task-1")
            ).mappings().one()
            completed_events = conn.execute(
                select(func.count())
                .select_from(event_journal)
                .where(event_journal.c.event_type == "TASK_COMPLETED")
            ).scalar_one()
        self.assertEqual(task["status"], "COMPLETED")
        self.assertIsNone(task["next_action"])
        self.assertEqual(completed_events, 1)

    def test_stale_version_rolls_back_without_checkpoint(self) -> None:
        with self.assertRaises(TaskConcurrencyError):
            self.repo.start_step(
                task_id="task-1",
                step_id="step-1",
                expected_version=99,
                writer_epoch=7,
            )

        with self.db.engine.connect() as conn:
            step = conn.execute(
                select(task_steps).where(task_steps.c.step_id == "step-1")
            ).mappings().one()
            checkpoint_count = conn.execute(
                select(func.count()).select_from(task_checkpoints)
            ).scalar_one()
        self.assertEqual(step["status"], "PENDING")
        self.assertEqual(checkpoint_count, 0)

    def test_stale_writer_epoch_rolls_back_without_checkpoint(self) -> None:
        with self.assertRaises(TaskConcurrencyError):
            self.repo.start_step(
                task_id="task-1",
                step_id="step-1",
                expected_version=1,
                writer_epoch=6,
            )

        with self.db.engine.connect() as conn:
            task = conn.execute(
                select(tasks).where(tasks.c.task_id == "task-1")
            ).mappings().one()
            checkpoint_count = conn.execute(
                select(func.count()).select_from(task_checkpoints)
            ).scalar_one()
        self.assertEqual(task["version"], 1)
        self.assertEqual(checkpoint_count, 0)

    def test_cannot_start_second_step_while_one_is_running(self) -> None:
        self.repo.start_step(
            task_id="task-1",
            step_id="step-1",
            expected_version=1,
            writer_epoch=7,
        )
        with self.assertRaises(TaskStateError):
            self.repo.start_step(
                task_id="task-1",
                step_id="step-2",
                expected_version=2,
                writer_epoch=7,
            )


if __name__ == "__main__":
    unittest.main()
