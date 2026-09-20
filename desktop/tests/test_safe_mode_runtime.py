from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from qbot.app import build_runtime
from qbot.config import QbotConfig
from qbot.persistence import Database
from qbot.runtime.recovery_executor import RecoveryMode
from qbot.transport import MockTransport


class SafeModeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "qbot.db"
        self.config = QbotConfig(database_path=self.db_path)

        seed = Database(self.config)
        self.assertFalse(seed.bootstrap().safe_mode)
        try:
            with seed.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE qbot_meta SET value='99' "
                        "WHERE key='db_schema_version'"
                    )
                )
        finally:
            seed.close()

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_safe_mode_runtime_does_not_start_transport_or_recovery(self) -> None:
        transport = MockTransport()
        runtime = build_runtime(
            config=self.config,
            transport=transport,
        )
        try:
            report = await runtime.start(RecoveryMode.ASSIST)
            self.assertTrue(report.safe_mode)
            self.assertIsNone(report.recovery)
            self.assertTrue(runtime.database.safe_mode)

            with self.assertRaises(RuntimeError):
                await transport.send(
                    __import__(
                        "qbot.transport",
                        fromlist=["OutgoingMessage"],
                    ).OutgoingMessage(
                        account_id="acc-1",
                        conversation_id="private:1",
                        dedupe_key="12345678",
                        text="must not send",
                    )
                )
        finally:
            await runtime.stop()

    async def test_diagnostic_is_read_only_and_snapshot_can_be_exported(self) -> None:
        db = Database(self.config)
        try:
            before = self.db_path.stat().st_mtime_ns
            diagnostic = db.diagnose()
            after = self.db_path.stat().st_mtime_ns

            self.assertEqual(diagnostic.schema_version, "99")
            self.assertTrue(diagnostic.integrity_ok)
            self.assertTrue(diagnostic.foreign_keys_ok)
            self.assertTrue(diagnostic.issues)
            self.assertEqual(before, after)

            snapshot = db.create_backup()
            self.assertTrue(snapshot.exists())
            self.assertGreater(snapshot.stat().st_size, 0)
            self.assertNotEqual(snapshot, self.db_path)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
