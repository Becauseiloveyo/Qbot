from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update

from .database import Database
from .tables import event_journal, memories

MEMORY_STATES = {
    "CANDIDATE",
    "PROMOTED",
    "SUPERSEDED",
    "REJECTED",
    "EXPIRED",
}

MEMORY_SCOPES = {
    "SYSTEM_POLICY",
    "USER_PERSONA",
    "CONTACT_PROFILE",
    "CONVERSATION_MEMORY",
    "TASK_MEMORY",
}

SOURCE_TYPES = {
    "SYSTEM",
    "USER_SELF",
    "CONTACT",
    "AGENT_INFERENCE",
    "IMPORT",
}

ALLOWED_SCOPES_BY_SOURCE: dict[str, set[str]] = {
    "SYSTEM": set(MEMORY_SCOPES),
    "USER_SELF": {
        "USER_PERSONA",
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    },
    "CONTACT": {
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    },
    "AGENT_INFERENCE": {
        "USER_PERSONA",
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    },
    "IMPORT": {
        "USER_PERSONA",
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    },
}


class MemoryPolicyError(ValueError):
    pass


class MemoryStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    schema_version: str
    state: str
    scope: str
    owner_id: str | None
    conversation_id: str | None
    task_id: str | None
    content: str
    entities: tuple[str, ...]
    importance: float | None
    trust: float
    confidence: float | None
    source_type: str
    source_message_id: str | None
    source_event_id: str | None
    valid_from: str | None
    valid_to: str | None
    supersedes: str | None
    created_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _score(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise MemoryPolicyError(f"{name} must be between 0 and 1")
    return number


def _clean_entities(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return tuple(unique)


class MemoryRepository:
    """Durable memory staging/promotion with provenance and append-only history."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_candidate(
        self,
        *,
        scope: str,
        content: str,
        source_type: str,
        trust: float,
        owner_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        entities: tuple[str, ...] | list[str] = (),
        importance: float | None = None,
        confidence: float | None = None,
        source_message_id: str | None = None,
        source_event_id: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        supersedes: str | None = None,
    ) -> MemoryRecord:
        scope = scope.strip().upper()
        source_type = source_type.strip().upper()
        content = content.strip()
        if not content:
            raise MemoryPolicyError("memory content must not be blank")
        self._validate_scope_for_source(scope, source_type)
        self._validate_scope_identity(
            scope=scope,
            owner_id=owner_id,
            conversation_id=conversation_id,
            task_id=task_id,
        )
        if source_type == "CONTACT" and not (
            source_message_id or source_event_id
        ):
            raise MemoryPolicyError(
                "CONTACT memory requires source_message_id or source_event_id"
            )

        trust = float(_score(trust, "trust"))
        importance = _score(importance, "importance")
        confidence = _score(confidence, "confidence")
        cleaned_entities = _clean_entities(entities)
        created_at = _now()
        memory_id = self._candidate_id(
            scope=scope,
            owner_id=owner_id,
            conversation_id=conversation_id,
            task_id=task_id,
            content=content,
            source_type=source_type,
            source_message_id=source_message_id,
            source_event_id=source_event_id,
        )

        with self.database.transaction() as conn:
            existing = conn.execute(
                select(memories).where(memories.c.memory_id == memory_id)
            ).mappings().one_or_none()
            if existing is not None:
                return self._record(existing)

            if supersedes is not None:
                target = conn.execute(
                    select(memories).where(memories.c.memory_id == supersedes)
                ).mappings().one_or_none()
                if target is None:
                    raise MemoryPolicyError(
                        f"superseded memory does not exist: {supersedes}"
                    )
                self._assert_same_memory_domain(
                    candidate={
                        "scope": scope,
                        "owner_id": owner_id,
                        "conversation_id": conversation_id,
                        "task_id": task_id,
                    },
                    target=target,
                )

            conn.execute(
                memories.insert().values(
                    memory_id=memory_id,
                    schema_version="0.1.0",
                    state="CANDIDATE",
                    scope=scope,
                    owner_id=owner_id,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    content=content,
                    entities_json=json.dumps(
                        cleaned_entities,
                        ensure_ascii=False,
                    ),
                    importance=importance,
                    trust=trust,
                    confidence=confidence,
                    source_type=source_type,
                    source_message_id=source_message_id,
                    source_event_id=source_event_id,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    supersedes=supersedes,
                    created_at=created_at,
                )
            )
            self._journal(
                conn,
                event_type="MEMORY_CANDIDATE_CREATED",
                actor=self._source_actor(source_type),
                related_id=memory_id,
                conversation_id=conversation_id,
                task_id=task_id,
                payload={
                    "scope": scope,
                    "source_type": source_type,
                    "supersedes": supersedes,
                },
                occurred_at=created_at,
            )
            row = conn.execute(
                select(memories).where(memories.c.memory_id == memory_id)
            ).mappings().one()

        return self._record(row)

    def promote(self, memory_id: str) -> MemoryRecord:
        now = _now()
        with self.database.transaction() as conn:
            candidate = conn.execute(
                select(memories).where(memories.c.memory_id == memory_id)
            ).mappings().one_or_none()
            if candidate is None:
                raise KeyError(f"unknown memory: {memory_id}")
            if candidate["state"] != "CANDIDATE":
                raise MemoryStateError(
                    f"memory {memory_id} must be CANDIDATE, "
                    f"got {candidate['state']}"
                )

            self._validate_scope_for_source(
                candidate["scope"],
                candidate["source_type"],
            )

            supersedes = candidate["supersedes"]
            if supersedes is not None:
                target = conn.execute(
                    select(memories).where(
                        memories.c.memory_id == supersedes
                    )
                ).mappings().one_or_none()
                if target is None:
                    raise MemoryPolicyError(
                        f"superseded memory does not exist: {supersedes}"
                    )
                if target["state"] != "PROMOTED":
                    raise MemoryStateError(
                        f"superseded memory {supersedes} must be PROMOTED, "
                        f"got {target['state']}"
                    )
                self._assert_same_memory_domain(candidate, target)
                conn.execute(
                    update(memories)
                    .where(
                        memories.c.memory_id == supersedes,
                        memories.c.state == "PROMOTED",
                    )
                    .values(state="SUPERSEDED")
                )

            affected = conn.execute(
                update(memories)
                .where(
                    memories.c.memory_id == memory_id,
                    memories.c.state == "CANDIDATE",
                )
                .values(state="PROMOTED")
            ).rowcount
            if affected != 1:
                raise MemoryStateError(
                    f"memory {memory_id} changed during promotion"
                )

            self._journal(
                conn,
                event_type="MEMORY_PROMOTED",
                actor="SYSTEM",
                related_id=memory_id,
                conversation_id=candidate["conversation_id"],
                task_id=candidate["task_id"],
                payload={
                    "scope": candidate["scope"],
                    "source_type": candidate["source_type"],
                    "supersedes": supersedes,
                },
                occurred_at=now,
            )
            row = conn.execute(
                select(memories).where(memories.c.memory_id == memory_id)
            ).mappings().one()

        return self._record(row)

    def reject(self, memory_id: str) -> MemoryRecord:
        with self.database.transaction() as conn:
            current = conn.execute(
                select(memories).where(memories.c.memory_id == memory_id)
            ).mappings().one_or_none()
            if current is None:
                raise KeyError(f"unknown memory: {memory_id}")
            if current["state"] != "CANDIDATE":
                raise MemoryStateError(
                    f"memory {memory_id} must be CANDIDATE, "
                    f"got {current['state']}"
                )
            affected = conn.execute(
                update(memories)
                .where(
                    memories.c.memory_id == memory_id,
                    memories.c.state == "CANDIDATE",
                )
                .values(state="REJECTED")
            ).rowcount
            if affected != 1:
                raise MemoryStateError(
                    f"memory {memory_id} changed during rejection"
                )
            row = conn.execute(
                select(memories).where(memories.c.memory_id == memory_id)
            ).mappings().one()

        return self._record(row)

    def load(self, memory_id: str) -> MemoryRecord | None:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                select(memories).where(memories.c.memory_id == memory_id)
            ).mappings().one_or_none()
        return None if row is None else self._record(row)

    def list_by_state(
        self,
        state: str,
        *,
        conversation_id: str | None = None,
        task_id: str | None = None,
    ) -> list[MemoryRecord]:
        state = state.strip().upper()
        if state not in MEMORY_STATES:
            raise MemoryPolicyError(f"unsupported memory state: {state}")

        statement = select(memories).where(memories.c.state == state)
        if conversation_id is not None:
            statement = statement.where(
                memories.c.conversation_id == conversation_id
            )
        if task_id is not None:
            statement = statement.where(memories.c.task_id == task_id)

        statement = statement.order_by(
            memories.c.created_at.asc(),
            memories.c.memory_id.asc(),
        )
        with self.database.engine.connect() as conn:
            rows = conn.execute(statement).mappings().all()
        return [self._record(row) for row in rows]

    @staticmethod
    def _validate_scope_for_source(
        scope: str,
        source_type: str,
    ) -> None:
        if scope not in MEMORY_SCOPES:
            raise MemoryPolicyError(f"unsupported memory scope: {scope}")
        if source_type not in SOURCE_TYPES:
            raise MemoryPolicyError(
                f"unsupported provenance source_type: {source_type}"
            )
        if scope not in ALLOWED_SCOPES_BY_SOURCE[source_type]:
            raise MemoryPolicyError(
                f"{source_type} cannot create memory for scope {scope}"
            )

    @staticmethod
    def _validate_scope_identity(
        *,
        scope: str,
        owner_id: str | None,
        conversation_id: str | None,
        task_id: str | None,
    ) -> None:
        if scope == "CONTACT_PROFILE" and not owner_id:
            raise MemoryPolicyError(
                "CONTACT_PROFILE memory requires owner_id"
            )
        if scope == "CONVERSATION_MEMORY" and not conversation_id:
            raise MemoryPolicyError(
                "CONVERSATION_MEMORY requires conversation_id"
            )
        if scope == "TASK_MEMORY" and not task_id:
            raise MemoryPolicyError("TASK_MEMORY requires task_id")

    @staticmethod
    def _assert_same_memory_domain(
        candidate,
        target,
    ) -> None:
        keys = (
            "scope",
            "owner_id",
            "conversation_id",
            "task_id",
        )
        if any(candidate[key] != target[key] for key in keys):
            raise MemoryPolicyError(
                "supersedes target must have the same memory domain"
            )

    @staticmethod
    def _candidate_id(
        *,
        scope: str,
        owner_id: str | None,
        conversation_id: str | None,
        task_id: str | None,
        content: str,
        source_type: str,
        source_message_id: str | None,
        source_event_id: str | None,
    ) -> str:
        if source_message_id is None and source_event_id is None:
            return f"mem-{uuid4()}"

        material = "\x1f".join(
            [
                source_type,
                source_event_id or "",
                source_message_id or "",
                scope,
                owner_id or "",
                conversation_id or "",
                task_id or "",
                content,
            ]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return "mem-" + digest[:32]

    @staticmethod
    def _source_actor(source_type: str) -> str:
        return {
            "SYSTEM": "SYSTEM",
            "USER_SELF": "USER",
            "CONTACT": "CONTACT",
            "AGENT_INFERENCE": "AGENT",
            "IMPORT": "SYSTEM",
        }[source_type]

    @staticmethod
    def _journal(
        conn,
        *,
        event_type: str,
        actor: str,
        related_id: str,
        conversation_id: str | None,
        task_id: str | None,
        payload: dict[str, object],
        occurred_at: str,
    ) -> None:
        conn.execute(
            event_journal.insert().values(
                journal_id=f"journal-{uuid4()}",
                schema_version="0.1.0",
                event_type=event_type,
                actor=actor,
                account_id=None,
                conversation_id=conversation_id,
                task_id=task_id,
                run_id=None,
                related_id=related_id,
                payload_json=json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                occurred_at=occurred_at,
            )
        )

    @staticmethod
    def _record(row) -> MemoryRecord:
        raw_entities = json.loads(row["entities_json"] or "[]")
        if not isinstance(raw_entities, list):
            raw_entities = []

        return MemoryRecord(
            memory_id=row["memory_id"],
            schema_version=row["schema_version"],
            state=row["state"],
            scope=row["scope"],
            owner_id=row["owner_id"],
            conversation_id=row["conversation_id"],
            task_id=row["task_id"],
            content=row["content"],
            entities=tuple(str(value) for value in raw_entities),
            importance=row["importance"],
            trust=float(row["trust"]),
            confidence=row["confidence"],
            source_type=row["source_type"],
            source_message_id=row["source_message_id"],
            source_event_id=row["source_event_id"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            supersedes=row["supersedes"],
            created_at=row["created_at"],
        )
