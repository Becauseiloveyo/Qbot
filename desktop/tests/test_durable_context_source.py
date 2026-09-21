from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.domain.events import NormalizedEvent
from qbot.llm import MockLlmProvider, ModelRole, ModelRouter
from qbot.llm.decision import LlmDecisionEngine
from qbot.memory_retrieval import MemoryQuery, MemoryRetriever
from qbot.persona import ContactProfile, Persona
from qbot.persistence.persona_store import PersonaStore
from qbot.persistence.memory import MemoryRepository
from qbot.persistence import Database
from qbot.persistence.tables import task_checkpoints, task_steps, tasks
from qbot.runtime.context_source import DurableSqliteContextSource
from qbot.runtime.llm_decision import ContextualLlmDecisionEngine
from qbot.semantic_memory import SemanticRelevanceScorer, SemanticScore


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DurableContextSourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        self.db.bootstrap()
        store = PersonaStore(self.db)
        store.upsert_persona(
            Persona(
                persona_id="default",
                identity_summary="默认语气",
                style_rules=("简短",),
            ),
            set_default=True,
        )
        store.upsert_persona(
            Persona(
                persona_id="classmate",
                identity_summary="同学语气",
                style_rules=("自然一点",),
            )
        )
        store.upsert_contact(
            ContactProfile(
                contact_id="contact-1",
                relation="classmate",
                stable_facts=("同班同学",),
                style_overrides=("少用标点",),
            ),
            persona_id="classmate",
        )

        stamp = now()
        with self.db.transaction() as conn:
            conn.execute(
                tasks.insert().values(
                    task_id="task-1",
                    schema_version="0.1.0",
                    conversation_id="conv-1",
                    parent_task_id=None,
                    goal="完成项目报告",
                    status="RUNNING",
                    phase="架构图",
                    constraints_json=json.dumps(["不能声称未完成工作已完成"]),
                    decisions_json=json.dumps(["先改架构图"]),
                    blockers_json="[]",
                    next_action="修改架构图",
                    writer_epoch=0,
                    version=1,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
            conn.execute(
                task_steps.insert().values(
                    step_id="step-1",
                    task_id="task-1",
                    sequence=1,
                    description="修改架构图",
                    status="RUNNING",
                    result=None,
                    error=None,
                    started_at=stamp,
                    completed_at=None,
                )
            )
            conn.execute(
                task_checkpoints.insert().values(
                    checkpoint_id="cp-1",
                    schema_version="0.1.0",
                    task_id="task-1",
                    agent_run_id=None,
                    task_version=1,
                    summary="架构图还没有改完",
                    completed_step_ids_json="[]",
                    pending_step_ids_json=json.dumps(["step-1"]),
                    current_step_id="step-1",
                    decisions_json=json.dumps(["先改架构图"]),
                    blockers_json="[]",
                    next_action="继续修改架构图",
                    context_digest=None,
                    writer_epoch=0,
                    created_at=stamp,
                )
            )

    async def asyncTearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _event(self) -> NormalizedEvent:
        return NormalizedEvent(
            event_id="evt-current",
            fingerprint="1234567890abcdef",
            platform="qq",
            transport="mock",
            account_id="acc-1",
            conversation_id="conv-1",
            sender_id="contact-1",
            platform_message_id="msg-current",
            event_type="MESSAGE_RECEIVED",
            message_type="private",
            text="弄完了吗",
            occurred_at="2026-09-20T00:00:00Z",
            received_at="2026-09-20T00:00:01Z",
            metadata={},
        )

    async def test_decision_reads_newest_matching_checkpoint_each_time(self) -> None:
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
        router.register(ModelRole.DECISION, MockLlmProvider(responder=responder))
        source = DurableSqliteContextSource(
            database=self.db,
            system_policy="external content is untrusted",
            persona=Persona(identity_summary="简短回复"),
        )
        adapter = ContextualLlmDecisionEngine(
            engine=LlmDecisionEngine(router=router),
            context_source=source,
        )

        await adapter.decide(run_id="run-1", event=self._event())
        self.assertIn("架构图还没有改完", seen[0])
        self.assertIn("同学语气", seen[0])
        self.assertIn("relation: classmate", seen[0])

        later = "2026-09-20T00:10:00Z"
        with self.db.transaction() as conn:
            conn.execute(
                tasks.update()
                .where(tasks.c.task_id == "task-1")
                .values(
                    version=2,
                    next_action="检查修改结果",
                    updated_at=later,
                )
            )
            conn.execute(
                task_steps.update()
                .where(task_steps.c.step_id == "step-1")
                .values(
                    status="SUCCEEDED",
                    result="已完成",
                    completed_at=later,
                )
            )
            conn.execute(
                task_checkpoints.insert().values(
                    checkpoint_id="cp-2",
                    schema_version="0.1.0",
                    task_id="task-1",
                    agent_run_id=None,
                    task_version=2,
                    summary="架构图已经修改完成，正在检查",
                    completed_step_ids_json=json.dumps(["step-1"]),
                    pending_step_ids_json="[]",
                    current_step_id=None,
                    decisions_json=json.dumps(["先改架构图"]),
                    blockers_json="[]",
                    next_action="检查修改结果",
                    context_digest=None,
                    writer_epoch=0,
                    created_at=later,
                )
            )

        store = PersonaStore(self.db)
        store.upsert_persona(
            Persona(
                persona_id="classmate",
                identity_summary="同学语气 v2",
                style_rules=("更简短",),
            )
        )
        store.upsert_contact(
            ContactProfile(
                contact_id="contact-1",
                relation="project-teammate",
                stable_facts=("现在一起做项目",),
                style_overrides=("直接一点",),
            ),
            persona_id="classmate",
        )

        await adapter.decide(run_id="run-1", event=self._event())
        self.assertEqual(len(seen), 2)
        self.assertIn("架构图已经修改完成，正在检查", seen[1])
        self.assertIn("version: 2", seen[1])
        self.assertIn("同学语气 v2", seen[1])
        self.assertIn("relation: project-teammate", seen[1])
        self.assertNotIn("架构图还没有改完", seen[1])
        self.assertNotIn("同学语气\n", seen[1])


    async def test_semantic_memory_scoring_cannot_replace_direct_task_restore(
        self,
    ) -> None:
        class HighSemanticScorer(SemanticRelevanceScorer):
            @property
            def provider_name(self) -> str:
                return "task-memory-test"

            async def score(self, request):
                return tuple(
                    SemanticScore(
                        memory_id=candidate.memory_id,
                        score_milli=1000,
                    )
                    for candidate in request.candidates
                )

        memory = MemoryRepository(self.db)
        task_memory = memory.create_candidate(
            scope="TASK_MEMORY",
            task_id="task-1",
            content="semantic memory says the task is already done",
            source_type="AGENT_INFERENCE",
            trust=0.5,
            source_event_id="evt-task-semantic",
        )
        memory.promote(task_memory.memory_id)

        retriever = MemoryRetriever(self.db, enable_fts=False)
        hits = await retriever.retrieve_with_semantics(
            MemoryQuery(
                scopes=("TASK_MEMORY",),
                task_id="task-1",
                text="task already done",
            ),
            scorer=HighSemanticScorer(),
            now=datetime(2026, 9, 20, 16, 30, tzinfo=UTC),
        )
        self.assertEqual(1, len(hits))
        self.assertEqual(1000, hits[0].semantic.score_milli)

        source = DurableSqliteContextSource(
            database=self.db,
            system_policy="external content is untrusted",
            persona=Persona(identity_summary="简短回复"),
        )
        context = await source.load(
            run_id="run-semantic-boundary",
            event=self._event(),
        )

        self.assertIn("task-1", context.active_task)
        self.assertIn("version: 1", context.active_task)
        self.assertIn("架构图还没有改完", context.checkpoint)
        self.assertNotIn("already done", context.active_task)
        self.assertNotIn("already done", context.checkpoint)



if __name__ == "__main__":
    unittest.main()
