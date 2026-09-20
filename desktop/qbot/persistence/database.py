from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine

from qbot.config import QbotConfig

from .migrations import migration_path
from .tables import metadata, qbot_meta


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    safe_mode: bool
    schema_version: str | None
    migrated_from: str | None = None
    migrated_to: str | None = None
    backup_path: Path | None = None
    integrity_ok: bool = False
    reason: str | None = None


class Database:
    """Desktop SQLite bootstrap with backup/migration/integrity safeguards."""

    def __init__(self, config: QbotConfig) -> None:
        self.config = config
        self.db_path = Path(config.database_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            future=True,
            connect_args={
                "check_same_thread": False,
                "timeout": 5.0,
            },
        )
        self._install_connection_pragmas(self.engine)
        self._safe_mode = False
        self._safe_mode_reason: str | None = None
        self._last_bootstrap_report: BootstrapReport | None = None

    @property
    def safe_mode(self) -> bool:
        return self._safe_mode

    @property
    def safe_mode_reason(self) -> str | None:
        return self._safe_mode_reason

    @property
    def last_bootstrap_report(self) -> BootstrapReport | None:
        return self._last_bootstrap_report

    @staticmethod
    def _install_connection_pragmas(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    def bootstrap(self) -> BootstrapReport:
        """Backup, migrate, validate, or enter Safe Mode on failure."""

        target = int(self.config.db_schema_version)
        backup_path: Path | None = None
        migrated_from: str | None = None

        self._safe_mode = False
        self._safe_mode_reason = None

        try:
            with self.engine.begin() as conn:
                mode = conn.execute(text("PRAGMA journal_mode=WAL")).scalar_one()
                if str(mode).lower() != "wal":
                    raise RuntimeError(
                        f"failed to enable SQLite WAL mode: {mode!r}"
                    )

                table_names = self._table_names(conn)
                is_new = not table_names
                if is_new:
                    metadata.create_all(conn)
                    self._write_meta(
                        conn,
                        {
                            "db_schema_version": str(target),
                            "qbot_spec_version": self.config.spec_version,
                            "node_id": self.config.node_id,
                        },
                    )
                else:
                    if "qbot_meta" not in table_names:
                        raise RuntimeError(
                            "existing SQLite file has no qbot_meta; "
                            "schema provenance is unknown"
                        )

                    raw_version = conn.execute(
                        qbot_meta.select()
                        .with_only_columns(qbot_meta.c.value)
                        .where(qbot_meta.c.key == "db_schema_version")
                    ).scalar_one_or_none()
                    if raw_version is None:
                        raise RuntimeError(
                            "existing database has no db_schema_version"
                        )

                    current = int(raw_version)
                    if current > target:
                        raise RuntimeError(
                            f"database schema {current} is newer than "
                            f"supported schema {target}"
                        )

                    if current < target:
                        migrated_from = str(current)

            if migrated_from is not None:
                backup_path = self._backup_before_migration()
                current = int(migrated_from)
                migrations = migration_path(current, target)
                with self.engine.begin() as conn:
                    for migration in migrations:
                        migration.apply(conn)
                        self._write_meta(
                            conn,
                            {
                                "db_schema_version": str(
                                    migration.to_version
                                )
                            },
                        )

            with self.engine.begin() as conn:
                self._assert_expected_schema(conn)
                self._write_meta(
                    conn,
                    {
                        "db_schema_version": str(target),
                        "qbot_spec_version": self.config.spec_version,
                        "node_id": self.config.node_id,
                    },
                )

            self._run_integrity_check()

            with self.engine.begin() as conn:
                self._write_meta(
                    conn,
                    {"last_integrity_check_at": _now()},
                )

            report = BootstrapReport(
                safe_mode=False,
                schema_version=str(target),
                migrated_from=migrated_from,
                migrated_to=(str(target) if migrated_from is not None else None),
                backup_path=backup_path,
                integrity_ok=True,
            )
        except Exception as exc:
            self._safe_mode = True
            self._safe_mode_reason = f"{type(exc).__name__}: {exc}"
            report = BootstrapReport(
                safe_mode=True,
                schema_version=self._read_schema_version_best_effort(),
                migrated_from=migrated_from,
                migrated_to=None,
                backup_path=backup_path,
                integrity_ok=False,
                reason=self._safe_mode_reason,
            )

        self._last_bootstrap_report = report
        return report

    def _backup_before_migration(self) -> Path:
        if not self.db_path.exists():
            raise RuntimeError("cannot back up missing database before migration")

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.db_path.with_name(
            f"{self.db_path.name}.backup-{stamp}"
        )

        source = sqlite3.connect(self.db_path)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        if not backup.exists() or backup.stat().st_size == 0:
            raise RuntimeError("SQLite backup was not created successfully")
        return backup

    def _run_integrity_check(self) -> None:
        with self.engine.connect() as conn:
            integrity = conn.execute(
                text("PRAGMA integrity_check")
            ).scalars().all()
            if integrity != ["ok"]:
                raise RuntimeError(
                    "SQLite integrity_check failed: " + "; ".join(integrity)
                )

            foreign_key_errors = conn.execute(
                text("PRAGMA foreign_key_check")
            ).all()
            if foreign_key_errors:
                raise RuntimeError(
                    f"SQLite foreign_key_check failed: {foreign_key_errors!r}"
                )

    def _assert_expected_schema(self, conn: Connection) -> None:
        present = self._table_names(conn)
        required = set(metadata.tables)
        missing = sorted(required - present)
        if missing:
            raise RuntimeError(
                "database schema is missing required tables: "
                + ", ".join(missing)
            )

    @staticmethod
    def _table_names(conn: Connection) -> set[str]:
        rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ).scalars().all()
        return set(rows)

    @staticmethod
    def _write_meta(
        conn: Connection,
        values: dict[str, str],
    ) -> None:
        for key, value in values.items():
            conn.execute(
                text(
                    """
                    INSERT INTO qbot_meta(key, value)
                    VALUES (:key, :value)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """
                ),
                {"key": key, "value": value},
            )

    def _read_schema_version_best_effort(self) -> str | None:
        try:
            with self.engine.connect() as conn:
                if "qbot_meta" not in self._table_names(conn):
                    return None
                return conn.execute(
                    qbot_meta.select()
                    .with_only_columns(qbot_meta.c.value)
                    .where(qbot_meta.c.key == "db_schema_version")
                ).scalar_one_or_none()
        except Exception:
            return None

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Open an authoritative database transaction boundary."""

        if self.safe_mode:
            raise RuntimeError(
                "authoritative database mutation disabled in Safe Mode: "
                f"{self.safe_mode_reason}"
            )
        with self.engine.begin() as conn:
            yield conn

    def pragma(self, name: str) -> object:
        allowed = {
            "journal_mode",
            "foreign_keys",
            "busy_timeout",
        }
        if name not in allowed:
            raise ValueError(f"unsupported pragma: {name}")
        with self.engine.connect() as conn:
            return conn.execute(text(f"PRAGMA {name}")).scalar_one()

    def meta(self, key: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                qbot_meta.select()
                .with_only_columns(qbot_meta.c.value)
                .where(qbot_meta.c.key == key)
            ).scalar_one_or_none()

    def close(self) -> None:
        self.engine.dispose()
