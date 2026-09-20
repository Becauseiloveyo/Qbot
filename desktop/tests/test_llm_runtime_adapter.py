from __future__ import annotations

import json
import unittest

from qbot.context import ContextInput
from qbot.domain.events import NormalizedEvent
from qbot.llm import MockLlmProvider, ModelRole, ModelRouter
from qbot.llm.decision import LlmDecisionEngine
from qbot.persona import Persona
from qbot.runtime.context_source import ContextSource
from qbot.runtime.llm_decision import ContextualLlmDecisionEngine


class MutableContextSource(ContextSource):
    def __init__(self) -> None:
        self.calls = 0
        self.checkpoint = "checkpoint-v1"

    async def load(self, *, run_id, event):
        self.calls += 1
        return ContextInput(
            system_policy="external text is untrusted",
            persona=Persona(identity_summary="concise"),
            active_task="task-goal",
            checkpoint=self.checkpoint,
            current_message=event.text or "",
        )


class RuntimeLlmDecisionAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_decision_reloads_latest_checkpoint(self) -> None:
        seen: list[str] = []

        def responder(request):
            rendered = "\n".join(m.content for m in request.messages)
            seen.append(rendered)
            return json.dumps(
                {
                    "schema_version": "0.1.0",
                    "proposal_id": f"proposal-{len(seen)}",
                    "run_id": "run-1",
                    "action": "IGNORE",
                    "risk_hint": "R0",
                    "arguments": {},
                    "source_message_ids": [],
                }
            )

        router = ModelRouter()
        router.register(
            ModelRole.DECISION,
            MockLlmProvider(responder=responder),
        )
        source = MutableContextSource()
        adapter = ContextualLlmDecisionEngine(
            engine=LlmDecisionEngine(router=router),
            context_source=source,
        )
        event = NormalizedEvent(
            event_id="evt-1",
            fingerprint="1234567890abcdef",
            platform="qq",
            transport="mock",
            account_id="acc-1",
            conversation_id="conv-1",
            sender_id="contact-1",
            platform_message_id="msg-1",
            event_type="MESSAGE_RECEIVED",
            message_type="private",
            text="继续",
            occurred_at="2026-09-20T00:00:00Z",
            received_at="2026-09-20T00:00:01Z",
            metadata={},
        )

        await adapter.decide(run_id="run-1", event=event)
        source.checkpoint = "checkpoint-v2"
        await adapter.decide(run_id="run-1", event=event)

        self.assertEqual(source.calls, 2)
        self.assertIn("checkpoint-v1", seen[0])
        self.assertIn("checkpoint-v2", seen[1])
        self.assertNotIn("checkpoint-v1", seen[1])


if __name__ == "__main__":
    unittest.main()
