from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qbot.config import QbotConfig
from qbot.persistence import Database


class DatabaseTests(unittest.TestCase):
    def test_bootstrap_enables_wal_foreign_keys_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = QbotConfig(
                node_id="test-node",
                database_path=Path(tmp) / "qbot.db",
            )
            db = Database(config)
            try:
                report = db.bootstrap()
                self.assertFalse(report.safe_mode)
                self.assertTrue(report.integrity_ok)
                self.assertEqual(str(db.pragma("journal_mode")).lower(), "wal")
                self.assertEqual(int(db.pragma("foreign_keys")), 1)
                self.assertGreaterEqual(int(db.pragma("busy_timeout")), 5000)
                self.assertEqual(db.meta("db_schema_version"), "5")
                self.assertEqual(db.meta("qbot_spec_version"), "0.1.0")
                self.assertEqual(db.meta("node_id"), "test-node")
                self.assertIsNotNone(db.meta("last_integrity_check_at"))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
