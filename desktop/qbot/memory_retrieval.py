from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping, Sequence

from sqlalchemy import select

from qbot.persistence.database import Database
from qbot.persistence.memory import MEMORY_SCOPES, MemoryRecord
from qbot.persistence.tables import memories


class MemoryRetrievalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    scopes: tuple[str, ...]
    text: str = ""
    owner_id: str | None = None
    conversation_id: str | None = None
    task_id: str | None = None
    entities: tuple[str, ...] = ()
    min_trust: float = 0.0
    limit: int = 10


@dataclass(frozen=True, slots=True)
class MemoryScore:
    total_points: int
    keyword_milli: int
    entity_milli: int
    recency_milli: int
    importance_milli: int
    trust_milli: int

    @property
    def total(self) -> float:
        return self.total_points / 100_000


@dataclass(frozen=True, slots=True)
class MemoryHit:
    record: MemoryRecord
    score: MemoryScore


@dataclass(frozen=True, slots=True)
class MemoryScoringWeights:
    keyword: int = 40
    entity: int = 20
    recency: int = 15
    importance: int = 10
    trust: int = 15

    def validate(self) -> None:
        values = (
            self.keyword,
            self.entity,
            self.recency,
            self.importance,
            self.trust,
        )
        if any(value < 0 for value in values):
            raise MemoryRetrievalError("memory scoring weights must be non-negative")
        if sum(values) != 100:
            raise MemoryRetrievalError("memory scoring weights must sum to 100")


_WORD_RE = re.compile(r"[0-9a-z]+|[\u3400-\u4dbf\u4e00-\u9fff]+")
_OWNER_SCOPES = {"USER_PERSONA", "CONTACT_PROFILE"}


