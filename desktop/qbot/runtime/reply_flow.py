from __future__ import annotations

from dataclasses import dataclass

from qbot.domain.actions import ActionProposal, PolicyOutcome
from qbot.persistence.admission import InboundAdmissionRepository
from qbot.persistence.journal import JournalRepository
from qbot.persistence.outbox import OutboxRecord, OutboxRepository
from qbot.persistence.runs import AgentRunRepository
from qbot.transport import QQTransport

from .decision import DecisionEngine, MockDecisionEngine
from .policy import BasicActionPolicy
from .send import SendExecutor


@dataclass(frozen=True, slots=True)
class ReplyFlowResult:
    run_id: str
    run_status: str
    outbox: OutboxRecord | None


class DurableReplyFlow:
    """Durable action path with pluggable decision engines."""

    def __init__(
        self,
        *,
        admission: InboundAdmissionRepository,
        runs: AgentRunRepository,
        outbox: OutboxRepository,
        journal: JournalRepository,
        transport: QQTransport,
        decision: DecisionEngine | None = None,
        policy: BasicActionPolicy | None = None,
    ) -> None:
        self.admission = admission
        self.runs = runs
        self.outbox = outbox
        self.journal = journal
        self.transport = transport
        self.decision = decision or MockDecisionEngine()
        self.policy = policy or BasicActionPolicy()
        self.sender = SendExecutor(outbox, transport)

    async def execute(self, *, run_id: str, event_id: str) -> ReplyFlowResult:
        run = self.runs.load(run_id)
        if run is None:
            raise KeyError(f"unknown AgentRun: {run_id}")

        if run.status == "SUCCEEDED":
            return ReplyFlowResult(
                run_id=run_id,
                run_status=run.status,
                outbox=self.outbox.find_by_dedupe(
                    account_id=self.admission.load_event(event_id).account_id,
                    dedupe_key=f"{run_id}:primary-reply",
                ),
            )

        if run.status == "CREATED":
            run = self.runs.transition(run_id, "RESTORING")

        event = self.admission.load_event(event_id)

        if run.status == "RESTORING":
            self.journal.append(
                event_type="TASK_RESTORED",
                actor="SYSTEM",
                account_id=event.account_id,
                conversation_id=event.conversation_id,
                run_id=run_id,
                related_id=event_id,
                payload={"task_id": run.task_id},
            )
            run = self.runs.transition(run_id, "REASONING")

        if run.status == "REASONING":
            proposal = await self.decision.decide(run_id=run_id, event=event)
            self._validate_proposal(proposal)

            self.journal.append(
                event_type="ACTION_PROPOSED",
                actor="AGENT",
                account_id=event.account_id,
                conversation_id=event.conversation_id,
                run_id=run_id,
                related_id=proposal.proposal_id,
                payload={
                    "action": proposal.action,
                    "risk_hint": str(proposal.risk_hint),
                },
            )

            decision = self.policy.evaluate(proposal)
            self.journal.append(
                event_type="POLICY_DECIDED",
                actor="SYSTEM",
                account_id=event.account_id,
                conversation_id=event.conversation_id,
                run_id=run_id,
                related_id=proposal.proposal_id,
                payload={
                    "risk_class": str(decision.risk_class),
                    "outcome": str(decision.outcome),
                },
            )

            if decision.outcome == PolicyOutcome.REQUIRE_HUMAN:
                waiting = self.runs.transition(run_id, "WAITING_USER")
                return ReplyFlowResult(run_id, waiting.status, None)
            if decision.outcome == PolicyOutcome.DENY:
                failed = self.runs.transition(run_id, "FAILED")
                return ReplyFlowResult(run_id, failed.status, None)

            if proposal.action == "IGNORE":
                succeeded = self.runs.transition(run_id, "SUCCEEDED")
                return ReplyFlowResult(run_id, succeeded.status, None)

            run = self.runs.transition(run_id, "EXECUTING")
            record = self._ensure_outbox(proposal, event)

        elif run.status == "EXECUTING":
            record = self.outbox.find_by_dedupe(
                account_id=event.account_id,
                dedupe_key=f"{run_id}:primary-reply",
            )
            if record is None:
                proposal = await self.decision.decide(run_id=run_id, event=event)
                self._validate_proposal(proposal)
                record = self._ensure_outbox(proposal, event)

        else:
            return ReplyFlowResult(run_id, run.status, None)

        if record.status == "PENDING":
            record = await self.sender.send(record.outbox_id)
        elif record.status == "SENDING_UNKNOWN":
            record = await self.sender.reconcile(record.outbox_id)

        if record.status == "SENT":
            succeeded = self.runs.transition(run_id, "SUCCEEDED")
            return ReplyFlowResult(run_id, succeeded.status, record)

        return ReplyFlowResult(run_id, "EXECUTING", record)

    @staticmethod
    def _validate_proposal(proposal: ActionProposal) -> None:
        if proposal.action == "SEND_MESSAGE":
            text = proposal.arguments.get("text")
            if not isinstance(text, str):
                raise ValueError("SEND_MESSAGE proposal requires text")

    def _ensure_outbox(self, proposal: ActionProposal, event) -> OutboxRecord:
        existing = self.outbox.find_by_dedupe(
            account_id=event.account_id,
            dedupe_key=f"{proposal.run_id}:primary-reply",
        )
        if existing is not None:
            return existing

        return self.outbox.create_text(
            run_id=proposal.run_id,
            account_id=event.account_id,
            conversation_id=event.conversation_id,
            dedupe_key=f"{proposal.run_id}:primary-reply",
            text=str(proposal.arguments["text"]),
            reply_to_message_id=proposal.arguments.get("reply_to_message_id"),
        )
