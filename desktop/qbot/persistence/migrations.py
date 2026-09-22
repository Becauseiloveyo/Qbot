from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.engine import Connection

from .tables import (
    contact_profiles,
    conversation_summaries,
    memories,
    personas,
    task_checkpoints,
    task_steps,
    tasks,
)


@dataclass(frozen=True, slots=True)
class Migration:
    from_version: int
    to_version: int
    apply: Callable[[Connection], None]


def _v1_to_v2(conn: Connection) -> None:
    tasks.create(conn, checkfirst=True)
    task_steps.create(conn, checkfirst=True)
    task_checkpoints.create(conn, checkfirst=True)


def _v2_to_v3(conn: Connection) -> None:
    personas.create(conn, checkfirst=True)
    contact_profiles.create(conn, checkfirst=True)


def _v3_to_v4(conn: Connection) -> None:
    memories.create(conn, checkfirst=True)


def _v4_to_v5(conn: Connection) -> None:
    conversation_summaries.create(conn, checkfirst=True)


MIGRATIONS: dict[int, Migration] = {
    1: Migration(1, 2, _v1_to_v2),
    2: Migration(2, 3, _v2_to_v3),
    3: Migration(3, 4, _v3_to_v4),
    4: Migration(4, 5, _v4_to_v5),
}


def migration_path(current: int, target: int) -> tuple[Migration, ...]:
    if current > target:
        raise ValueError(
            f"database schema {current} is newer than supported target {target}"
        )

    path: list[Migration] = []
    version = current
    while version < target:
        migration = MIGRATIONS.get(version)
        if migration is None or migration.to_version != version + 1:
            raise ValueError(
                f"no contiguous migration registered for {version} -> {version + 1}"
            )
        path.append(migration)
        version = migration.to_version
    return tuple(path)
