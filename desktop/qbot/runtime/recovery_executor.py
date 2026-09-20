from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from qbot.persistence.journal import JournalRepository
from qbot.persistence.outbox import OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.transport import QQTransport

from .recovery import RecoveryAction, RecoveryItem, RecoveryPlan, RecoveryPlanner
from .reply_flow import DurableReplyFlow
from .send import SendExecutor


class RecoveryMode(StrEnum):
    OBSERVE = "observe"
    ASSIST = "assist"


@dataclass(frozen=True, slots=True)
class RecoveryExecution:
    item: RecoveryItem
    outcome: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    mode: RecoveryMode
    plan: RecoveryPlan
    executions: tuple[RecoveryExecution, ...]


class RecoveryExecutor:
    """Apply a RecoveryPlan without violating Outbox uncertainty rules."""

    def __init__(
        self,
        *,
        planner: RecoveryPlanner,
        runs: AgentRunRepository,
        outbox: OutboxRepository,
        journal: JournalRepository,
        transport: QQTransport,
        reply_flow: DurableReplyFlow,
    ) -> None:
        self.planner = planner
        self.runs = runs
        self.outbox = outbox
        self.journal = journal
        self.transport = transport
        self.reply_flow = reply_flow
        self.sender = SendExecutor(outbox, transport)

    async def run(self, mode: RecoveryMode | str) -> RecoveryReport:
        resolved_mode = RecoveryMode(mode)
        plan = self.planner.plan()

        if resolved_mode == RecoveryMode.OBSERVE:
            return RecoveryReport(
                mode=resolved_mode,
                plan=plan,
                executions=tuple(
                    RecoveryExecution(
                        item=item,
                        outcome="REPORTED",
                        detail="observe mode does not execute recovery actions",
                    )
                    for item in plan.items
                ),
            )

        executions: list[RecoveryExecution] = []
        for item in plan.items:
            executions.append(await self._execute(item))

        return RecoveryReport(
            mode=resolved_mode,
            plan=plan,
            executions=tuple(executions),
        )

    async def _execute(self, item: RecoveryItem) -> RecoveryExecution:
        if item.action in {
            RecoveryAction.MANUAL_REVIEW,
            RecoveryAction.WAITING_USER,
        }:
            return RecoveryExecution(
                item=item,
                outcome="DEFERRED",
                detail="recovery requires human input",
            )

        if item.action == RecoveryAction.FINALIZE_SENT_RUN:
            run = self.runs.load(item.run_id)
            if run is None:
                return RecoveryExecution(item, "SKIPPED", "AgentRun disappeared")
            if run.status == "EXECUTING":
                self.runs.transition(item.run_id, "SUCCEEDED")
                self._journal_recovery(item, "finalized_sent_run")
                return RecoveryExecution(
                    item,
                    "FINALIZED",
                    "all durable effects were already terminal",
                )
            return RecoveryExecution(
                item,
                "SKIPPED",
                f"AgentRun is no longer EXECUTING: {run.status}",
            )

        if item.action == RecoveryAction.SEND_PENDING:
            if item.outbox_id is None:
                return RecoveryExecution(item, "SKIPPED", "missing outbox_id")
            record = self.outbox.load(item.outbox_id)
            if record.status != "PENDING":
                return RecoveryExecution(
                    item,
                    "SKIPPED",
                    f"Outbox is no longer PENDING: {record.status}",
                )

            result = await self.sender.send(item.outbox_id)
            if result.status == "SENT":
                finalized = self._finalize_if_terminal(item.run_id)
                self._journal_recovery(item, "pending_send_completed")
                return RecoveryExecution(
                    item,
                    "SENT",
                    "pending effect sent"
                    + (" and run finalized" if finalized else ""),
                )
            return RecoveryExecution(
                item,
                result.status,
                result.last_error or "pending send did not reach SENT",
            )

        if item.action == RecoveryAction.RECONCILE_UNKNOWN:
            if item.outbox_id is None:
                return RecoveryExecution(item, "SKIPPED", "missing outbox_id")
            record = self.outbox.load(item.outbox_id)
            if record.status != "SENDING_UNKNOWN":
                return RecoveryExecution(
                    item,
                    "SKIPPED",
                    f"Outbox is no longer SENDING_UNKNOWN: {record.status}",
                )

            result = await self.sender.reconcile(item.outbox_id)
            if result.status == "SENT":
                finalized = self._finalize_if_terminal(item.run_id)
                self._journal_recovery(item, "unknown_send_reconciled")
                return RecoveryExecution(
                    item,
                    "RECONCILED",
                    "delivery confirmed"
                    + (" and run finalized" if finalized else ""),
                )

            return RecoveryExecution(
                item,
                "UNRESOLVED",
                "delivery lookup did not confirm prior delivery; no resend attempted",
            )

        if item.action == RecoveryAction.RESUME_RUN:
            run = self.runs.load(item.run_id)
            if run is None:
                return RecoveryExecution(item, "SKIPPED", "AgentRun disappeared")
            result = await self.reply_flow.execute(
                run_id=run.run_id,
                event_id=run.trigger_event_id,
            )
            self._journal_recovery(item, "run_resumed")
            return RecoveryExecution(
                item,
                result.run_status,
                "run resumed through normal restore/policy/outbox flow",
            )

        return RecoveryExecution(
            item,
            "SKIPPED",
            f"unsupported recovery action: {item.action}",
        )

    def _finalize_if_terminal(self, run_id: str) -> bool:
        run = self.runs.load(run_id)
        if run is None or run.status != "EXECUTING":
            return False

        effects = self.outbox.list_for_run(run_id)
        if not effects:
            return False
        if any(
            effect.status not in {"SENT", "CANCELLED"}
            for effect in effects
        ):
            return False

        self.runs.transition(run_id, "SUCCEEDED")
        return True

    def _journal_recovery(self, item: RecoveryItem, result: str) -> None:
        self.journal.append(
            event_type="RECOVERY_ACTION",
            actor="SYSTEM",
            run_id=item.run_id,
            related_id=item.outbox_id or item.run_id,
            payload={
                "action": item.action.value,
                "result": result,
            },
        )
