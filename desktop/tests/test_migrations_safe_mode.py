from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

from qbot.config import QbotConfig
from qbot.persistence import Database


class MigrationAndSafeModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "qbot.db"
        self.config = QbotConfig(database_path=self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_v1_like_database(self) -> None:
        db = Database(self.config)
        report = db.bootstrap()
        self.assertFalse(report.safe_mode)
        try:
            with db.engine.begin() as conn:
                # Remove tables introduced by the explicit v1->v2 and v2->v3
                # migrations while preserving the v1 durable core tables.
                for table in (
                    "memories",
                    "contact_profiles",
                    "personas",
                    "task_checkpoints",
                    "task_steps",
                    "tasks",
                ):
                    conn.execute(text(f"DROP TABLE {table}"))
                conn.execute(
                    text(
                        "UPDATE qbot_meta SET value='1' "
                        "WHERE key='db_schema_version'"
                    )
                )
        finally:
            db.close()

    def test_v1_database_is_backed_up_then_migrated_to_v4(self) -> None:
        self._seed_v1_like_database()

        db = Database(self.config)
        try:
            report = db.bootstrap()
            self.assertFalse(report.safe_mode)
            self.assertTrue(report.integrity_ok)
            self.assertEqual(report.migrated_from, "1")
            self.assertEqual(report.migrated_to, "4")
            self.assertIsNotNone(report.backup_path)
            self.assertTrue(report.backup_path.exists())
            self.assertEqual(db.meta("db_schema_version"), "4")
            self.assertIsNotNone(db.meta("last_integrity_check_at"))

            with db.engine.connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table'"
                        )
                    ).all()
                }
            self.assertIn("tasks", tables)
            self.assertIn("task_checkpoints", tables)
            self.assertIn("personas", tables)
            self.assertIn("contact_profiles", tables)
            self.assertIn("memories", tables)

            old = sqlite3.connect(report.backup_path)
            try:
                old_version = old.execute(
                    "SELECT value FROM qbot_meta "
                    "WHERE key='db_schema_version'"
                ).fetchone()[0]
            finally:
                old.close()
            self.assertEqual(old_version, "1")
        finally:
            db.close()

    def test_newer_unknown_schema_enters_safe_mode_and_blocks_mutation(self) -> None:
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

        db = Database(self.config)
        try:
            report = db.bootstrap()
            self.assertTrue(report.safe_mode)
            self.assertFalse(report.integrity_ok)
            self.assertEqual(report.schema_version, "99")
            self.assertIn("newer than supported", report.reason)
            self.assertTrue(db.safe_mode)

            with self.assertRaises(RuntimeError):
                with db.transaction():
                    pass
        finally:
            db.close()

    def test_existing_database_without_qbot_meta_enters_safe_mode(self) -> None:
        raw = sqlite3.connect(self.db_path)
        try:
            raw.execute("CREATE TABLE unknown_data(id INTEGER PRIMARY KEY)")
            raw.commit()
        finally:
            raw.close()

        db = Database(self.config)
        try:
            report = db.bootstrap()
            self.assertTrue(report.safe_mode)
            self.assertIsNone(report.schema_version)
            self.assertIn("no qbot_meta", report.reason)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
