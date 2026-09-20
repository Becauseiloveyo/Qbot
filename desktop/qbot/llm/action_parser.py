from __future__ import annotations

import json

from pydantic import ValidationError

from qbot.domain.actions import ActionProposal


class ActionProposalParseError(ValueError):
    pass


class ActionProposalParser:
    """Strictly parse model output as one JSON object."""

    def parse(
        self,
        text: str,
        *,
        expected_run_id: str,
    ) -> ActionProposal:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ActionProposalParseError(
                "decision model output is not strict JSON"
            ) from exc

        if not isinstance(raw, dict):
            raise ActionProposalParseError(
                "decision model output must be one JSON object"
            )

        try:
            proposal = ActionProposal.model_validate(raw)
        except ValidationError as exc:
            raise ActionProposalParseError(
                "decision model JSON does not match ActionProposal"
            ) from exc

        if proposal.run_id != expected_run_id:
            raise ActionProposalParseError(
                "decision model proposal run_id does not match active AgentRun"
            )

        return proposal
