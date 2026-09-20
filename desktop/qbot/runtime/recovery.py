from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.transport import QQTransport, TransportCapability


class RecoveryAction(StrEnum):
    RESUME_RUN = "RESUME_RUN"
    SEND_PENDING = "SEND_PENDING"
    RECONCILE_UNKNOWN = "RECONCILE_UNKNOWN"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FINALIZE_SENT_RUN = "FINALIZE_SENT_RUN"
    WAITING_USER = "WAITING_USER"


@dataclass(frozen=True, slots=True)
class RecoveryItem:
    action: RecoveryAction
    run_id: str
    outbox_id: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    items: tuple[RecoveryItem, ...]
    interrupted_sends_reclassified: tuple[str, ...] = ()


class RecoveryPlanner:
    """Build a startup plan without blindly repeating external effects.

    The only mutation performed while planning is the safe local conversion
    SENDING -> SENDING_UNKNOWN after a process restart.
    """

    _NON_TERMINAL_RUNS = (
        "CREATED",
        "RESTORING",
        "REASONING",
        "EXECUTING",
        "WAITING_USER",
    )

    def __init__(
        self,
        *,
        runs: AgentRunRepository,
        outbox: OutboxRepository,
        transport: QQTransport,
    ) -> None:
        self.runs = runs
        self.outbox = outbox
        self.transport = transport

    def plan(self) -> RecoveryPlan:
        interrupted = self.outbox.recover_interrupted_sends()
        items: list[RecoveryItem] = []

        active_runs = self.runs.list_by_status(self._NON_TERMINAL_RUNS)
        for run in active_runs:
            effects = self.outbox.list_for_run(run.run_id)

            if run.status == "WAITING_USER":
                items.append(
                    RecoveryItem(
                        action=RecoveryAction.WAITING_USER,
                        run_id=run.run_id,
                        reason="run is waiting for explicit human input",
                    )
                )
                continue

            if not effects:
                items.append(
                    RecoveryItem(
                        action=RecoveryAction.RESUME_RUN,
                        run_id=run.run_id,
                        reason=f"non-terminal run has no external effect; status={run.status}",
                    )
                )
                continue

            pending = [effect for effect in effects if effect.status == "PENDING"]
            unknown = [
                effect for effect in effects
                if effect.status == "SENDING_UNKNOWN"
            ]
            sent = [effect for effect in effects if effect.status == "SENT"]
            unresolved_other = [
                effect
                for effect in effects
                if effect.status not in {
                    "PENDING",
                    "SENDING_UNKNOWN",
                    "SENT",
                    "CANCELLED",
                }
            ]

            for effect in pending:
                items.append(
                    RecoveryItem(
                        action=RecoveryAction.SEND_PENDING,
                        run_id=run.run_id,
                        outbox_id=effect.outbox_id,
                        reason="durable effect exists but no send attempt is in flight",
                    )
                )

            for effect in unknown:
                if (
                    TransportCapability.DELIVERY_LOOKUP
                    in self.transport.capabilities
                ):
                    action = RecoveryAction.RECONCILE_UNKNOWN
                    reason = (
                        "delivery outcome is unknown; transport supports lookup"
                    )
                else:
                    action = RecoveryAction.MANUAL_REVIEW
                    reason = (
                        "delivery outcome is unknown and transport cannot "
                        "reconcile safely; blind replay is forbidden"
                    )
                items.append(
                    RecoveryItem(
                        action=action,
                        run_id=run.run_id,
                        outbox_id=effect.outbox_id,
                        reason=reason,
                    )
                )

            if unresolved_other:
                for effect in unresolved_other:
                    items.append(
                        RecoveryItem(
                            action=RecoveryAction.MANUAL_REVIEW,
                            run_id=run.run_id,
                            outbox_id=effect.outbox_id,
                            reason=(
                                "external effect is in an unexpected recovery "
                                f"state: {effect.status}"
                            ),
                        )
                    )
                continue

            if (
                run.status == "EXECUTING"
                and sent
                and not pending
                and not unknown
                and all(
                    effect.status in {"SENT", "CANCELLED"}
                    for effect in effects
                )
            ):
                items.append(
                    RecoveryItem(
                        action=RecoveryAction.FINALIZE_SENT_RUN,
                        run_id=run.run_id,
                        reason=(
                            "all external effects are terminal; only the local "
                            "AgentRun completion commit was interrupted"
                        ),
                    )
                )

        items.sort(
            key=lambda item: (
                item.run_id,
                item.outbox_id or "",
                item.action.value,
            )
        )
        return RecoveryPlan(
            items=tuple(items),
            interrupted_sends_reclassified=tuple(
                record.outbox_id for record in interrupted
            ),
        )
