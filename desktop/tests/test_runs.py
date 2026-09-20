from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.runs import AgentRunRepository, InvalidAgentRunTransition
from qbot.runtime import EventNormalizer
from qbot.transport import IncomingTransportEvent


class AgentRunRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(QbotConfig(database_path=Path(self.tmp.name) / "qbot.db"))
        self.db.bootstrap()
        event = EventNormalizer("mock").normalize(
            IncomingTransportEvent(
                account_id="acc-1",
                conversation_id="conv-1",
                platform_message_id="msg-1",
                text="hello",
                occurred_at=datetime.now(UTC),
            )
        )
        admitted = InboundAdmissionRepository(self.db).admit(event)
        self.run_id = admitted.run_id
        self.runs = AgentRunRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_restore_and_valid_transitions(self) -> None:
        created = self.runs.load(self.run_id)
        self.assertIsNotNone(created)
        self.assertEqual(created.status, "CREATED")

        restoring = self.runs.transition(self.run_id, "RESTORING")
        self.assertEqual(restoring.status, "RESTORING")

        reasoning = self.runs.transition(self.run_id, "REASONING")
        self.assertEqual(reasoning.status, "REASONING")

        reloaded = self.runs.load(self.run_id)
        self.assertEqual(reloaded.status, "REASONING")

    def test_illegal_transition_is_rejected(self) -> None:
        with self.assertRaises(InvalidAgentRunTransition):
            self.runs.transition(self.run_id, "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
