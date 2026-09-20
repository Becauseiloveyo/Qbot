from __future__ import annotations

from qbot.domain.actions import (
    ActionProposal,
    PolicyDecision,
    PolicyOutcome,
    RiskClass,
)


class BasicActionPolicy:
    """Minimal deterministic R0-R3 gate independent of model instructions."""

    def evaluate(self, proposal: ActionProposal) -> PolicyDecision:
        if proposal.action == "REQUEST_HUMAN":
            return PolicyDecision(
                risk_class=RiskClass.R2,
                outcome=PolicyOutcome.REQUIRE_HUMAN,
                reasons=("proposal explicitly requested human review",),
            )

        mapping = {
            RiskClass.R0: PolicyOutcome.ALLOW,
            RiskClass.R1: PolicyOutcome.ALLOW_AUDIT,
            RiskClass.R2: PolicyOutcome.REQUIRE_HUMAN,
            RiskClass.R3: PolicyOutcome.DENY,
        }
        outcome = mapping[proposal.risk_hint]
        return PolicyDecision(
            risk_class=proposal.risk_hint,
            outcome=outcome,
            reasons=(f"risk class {proposal.risk_hint} -> {outcome}",),
        )
