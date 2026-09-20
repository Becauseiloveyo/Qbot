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
    """Minimal source until durable Task/Memory repositories are wired.

    This deliberately has no cache. Every call constructs a fresh ContextInput.
    """

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
