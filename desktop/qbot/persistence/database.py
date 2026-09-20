from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Column, MetaData, String, Table, create_engine, event, text
from sqlalchemy.engine import Connection, Engine

from qbot.config import QbotConfig


metadata = MetaData()

qbot_meta = Table(
    "qbot_meta",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)


class Database:
    """Desktop SQLite bootstrap with Qbot durability defaults."""

    def __init__(self, config: QbotConfig) -> None:
        self.config = config
        db_path = Path(config.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{db_path}",
            future=True,
            connect_args={
                "check_same_thread": False,
                "timeout": 5.0,
            },
        )
        self._install_connection_pragmas(self.engine)

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

    def bootstrap(self) -> None:
        """Create v0.2 bootstrap metadata and enable WAL mode.

        WAL is a database-level setting and is established before runtime work.
        Foreign-key enforcement is installed on every SQLAlchemy connection.
        """

        with self.engine.begin() as conn:
            mode = conn.execute(text("PRAGMA journal_mode=WAL")).scalar_one()
            if str(mode).lower() != "wal":
                raise RuntimeError(f"failed to enable SQLite WAL mode: {mode!r}")

            metadata.create_all(conn)

            values = {
                "db_schema_version": self.config.db_schema_version,
                "qbot_spec_version": self.config.spec_version,
                "node_id": self.config.node_id,
            }
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

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Open an authoritative database transaction boundary."""

        with self.engine.begin() as conn:
            yield conn

    def pragma(self, name: str) -> object:
        allowed = {"journal_mode", "foreign_keys", "busy_timeout"}
        if name not in allowed:
            raise ValueError(f"unsupported pragma: {name}")
        with self.engine.connect() as conn:
            return conn.execute(text(f"PRAGMA {name}")).scalar_one()

    def meta(self, key: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                text("SELECT value FROM qbot_meta WHERE key=:key"),
                {"key": key},
            ).scalar_one_or_none()

    def close(self) -> None:
        self.engine.dispose()
