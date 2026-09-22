from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.memory_retrieval import MemoryQuery, MemoryRetriever
from qbot.persistence import Database
from qbot.persistence.memory import MemoryRepository
from qbot.persistence.tables import memories
from qbot.semantic_memory import (
    NoopSemanticRelevanceScorer,
    SemanticRelevanceScorer,
    SemanticScore,
    SemanticScoreStatus,
)


NOW = datetime(2026, 9, 20, 16, 30, tzinfo=UTC)


class FixedSemanticScorer(SemanticRelevanceScorer):
    def __init__(self, scores: dict[str, int]) -> None:
        self.scores = scores
        self.seen_candidate_ids: tuple[str, ...] = ()

    @property
    def provider_name(self) -> str:
        return "fixed-test"

    @property
    def model_name(self) -> str | None:
        return "semantic-test-v1"

    async def score(self, request):
        self.seen_candidate_ids = tuple(
            candidate.memory_id for candidate in request.candidates
        )
        return tuple(
            SemanticScore(memory_id=memory_id, score_milli=score)
            for memory_id, score in self.scores.items()
        )


class FailingSemanticScorer(SemanticRelevanceScorer):
    @property
    def provider_name(self) -> str:
        return "failing-test"

    async def score(self, request):
        del request
        raise RuntimeError("embedding service unavailable")


class FixtureSemanticScorer(SemanticRelevanceScorer):
    def __init__(
        self,
        *,
        provider: str,
        model: str | None,
        outputs: list[dict[str, object]],
    ) -> None:
        self._provider = provider
        self._model = model
        self._outputs = outputs

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str | None:
        return self._model

    async def score(self, request):
        del request
        return tuple(
            SemanticScore(
                memory_id=str(item["memory_id"]),
                score_milli=int(item["score_milli"]),
            )
            for item in self._outputs
        )


class SemanticMemoryRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        report = self.db.bootstrap()
        self.assertFalse(report.safe_mode)
        self.memory = MemoryRepository(self.db)
        self.retriever = MemoryRetriever(self.db, enable_fts=False)

    async def asyncTearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _promote(self, **kwargs):
        candidate = self.memory.create_candidate(**kwargs)
        return self.memory.promote(candidate.memory_id)

    def _query(self) -> MemoryQuery:
        return MemoryQuery(
            scopes=("CONVERSATION_MEMORY",),
            conversation_id="conv-semantic",
            text="project meeting",
            limit=10,
        )

    def _seed_eligible_pair(self):
        first = self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-semantic",
            content="project meeting moved to eight",
            source_type="USER_SELF",
            trust=0.9,
            importance=0.9,
            source_event_id="evt-semantic-a",
            valid_from="2026-09-20T12:00:00Z",
        )
        second = self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-semantic",
            content="project meeting notes",
            source_type="USER_SELF",
            trust=0.8,
            importance=0.5,
            source_event_id="evt-semantic-b",
            valid_from="2026-09-19T12:00:00Z",
        )
        return first, second

    async def test_semantic_scores_are_advisory_and_do_not_reorder(self) -> None:
        first, second = self._seed_eligible_pair()
        deterministic = self.retriever.retrieve(self._query(), now=NOW)
        self.assertEqual(
            [first.memory_id, second.memory_id],
            [hit.record.memory_id for hit in deterministic],
        )

        scorer = FixedSemanticScorer(
            {
                first.memory_id: 10,
                second.memory_id: 1000,
            }
        )
        enriched = await self.retriever.retrieve_with_semantics(
            self._query(),
            scorer=scorer,
            now=NOW,
        )

        self.assertEqual(
            [hit.record.memory_id for hit in deterministic],
            [hit.record.memory_id for hit in enriched],
        )
        self.assertEqual(
            [hit.score for hit in deterministic],
            [hit.score for hit in enriched],
        )
        self.assertEqual(
            (first.memory_id, second.memory_id),
            scorer.seen_candidate_ids,
        )
        self.assertEqual(10, enriched[0].semantic.score_milli)
        self.assertEqual(1000, enriched[1].semantic.score_milli)
        self.assertTrue(
            all(
                hit.semantic.status == SemanticScoreStatus.SCORED
                for hit in enriched
            )
        )
        self.assertTrue(
            all(hit.semantic.provider == "fixed-test" for hit in enriched)
        )
        self.assertTrue(
            all(hit.semantic.model == "semantic-test-v1" for hit in enriched)
        )

    async def test_missing_backend_is_deterministic_noop(self) -> None:
        self._seed_eligible_pair()
        deterministic = self.retriever.retrieve(self._query(), now=NOW)

        disabled = await self.retriever.retrieve_with_semantics(
            self._query(),
            scorer=None,
            now=NOW,
        )
        unavailable = await self.retriever.retrieve_with_semantics(
            self._query(),
            scorer=NoopSemanticRelevanceScorer(),
            now=NOW,
        )

        self.assertEqual(
            [hit.record.memory_id for hit in deterministic],
            [hit.record.memory_id for hit in disabled],
        )
        self.assertEqual(
            [hit.record.memory_id for hit in deterministic],
            [hit.record.memory_id for hit in unavailable],
        )
        self.assertTrue(
            all(
                hit.semantic.status == SemanticScoreStatus.DISABLED
                for hit in disabled
            )
        )
        self.assertTrue(
            all(
                hit.semantic.status == SemanticScoreStatus.UNAVAILABLE
                for hit in unavailable
            )
        )

    async def test_semantic_failure_cannot_remove_deterministic_hits(self) -> None:
        self._seed_eligible_pair()
        deterministic = self.retriever.retrieve(self._query(), now=NOW)

        enriched = await self.retriever.retrieve_with_semantics(
            self._query(),
            scorer=FailingSemanticScorer(),
            now=NOW,
        )

        self.assertEqual(
            [hit.record.memory_id for hit in deterministic],
            [hit.record.memory_id for hit in enriched],
        )
        self.assertEqual(
            [hit.score for hit in deterministic],
            [hit.score for hit in enriched],
        )
        self.assertTrue(
            all(
                hit.semantic.status == SemanticScoreStatus.FAILED
                for hit in enriched
            )
        )
        self.assertTrue(
            all(hit.semantic.error_type == "RuntimeError" for hit in enriched)
        )

    async def test_semantic_scorer_never_receives_ineligible_memory(self) -> None:
        first, second = self._seed_eligible_pair()
        candidate = self.memory.create_candidate(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-semantic",
            content="project meeting candidate",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-semantic-candidate",
        )
        self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-other",
            content="project meeting other domain",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-semantic-other",
        )

        scorer = FixedSemanticScorer(
            {
                first.memory_id: 500,
                second.memory_id: 500,
            }
        )
        enriched = await self.retriever.retrieve_with_semantics(
            self._query(),
            scorer=scorer,
            now=NOW,
        )

        self.assertEqual(
            {first.memory_id, second.memory_id},
            set(scorer.seen_candidate_ids),
        )
        self.assertNotIn(candidate.memory_id, scorer.seen_candidate_ids)
        self.assertEqual(2, len(enriched))

    async def test_invalid_semantic_output_fails_closed_to_metadata(self) -> None:
        self._seed_eligible_pair()
        deterministic = self.retriever.retrieve(self._query(), now=NOW)
        scorer = FixedSemanticScorer({"not-an-eligible-id": 1000})

        enriched = await self.retriever.retrieve_with_semantics(
            self._query(),
            scorer=scorer,
            now=NOW,
        )

        self.assertEqual(
            [hit.record.memory_id for hit in deterministic],
            [hit.record.memory_id for hit in enriched],
        )
        self.assertTrue(
            all(
                hit.semantic.status == SemanticScoreStatus.FAILED
                for hit in enriched
            )
        )
        self.assertTrue(
            all(
                hit.semantic.error_type == "MemoryRetrievalError"
                for hit in enriched
            )
        )


    async def test_shared_cross_runtime_semantic_contract_fixture(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "tests"
            / "conformance"
            / "memory-retrieval-parity.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        given = fixture["given"]

        with self.db.transaction() as conn:
            for item in given["memories"]:
                provenance = item["provenance"]
                conn.execute(
                    memories.insert().values(
                        schema_version=item["schema_version"],
                        memory_id=item["memory_id"],
                        state=item["state"],
                        scope=item["scope"],
                        owner_id=item.get("owner_id"),
                        conversation_id=item.get("conversation_id"),
                        task_id=item.get("task_id"),
                        content=item["content"],
                        entities_json=json.dumps(
                            item.get("entities", []),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        importance=item.get("importance"),
                        trust=item["trust"],
                        confidence=item.get("confidence"),
                        source_type=provenance["source_type"],
                        source_message_id=provenance.get("source_message_id"),
                        source_event_id=provenance.get("source_event_id"),
                        valid_from=item.get("valid_from"),
                        valid_to=item.get("valid_to"),
                        supersedes=item.get("supersedes"),
                        created_at=item["created_at"],
                    )
                )

        retrieval_cases = {
            case["case_id"]: case
            for case in given["retrieval_cases"]
        }
        for semantic_case in given["semantic_cases"]:
            with self.subTest(case_id=semantic_case["case_id"]):
                retrieval_case = retrieval_cases[
                    semantic_case["retrieval_case_id"]
                ]
                raw_query = retrieval_case["query"]
                query = MemoryQuery(
                    scopes=tuple(raw_query["scopes"]),
                    text=raw_query.get("text", ""),
                    owner_id=raw_query.get("owner_id"),
                    conversation_id=raw_query.get("conversation_id"),
                    task_id=raw_query.get("task_id"),
                    entities=tuple(raw_query.get("entities", [])),
                    min_trust=raw_query.get("min_trust", 0.0),
                    limit=raw_query.get("limit", 10),
                )
                now = datetime.fromisoformat(
                    retrieval_case["evaluation_time"].replace(
                        "Z",
                        "+00:00",
                    )
                )

                raw_scorer = semantic_case.get("scorer")
                if raw_scorer is None:
                    scorer = None
                elif raw_scorer["behavior"] == "unavailable":
                    scorer = NoopSemanticRelevanceScorer()
                else:
                    scorer = FixtureSemanticScorer(
                        provider=raw_scorer["provider"],
                        model=raw_scorer.get("model"),
                        outputs=raw_scorer.get("outputs", []),
                    )

                deterministic = self.retriever.retrieve(query, now=now)
                enriched = await self.retriever.retrieve_with_semantics(
                    query,
                    scorer=scorer,
                    now=now,
                )
                expected = semantic_case["expect"]["hits"]

                self.assertEqual(
                    [hit.record.memory_id for hit in deterministic],
                    [hit.record.memory_id for hit in enriched],
                )
                self.assertEqual(
                    [hit.score for hit in deterministic],
                    [hit.score for hit in enriched],
                )
                self.assertEqual(
                    [item["memory_id"] for item in expected],
                    [hit.record.memory_id for hit in enriched],
                )
                for hit, expected_hit in zip(
                    enriched,
                    expected,
                    strict=True,
                ):
                    audit = expected_hit["semantic"]
                    self.assertEqual(
                        audit["status"],
                        hit.semantic.status.value,
                    )
                    self.assertEqual(
                        audit["provider"],
                        hit.semantic.provider,
                    )
                    self.assertEqual(
                        audit["model"],
                        hit.semantic.model,
                    )
                    self.assertEqual(
                        audit["score_milli"],
                        hit.semantic.score_milli,
                    )
                    self.assertEqual(
                        audit["error_type"],
                        hit.semantic.error_type,
                    )



if __name__ == "__main__":
    unittest.main()
