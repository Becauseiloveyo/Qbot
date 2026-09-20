from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.journal import JournalRepository


class JournalQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        self.journal = JournalRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_filters_by_run_task_conversation_and_type(self) -> None:
        self.journal.append(
            event_type="RUN_CREATED",
            actor="SYSTEM",
            account_id="acc-1",
            conversation_id="conv-1",
            task_id="task-1",
            run_id="run-1",
            related_id="evt-1",
            payload={"a": 1},
        )
        self.journal.append(
            event_type="CHECKPOINT_COMMITTED",
            actor="SYSTEM",
            account_id="acc-1",
            conversation_id="conv-1",
            task_id="task-1",
            run_id="run-1",
            related_id="cp-1",
            payload={"task_version": 2},
        )
        self.journal.append(
            event_type="RUN_CREATED",
            actor="SYSTEM",
            account_id="acc-1",
            conversation_id="conv-2",
            task_id=None,
            run_id="run-2",
            related_id="evt-2",
            payload={},
        )

        by_run = self.journal.query(run_id="run-1")
        self.assertEqual(len(by_run), 2)

        checkpoint = self.journal.query(
            task_id="task-1",
            event_type="CHECKPOINT_COMMITTED",
        )
        self.assertEqual(len(checkpoint), 1)
        self.assertEqual(checkpoint[0].related_id, "cp-1")
        self.assertEqual(checkpoint[0].payload["task_version"], 2)

        by_conversation = self.journal.query(conversation_id="conv-2")
        self.assertEqual([item.run_id for item in by_conversation], ["run-2"])

    def test_limit_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            self.journal.query(limit=0)
        with self.assertRaises(ValueError):
            self.journal.query(limit=1001)


if __name__ == "__main__":
    unittest.main()
