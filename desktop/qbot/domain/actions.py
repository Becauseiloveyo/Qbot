from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskClass(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class ActionProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["0.1.0"] = "0.1.0"
    proposal_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str | None = None
    action: Literal["SEND_MESSAGE", "IGNORE", "REQUEST_HUMAN"]
    risk_hint: RiskClass
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason_summary: str | None = None
    source_message_ids: tuple[str, ...] = ()


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    ALLOW_AUDIT = "ALLOW_AUDIT"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"
    DENY = "DENY"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk_class: RiskClass
    outcome: PolicyOutcome
    reasons: tuple[str, ...] = ()
