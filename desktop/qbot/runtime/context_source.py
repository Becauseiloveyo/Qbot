from __future__ import annotations

from abc import ABC, abstractmethod

from qbot.context import ContextInput
from qbot.domain.events import NormalizedEvent
from qbot.persona import ContactProfile, Persona


class ContextSource(ABC):
    """Load model context fresh for every reasoning execution."""

    @abstractmethod
    async def load(
        self,
        *,
        run_id: str,
        event: NormalizedEvent,
    ) -> ContextInput:
        raise NotImplementedError


class BasicContextSource(ContextSource):
    """Minimal source for tests and non-persistent prototypes."""

    def __init__(
        self,
        *,
        system_policy: str,
        persona: Persona,
    ) -> None:
        self.system_policy = system_policy
        self.persona = persona

    async def load(
        self,
        *,
        run_id: str,
        event: NormalizedEvent,
    ) -> ContextInput:
        return ContextInput(
            system_policy=self.system_policy,
            persona=self.persona,
            contact=(
                ContactProfile(contact_id=event.sender_id)
                if event.sender_id
                else None
            ),
            active_task=None,
            checkpoint=None,
            current_message=event.text or "",
        )


class DurableSqliteContextSource(ContextSource):
    """Reload Persona, Contact, Task and Checkpoint from SQLite every decision."""

    def __init__(
        self,
        *,
        database,
        system_policy: str,
        persona: Persona | None = None,
    ) -> None:
        from qbot.persistence.context_state import ContextStateRepository
        from qbot.persistence.persona_store import PersonaStore

        self.repository = ContextStateRepository(database)
        self.personas = PersonaStore(database)
        self.system_policy = system_policy
        self.fallback_persona = persona or Persona()

    async def load(
        self,
        *,
        run_id: str,
        event: NormalizedEvent,
    ) -> ContextInput:
        snapshot = self.repository.load(
            conversation_id=event.conversation_id,
            current_event_id=event.event_id,
        )
        persona, contact = self.personas.load_selected(
            contact_id=event.sender_id,
            fallback_persona=self.fallback_persona,
        )
        if contact is None and event.sender_id:
            contact = ContactProfile(contact_id=event.sender_id)

        return ContextInput(
            system_policy=self.system_policy,
            persona=persona,
            contact=contact,
            active_task=snapshot.active_task,
            checkpoint=snapshot.checkpoint,
            important_decisions=snapshot.important_decisions,
            recent_messages=snapshot.recent_messages,
            current_message=event.text or "",
        )
