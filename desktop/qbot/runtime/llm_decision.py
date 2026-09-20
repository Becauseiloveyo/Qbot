from __future__ import annotations

from qbot.domain.actions import ActionProposal
from qbot.domain.events import NormalizedEvent
from qbot.llm.decision import LlmDecisionEngine

from .context_source import ContextSource


class ContextualLlmDecisionEngine:
    """Runtime adapter that reloads context before every model decision."""

    def __init__(
        self,
        *,
        engine: LlmDecisionEngine,
        context_source: ContextSource,
    ) -> None:
        self.engine = engine
        self.context_source = context_source

    async def decide(
        self,
        *,
        run_id: str,
        event: NormalizedEvent,
    ) -> ActionProposal:
        context = await self.context_source.load(
            run_id=run_id,
            event=event,
        )
        result = await self.engine.decide(
            run_id=run_id,
            context=context,
            account_id=event.account_id,
            conversation_id=event.conversation_id,
        )
        return result.proposal
