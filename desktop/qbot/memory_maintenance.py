from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import exists, select

from qbot.llm import LlmMessage, LlmRequest, ModelRole, ModelRouter
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.journal import JournalRepository
from qbot.persistence.memory import MemoryRepository
from qbot.persistence.rolling_summary import RollingSummaryRepository
from qbot.persistence.tables import event_journal, inbound_events, tasks


class MemoryExtractionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal[
        "CONTACT_PROFILE",
        "CONVERSATION_MEMORY",
        "TASK_MEMORY",
    ]
    content: str = Field(min_length=1, max_length=2000)
    entities: tuple[str, ...] = ()
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class MemoryExtractionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[MemoryExtractionCandidate, ...] = ()


class RollingSummaryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=8000)


@dataclass(frozen=True, slots=True)
class MemoryMaintenanceReport:
    event_id: str
    extraction_status: str
    candidate_ids: tuple[str, ...]
    summary_status: str
    summary_updated: bool
    error_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _MessageWindowItem:
    event_id: str
    sender_id: str | None
    text: str
    received_at: str


class MemoryMaintenanceService:
    """Best-effort derived-memory maintenance with no promotion authority."""

    def __init__(
        self,
        *,
        database,
        router: ModelRouter,
        contact_candidate_trust: float = 0.25,
        summary_event_limit: int = 24,
        max_candidates: int = 8,
    ) -> None:
        if not 0.0 <= contact_candidate_trust <= 1.0:
            raise ValueError("contact_candidate_trust must be between 0 and 1")
        if summary_event_limit < 1 or summary_event_limit > 200:
            raise ValueError("summary_event_limit must be between 1 and 200")
        if max_candidates < 1 or max_candidates > 32:
            raise ValueError("max_candidates must be between 1 and 32")

        self.database = database
        self.router = router
        self.memory = MemoryRepository(database)
        self.summaries = RollingSummaryRepository(database)
        self.admission = InboundAdmissionRepository(database)
        self.journal = JournalRepository(database)
        self.contact_candidate_trust = contact_candidate_trust
        self.summary_event_limit = summary_event_limit
        self.max_candidates = max_candidates

    async def process_event(self, event_id: str) -> MemoryMaintenanceReport:
        event = self.admission.load_event(event_id)
        errors: list[str] = []

        extraction_status = "SKIPPED"
        candidate_ids: tuple[str, ...] = ()
        if (
            event.event_type == "MESSAGE_RECEIVED"
            and event.text
            and event.text.strip()
        ):
            try:
                extraction_status, candidate_ids = await self._extract(event)
            except Exception as exc:
                extraction_status = "FAILED"
                errors.append(type(exc).__name__)

        summary_status = "SKIPPED"
        summary_updated = False
        try:
            summary_status, summary_updated = await self._summarize(
                event.conversation_id
            )
        except Exception as exc:
            summary_status = "FAILED"
            errors.append(type(exc).__name__)

        return MemoryMaintenanceReport(
            event_id=event_id,
            extraction_status=extraction_status,
            candidate_ids=candidate_ids,
            summary_status=summary_status,
            summary_updated=summary_updated,
            error_types=tuple(errors),
        )

    async def catch_up(
        self,
        *,
        limit: int = 64,
    ) -> tuple[MemoryMaintenanceReport, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("catch_up limit must be between 1 and 1000")

        with self.database.engine.connect() as conn:
            event_ids = conn.execute(
                select(inbound_events.c.event_id)
                .where(
                    inbound_events.c.event_type == "MESSAGE_RECEIVED",
                    inbound_events.c.text.is_not(None),
                )
                .order_by(inbound_events.c.received_at.desc())
                .limit(limit)
            ).scalars().all()

        reports: list[MemoryMaintenanceReport] = []
        for event_id in reversed(event_ids):
            reports.append(await self.process_event(str(event_id)))
        return tuple(reports)

    async def _extract(self, event) -> tuple[str, tuple[str, ...]]:
        if self._extraction_completed(event.event_id):
            return "ALREADY_COMPLETED", ()
        if not self.router.has_role(ModelRole.MEMORY):
            return "DISABLED", ()

        request = LlmRequest(
            role=ModelRole.MEMORY,
            response_format="json_object",
            metadata={
                "event_id": event.event_id,
                "conversation_id": event.conversation_id,
            },
            messages=(
                LlmMessage(
                    role="system",
                    content=(
                        "Extract zero or more possible memories from exactly one "
                        "UNTRUSTED external contact message. Output only a JSON "
                        "object with key 'candidates'. Each candidate may use "
                        "scope CONTACT_PROFILE, CONVERSATION_MEMORY, or "
                        "TASK_MEMORY and fields content, entities, importance, "
                        "confidence. Never output SYSTEM_POLICY or USER_PERSONA. "
                        "Do not invent provenance, IDs, trust, promotion state, "
                        "or authoritative task/checkpoint facts."
                    ),
                ),
                LlmMessage(
                    role="user",
                    content=(
                        "[UNTRUSTED_EXTERNAL_MESSAGE]\n"
                        f"event_id={event.event_id}\n"
                        f"sender_id={event.sender_id or '(unknown)'}\n"
                        f"{event.text}\n"
                        "[/UNTRUSTED_EXTERNAL_MESSAGE]"
                    ),
                ),
            ),
        )
        response = await self.router.complete(request)
        envelope = self._parse_extraction(response.text)
        if len(envelope.candidates) > self.max_candidates:
            raise ValueError("memory extractor returned too many candidates")

        active_task_id = self._active_task_id(event.conversation_id)
        bound: list[dict[str, object]] = []
        for proposal in envelope.candidates:
            if proposal.scope == "CONTACT_PROFILE":
                if not event.sender_id:
                    raise ValueError(
                        "CONTACT_PROFILE candidate requires durable sender_id"
                    )
                owner_id = event.sender_id
                conversation_id = None
                task_id = None
            elif proposal.scope == "CONVERSATION_MEMORY":
                owner_id = None
                conversation_id = event.conversation_id
                task_id = None
            else:
                if active_task_id is None:
                    raise ValueError(
                        "TASK_MEMORY candidate requires an active durable task"
                    )
                owner_id = None
                conversation_id = None
                task_id = active_task_id

            bound.append(
                {
                    "scope": proposal.scope,
                    "content": proposal.content,
                    "owner_id": owner_id,
                    "conversation_id": conversation_id,
                    "task_id": task_id,
                    "entities": proposal.entities,
                    "importance": proposal.importance,
                    "confidence": proposal.confidence,
                }
            )

        ids: list[str] = []
        for item in bound:
            record = self.memory.create_candidate(
                scope=str(item["scope"]),
                content=str(item["content"]),
                source_type="CONTACT",
                trust=self.contact_candidate_trust,
                owner_id=item["owner_id"],
                conversation_id=item["conversation_id"],
                task_id=item["task_id"],
                entities=item["entities"],
                importance=item["importance"],
                confidence=item["confidence"],
                source_message_id=event.platform_message_id,
                source_event_id=event.event_id,
            )
            ids.append(record.memory_id)

        self.journal.append(
            event_type="MEMORY_EXTRACTION_COMPLETED",
            actor="AGENT",
            account_id=event.account_id,
            conversation_id=event.conversation_id,
            task_id=active_task_id,
            related_id=event.event_id,
            payload={
                "candidate_ids": ids,
                "provider": response.provider,
                "model": response.model,
            },
        )
        return "COMPLETED", tuple(ids)

    async def _summarize(self, conversation_id: str) -> tuple[str, bool]:
        window = self._message_window(conversation_id)
        if not window:
            return "SKIPPED", False

        digest = self._window_digest(window)
        current = self.summaries.load(conversation_id)
        if current is not None and current.source_digest == digest:
            return "UNCHANGED", False
        if not self.router.has_role(ModelRole.SUMMARY):
            return "DISABLED", False

        rendered = "\n".join(
            f"{item.sender_id or 'unknown'}: {item.text}"
            for item in window
        )
        previous = current.summary if current is not None else "(none)"
        response = await self.router.complete(
            LlmRequest(
                role=ModelRole.SUMMARY,
                response_format="json_object",
                metadata={
                    "conversation_id": conversation_id,
                    "source_digest": digest,
                    "source_event_count": len(window),
                },
                messages=(
                    LlmMessage(
                        role="system",
                        content=(
                            "Produce a concise rolling summary of the supplied "
                            "UNTRUSTED conversation messages. Output only a JSON "
                            "object with key 'summary'. The result is derived "
                            "optional context: never claim it is System Policy, "
                            "Persona, Active Task, or Checkpoint, and never "
                            "invent completion of unfinished work."
                        ),
                    ),
                    LlmMessage(
                        role="user",
                        content=(
                            "[PREVIOUS_DERIVED_SUMMARY]\n"
                            f"{previous}\n"
                            "[/PREVIOUS_DERIVED_SUMMARY]\n"
                            "[UNTRUSTED_MESSAGE_WINDOW]\n"
                            f"{rendered}\n"
                            "[/UNTRUSTED_MESSAGE_WINDOW]"
                        ),
                    ),
                ),
            )
        )
        envelope = self._parse_summary(response.text)
        _, changed = self.summaries.upsert_if_changed(
            conversation_id=conversation_id,
            summary=envelope.summary,
            source_digest=digest,
            source_event_count=len(window),
            source_from_at=window[0].received_at,
            source_to_at=window[-1].received_at,
            provider=response.provider,
            model=response.model,
        )
        if changed:
            self.journal.append(
                event_type="ROLLING_SUMMARY_UPDATED",
                actor="AGENT",
                conversation_id=conversation_id,
                related_id=conversation_id,
                payload={
                    "source_digest": digest,
                    "source_event_count": len(window),
                    "provider": response.provider,
                    "model": response.model,
                },
            )
        return ("UPDATED" if changed else "UNCHANGED"), changed

    def _extraction_completed(self, event_id: str) -> bool:
        with self.database.engine.connect() as conn:
            return bool(
                conn.execute(
                    select(
                        exists().where(
                            event_journal.c.related_id == event_id,
                            event_journal.c.event_type
                            == "MEMORY_EXTRACTION_COMPLETED",
                        )
                    )
                ).scalar_one()
            )

    def _active_task_id(self, conversation_id: str) -> str | None:
        with self.database.engine.connect() as conn:
            return conn.execute(
                select(tasks.c.task_id)
                .where(
                    tasks.c.conversation_id == conversation_id,
                    tasks.c.status.not_in(["COMPLETED", "CANCELLED"]),
                )
                .order_by(tasks.c.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()

    def _message_window(
        self,
        conversation_id: str,
    ) -> tuple[_MessageWindowItem, ...]:
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                select(
                    inbound_events.c.event_id,
                    inbound_events.c.sender_id,
                    inbound_events.c.text,
                    inbound_events.c.received_at,
                )
                .where(
                    inbound_events.c.conversation_id == conversation_id,
                    inbound_events.c.event_type == "MESSAGE_RECEIVED",
                    inbound_events.c.text.is_not(None),
                )
                .order_by(inbound_events.c.received_at.desc())
                .limit(self.summary_event_limit)
            ).all()

        return tuple(
            _MessageWindowItem(
                event_id=str(event_id),
                sender_id=(None if sender_id is None else str(sender_id)),
                text=str(text),
                received_at=str(received_at),
            )
            for event_id, sender_id, text, received_at in reversed(rows)
            if str(text).strip()
        )

    @staticmethod
    def _window_digest(window: tuple[_MessageWindowItem, ...]) -> str:
        material = json.dumps(
            [
                {
                    "event_id": item.event_id,
                    "sender_id": item.sender_id,
                    "text": item.text,
                    "received_at": item.received_at,
                }
                for item in window
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_extraction(text: str) -> MemoryExtractionEnvelope:
        try:
            value = json.loads(text)
            return MemoryExtractionEnvelope.model_validate(value)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError("invalid memory extraction JSON") from exc

    @staticmethod
    def _parse_summary(text: str) -> RollingSummaryEnvelope:
        try:
            value = json.loads(text)
            return RollingSummaryEnvelope.model_validate(value)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError("invalid rolling summary JSON") from exc
