from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.tables import agent_runs, event_journal, inbound_events
from qbot.runtime import EventNormalizer
from qbot.transport import IncomingTransportEvent


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        self.repo = InboundAdmissionRepository(self.db)
        self.normalizer = EventNormalizer("mock")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _incoming(self) -> IncomingTransportEvent:
        return IncomingTransportEvent(
            account_id="acc-1",
            conversation_id="conv-1",
            sender_id="contact-1",
            platform_message_id="msg-100",
            text="在吗",
            occurred_at=datetime(2026, 9, 20, 6, 10, tzinfo=UTC),
        )

    def test_duplicate_platform_message_creates_one_event_and_run(self) -> None:
        first = self.repo.admit(self.normalizer.normalize(self._incoming()))
        second = self.repo.admit(self.normalizer.normalize(self._incoming()))

        self.assertTrue(first.is_new)
        self.assertFalse(second.is_new)
        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(first.run_id, second.run_id)

        with self.db.engine.connect() as conn:
            event_count = conn.execute(
                select(func.count()).select_from(inbound_events)
            ).scalar_one()
            run_count = conn.execute(
                select(func.count()).select_from(agent_runs)
            ).scalar_one()
            journal_count = conn.execute(
                select(func.count()).select_from(event_journal)
            ).scalar_one()

        self.assertEqual(event_count, 1)
        self.assertEqual(run_count, 1)
        self.assertEqual(journal_count, 2)


if __name__ == "__main__":
    unittest.main()
