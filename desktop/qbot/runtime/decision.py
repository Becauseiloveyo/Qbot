from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from qbot.domain.actions import ActionProposal, RiskClass
from qbot.domain.events import NormalizedEvent


class DecisionEngine(Protocol):
    async def decide(
        self,
        *,
        run_id: str,
        event: NormalizedEvent,
    ) -> ActionProposal:
        ...


class MockDecisionEngine:
    """Deterministic stand-in for the model-facing decision layer."""

    async def decide(
        self,
        *,
        run_id: str,
        event: NormalizedEvent,
    ) -> ActionProposal:
        return ActionProposal(
            proposal_id=f"proposal-{uuid4()}",
            run_id=run_id,
            action="SEND_MESSAGE",
            risk_hint=RiskClass.R0,
            arguments={
                "text": "收到",
                "reply_to_message_id": event.platform_message_id,
                "account_id": event.account_id,
                "conversation_id": event.conversation_id,
            },
            reason_summary="deterministic mock reply for runtime validation",
            source_message_ids=(
                (event.platform_message_id,) if event.platform_message_id else ()
            ),
        )