class MemoryRetriever:
    """Deterministic read-only retrieval over authoritative promoted memory.

    This module freezes filtering and scoring semantics before any FTS or
    embedding-backed candidate accelerator is introduced. Future indexes may
    reduce the candidate set, but must not change eligibility or ranking.
    """

    def __init__(
        self,
        database: Database,
        *,
        weights: MemoryScoringWeights | None = None,
    ) -> None:
        self.database = database
        self.weights = weights or MemoryScoringWeights()
        self.weights.validate()

    def retrieve(
        self,
        query: MemoryQuery,
        *,
        now: datetime | None = None,
    ) -> list[MemoryHit]:
        scopes = self._validate_query(query)
        instant = self._normalize_now(now or datetime.now(UTC))
        terms = _terms(query.text)
        query_entities = _normalized_unique(query.entities)
        requires_relevance = bool(terms or query_entities)

        statement = (
            select(memories)
            .where(
                memories.c.state == "PROMOTED",
                memories.c.scope.in_(scopes),
                memories.c.trust >= query.min_trust,
            )
            .order_by(memories.c.memory_id.asc())
        )
        with self.database.engine.connect() as conn:
            rows = conn.execute(statement).mappings().all()

        hits: list[MemoryHit] = []
        for row in rows:
            if not self._domain_matches(row, query):
                continue
            if not self._is_temporally_valid(row, instant):
                continue

            record = _record(row)
            keyword_milli = self._keyword_score(record, terms)
            entity_milli = self._entity_score(record, query_entities)
            if requires_relevance and keyword_milli == 0 and entity_milli == 0:
                continue

            recency_milli = self._recency_score(record, instant)
            importance_milli = _unit_to_milli(
                record.importance if record.importance is not None else 0.5
            )
            trust_milli = _unit_to_milli(record.trust)
            total = (
                keyword_milli * self.weights.keyword
                + entity_milli * self.weights.entity
                + recency_milli * self.weights.recency
                + importance_milli * self.weights.importance
                + trust_milli * self.weights.trust
            )
            hits.append(
                MemoryHit(
                    record=record,
                    score=MemoryScore(
                        total_points=total,
                        keyword_milli=keyword_milli,
                        entity_milli=entity_milli,
                        recency_milli=recency_milli,
                        importance_milli=importance_milli,
                        trust_milli=trust_milli,
                    ),
                )
            )

        hits.sort(key=self._sort_key)
        return hits[: query.limit]

    @staticmethod
    def _validate_query(query: MemoryQuery) -> tuple[str, ...]:
        if not query.scopes:
            raise MemoryRetrievalError("at least one memory scope is required")
        scopes = tuple(dict.fromkeys(scope.strip().upper() for scope in query.scopes))
        unknown = sorted(set(scopes) - MEMORY_SCOPES)
        if unknown:
            raise MemoryRetrievalError(
                "unsupported memory scopes: " + ", ".join(unknown)
            )
        if any(scope in _OWNER_SCOPES for scope in scopes) and not query.owner_id:
            raise MemoryRetrievalError(
                "owner_id is required for USER_PERSONA/CONTACT_PROFILE retrieval"
            )
        if "CONVERSATION_MEMORY" in scopes and not query.conversation_id:
            raise MemoryRetrievalError(
                "conversation_id is required for CONVERSATION_MEMORY retrieval"
            )
        if "TASK_MEMORY" in scopes and not query.task_id:
            raise MemoryRetrievalError(
                "task_id is required for TASK_MEMORY retrieval"
            )
        if not 0.0 <= float(query.min_trust) <= 1.0:
            raise MemoryRetrievalError("min_trust must be between 0 and 1")
        if query.limit <= 0 or query.limit > 100:
            raise MemoryRetrievalError("limit must be between 1 and 100")
        return scopes

    @staticmethod
    def _domain_matches(row: Mapping[str, object], query: MemoryQuery) -> bool:
        scope = str(row["scope"])
        if scope in _OWNER_SCOPES:
            return row["owner_id"] == query.owner_id
        if scope == "CONVERSATION_MEMORY":
            return row["conversation_id"] == query.conversation_id
        if scope == "TASK_MEMORY":
            return row["task_id"] == query.task_id
        return scope == "SYSTEM_POLICY"

    @staticmethod
    def _is_temporally_valid(
        row: Mapping[str, object],
        now: datetime,
    ) -> bool:
        valid_from_raw = row["valid_from"]
        valid_to_raw = row["valid_to"]
        if valid_from_raw is not None:
            valid_from = _parse_timestamp(str(valid_from_raw))
            if valid_from is None or now < valid_from:
                return False
        if valid_to_raw is not None:
            valid_to = _parse_timestamp(str(valid_to_raw))
            if valid_to is None or now >= valid_to:
                return False
        return True

    @staticmethod
    def _keyword_score(record: MemoryRecord, terms: tuple[str, ...]) -> int:
        if not terms:
            return 0
        searchable = _normalize_text(
            " ".join((record.content, *record.entities))
        )
        matched = sum(1 for term in terms if term in searchable)
        return matched * 1000 // len(terms)

    @staticmethod
    def _entity_score(
        record: MemoryRecord,
        query_entities: tuple[str, ...],
    ) -> int:
        if not query_entities:
            return 0
        record_entities = set(_normalized_unique(record.entities))
        matched = sum(1 for entity in query_entities if entity in record_entities)
        return matched * 1000 // len(query_entities)

    @staticmethod
    def _recency_score(record: MemoryRecord, now: datetime) -> int:
        anchor = _parse_timestamp(record.valid_from) if record.valid_from else None
        if anchor is None:
            anchor = _parse_timestamp(record.created_at)
        if anchor is None:
            return 0

        age_seconds = max(0.0, (now - anchor).total_seconds())
        age_days = age_seconds / 86_400
        if age_days <= 1:
            return 1000
        if age_days <= 7:
            return 850
        if age_days <= 30:
            return 700
        if age_days <= 180:
            return 450
        if age_days <= 365:
            return 250
        return 100

    @staticmethod
    def _sort_key(hit: MemoryHit) -> tuple[object, ...]:
        created = _parse_timestamp(hit.record.created_at)
        created_stamp = created.timestamp() if created is not None else float("-inf")
        return (
            -hit.score.total_points,
            -hit.score.keyword_milli,
            -hit.score.entity_milli,
            -hit.score.recency_milli,
            -hit.score.importance_milli,
            -hit.score.trust_milli,
            -created_stamp,
            hit.record.memory_id,
        )

    @staticmethod
    def _normalize_now(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise MemoryRetrievalError("now must be timezone-aware")
        return value.astimezone(UTC)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(normalized.split())


def _terms(value: str) -> tuple[str, ...]:
    normalized = _normalize_text(value)
    return tuple(dict.fromkeys(_WORD_RE.findall(normalized)))


def _normalized_unique(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _normalize_text(raw)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _unit_to_milli(value: float) -> int:
    number = min(1.0, max(0.0, float(value)))
    return int(number * 1000 + 0.5)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _record(row: Mapping[str, object]) -> MemoryRecord:
    raw_entities = json.loads(str(row["entities_json"] or "[]"))
    if not isinstance(raw_entities, list):
        raw_entities = []
    return MemoryRecord(
        memory_id=str(row["memory_id"]),
        schema_version=str(row["schema_version"]),
        state=str(row["state"]),
        scope=str(row["scope"]),
        owner_id=_optional_string(row["owner_id"]),
        conversation_id=_optional_string(row["conversation_id"]),
        task_id=_optional_string(row["task_id"]),
        content=str(row["content"]),
        entities=tuple(str(value) for value in raw_entities),
        importance=_optional_float(row["importance"]),
        trust=float(row["trust"]),
        confidence=_optional_float(row["confidence"]),
        source_type=str(row["source_type"]),
        source_message_id=_optional_string(row["source_message_id"]),
        source_event_id=_optional_string(row["source_event_id"]),
        valid_from=_optional_string(row["valid_from"]),
        valid_to=_optional_string(row["valid_to"]),
        supersedes=_optional_string(row["supersedes"]),
        created_at=str(row["created_at"]),
    )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
