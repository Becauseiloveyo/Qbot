from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class SemanticScoreStatus(StrEnum):
    DISABLED = "DISABLED"
    SCORED = "SCORED"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class SemanticScorerUnavailable(RuntimeError):
    """The configured semantic backend is intentionally unavailable."""


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    memory_id: str
    content: str
    entities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticScoringRequest:
    query_text: str
    query_entities: tuple[str, ...]
    candidates: tuple[SemanticCandidate, ...]


@dataclass(frozen=True, slots=True)
class SemanticScore:
    memory_id: str
    score_milli: int


@dataclass(frozen=True, slots=True)
class SemanticAudit:
    status: SemanticScoreStatus
    provider: str | None = None
    model: str | None = None
    score_milli: int | None = None
    error_type: str | None = None


class SemanticRelevanceScorer(ABC):
    """Provider-neutral advisory scorer for already-eligible memories.

    Implementations receive only memories that have already passed Qbot's
    deterministic ADR-021 eligibility rules. Returned scores are advisory
    runtime metadata: they cannot add/remove/reorder memories or mutate
    authoritative state.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    def model_name(self) -> str | None:
        return None

    @abstractmethod
    async def score(
        self,
        request: SemanticScoringRequest,
    ) -> tuple[SemanticScore, ...]:
        raise NotImplementedError


class NoopSemanticRelevanceScorer(SemanticRelevanceScorer):
    """Deterministic fallback when no embedding backend is configured."""

    @property
    def provider_name(self) -> str:
        return "noop"

    async def score(
        self,
        request: SemanticScoringRequest,
    ) -> tuple[SemanticScore, ...]:
        del request
        raise SemanticScorerUnavailable(
            "semantic relevance backend is not configured"
        )
