from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from qbot.config import QbotConfig
from qbot.memory_retrieval import (
    MemoryQuery,
    MemoryRetrievalError,
    MemoryRetriever,
)
from qbot.persistence import Database
from qbot.persistence.memory import MemoryRepository
from qbot.persistence.tables import memories


NOW = datetime(2026, 9, 20, 16, 30, tzinfo=UTC)


class MemoryRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            QbotConfig(database_path=Path(self.tmp.name) / "qbot.db")
        )
        report = self.db.bootstrap()
        self.assertFalse(report.safe_mode)
        self.memory = MemoryRepository(self.db)
        self.retriever = MemoryRetriever(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _promote(self, **kwargs):
        candidate = self.memory.create_candidate(**kwargs)
        return self.memory.promote(candidate.memory_id)

    def test_only_promoted_current_domain_records_are_eligible(self) -> None:
        promoted = self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-1",
            content="project deadline is Friday",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-promoted",
            valid_from="2026-09-20T12:00:00Z",
        )
        self.memory.create_candidate(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-1",
            content="project deadline candidate",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-candidate",
        )
        rejected = self.memory.create_candidate(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-1",
            content="project deadline rejected",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-rejected",
        )
        self.memory.reject(rejected.memory_id)
        self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-2",
            content="project deadline other conversation",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-other",
        )

        old = self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-1",
            content="project deadline was Monday",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-old",
        )
        replacement = self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-1",
            content="project deadline is now Tuesday",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-new",
            supersedes=old.memory_id,
        )

        hits = self.retriever.retrieve(
            MemoryQuery(
                scopes=("CONVERSATION_MEMORY",),
                conversation_id="conv-1",
                text="project deadline",
                limit=10,
            ),
            now=NOW,
        )

        ids = [hit.record.memory_id for hit in hits]
        self.assertIn(promoted.memory_id, ids)
        self.assertIn(replacement.memory_id, ids)
        self.assertNotIn(old.memory_id, ids)
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(hit.record.state == "PROMOTED" for hit in hits))

    def test_scoring_is_deterministic_and_exposes_components(self) -> None:
        recent = self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-score",
            content="tea meeting moved to eight",
            entities=["tea", "meeting"],
            source_type="USER_SELF",
            trust=0.8,
            importance=0.6,
            source_event_id="evt-recent",
            valid_from="2026-09-20T12:00:00Z",
        )
        older = self._promote(
            scope="CONVERSATION_MEMORY",
            conversation_id="conv-score",
            content="tea meeting notes",
            entities=["tea"],
            source_type="USER_SELF",
            trust=1.0,
            importance=1.0,
            source_event_id="evt-older",
            valid_from="2025-09-01T00:00:00Z",
        )

        query = MemoryQuery(
            scopes=("CONVERSATION_MEMORY",),
            conversation_id="conv-score",
            text="tea meeting",
            entities=("meeting",),
        )
        first = self.retriever.retrieve(query, now=NOW)
        second = self.retriever.retrieve(query, now=NOW)

        self.assertEqual(
            [hit.record.memory_id for hit in first],
            [hit.record.memory_id for hit in second],
        )
        self.assertEqual(recent.memory_id, first[0].record.memory_id)
        self.assertEqual(1000, first[0].score.keyword_milli)
        self.assertEqual(1000, first[0].score.entity_milli)
        self.assertEqual(1000, first[0].score.recency_milli)
        self.assertEqual(600, first[0].score.importance_milli)
        self.assertEqual(800, first[0].score.trust_milli)
        self.assertGreater(
            first[0].score.total_points,
            next(
                hit.score.total_points
                for hit in first
                if hit.record.memory_id == older.memory_id
            ),
        )

    def test_owner_scope_isolation_is_strict(self) -> None:
        wanted = self._promote(
            scope="CONTACT_PROFILE",
            owner_id="contact-1",
            content="likes green tea",
            entities=["tea"],
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-contact-1",
        )
        self._promote(
            scope="CONTACT_PROFILE",
            owner_id="contact-2",
            content="likes green tea",
            entities=["tea"],
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-contact-2",
        )

        hits = self.retriever.retrieve(
            MemoryQuery(
                scopes=("CONTACT_PROFILE",),
                owner_id="contact-1",
                text="tea",
            ),
            now=NOW,
        )

        self.assertEqual([wanted.memory_id], [hit.record.memory_id for hit in hits])

    def test_temporal_validity_and_relevance_fail_closed(self) -> None:
        live = self._promote(
            scope="TASK_MEMORY",
            task_id="task-1",
            content="deploy after tests pass",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-live",
            valid_from="2026-09-20T10:00:00Z",
            valid_to="2026-09-21T10:00:00Z",
        )
        self._promote(
            scope="TASK_MEMORY",
            task_id="task-1",
            content="deploy future plan",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-future",
            valid_from="2026-09-21T10:00:00Z",
        )
        self._promote(
            scope="TASK_MEMORY",
            task_id="task-1",
            content="deploy expired plan",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-expired",
            valid_to="2026-09-19T10:00:00Z",
        )
        self._promote(
            scope="TASK_MEMORY",
            task_id="task-1",
            content="unrelated shopping preference",
            source_type="USER_SELF",
            trust=1.0,
            source_event_id="evt-unrelated",
        )

        hits = self.retriever.retrieve(
            MemoryQuery(
                scopes=("TASK_MEMORY",),
                task_id="task-1",
                text="deploy",
            ),
            now=NOW,
        )
        self.assertEqual([live.memory_id], [hit.record.memory_id for hit in hits])

    def test_explicit_domain_identifiers_and_limits_are_required(self) -> None:
        with self.assertRaises(MemoryRetrievalError):
            self.retriever.retrieve(
                MemoryQuery(scopes=("CONVERSATION_MEMORY",), text="x"),
                now=NOW,
            )
        with self.assertRaises(MemoryRetrievalError):
            self.retriever.retrieve(
                MemoryQuery(scopes=("CONTACT_PROFILE",), text="x"),
                now=NOW,
            )
        with self.assertRaises(MemoryRetrievalError):
            self.retriever.retrieve(
                MemoryQuery(scopes=("SYSTEM_POLICY",), limit=0),
                now=NOW,
            )

    def test_limit_and_stable_order_are_repeatable(self) -> None:
        for index in range(3):
            self._promote(
                scope="CONVERSATION_MEMORY",
                conversation_id="conv-limit",
                content=f"same keyword record {index}",
                source_type="USER_SELF",
                trust=0.5,
                importance=0.5,
                source_event_id=f"evt-limit-{index}",
                valid_from="2026-09-20T12:00:00Z",
            )

        query = MemoryQuery(
            scopes=("CONVERSATION_MEMORY",),
            conversation_id="conv-limit",
            text="same keyword",
            limit=2,
        )
        first = self.retriever.retrieve(query, now=NOW)
        second = self.retriever.retrieve(query, now=NOW)

        self.assertEqual(2, len(first))
        self.assertEqual(
            [hit.record.memory_id for hit in first],
            [hit.record.memory_id for hit in second],
        )


    def test_shared_cross_runtime_retrieval_fixture(self) -> None:
        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "tests"
            / "conformance"
            / "memory-retrieval-parity.json"
        )
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

        with self.db.transaction() as conn:
            for item in fixture["given"]["memories"]:
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

        for case in fixture["given"]["retrieval_cases"]:
            with self.subTest(case_id=case["case_id"]):
                raw_query = case["query"]
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
                    case["evaluation_time"].replace("Z", "+00:00")
                )
                hits = self.retriever.retrieve(query, now=now)
                expected = case["expect"]["hits"]

                self.assertEqual(
                    [item["memory_id"] for item in expected],
                    [hit.record.memory_id for hit in hits],
                )
                for hit, expected_hit in zip(hits, expected, strict=True):
                    expected_score = expected_hit["score"]
                    self.assertEqual(expected_score["total_points"], hit.score.total_points)
                    self.assertEqual(expected_score["keyword_milli"], hit.score.keyword_milli)
                    self.assertEqual(expected_score["entity_milli"], hit.score.entity_milli)
                    self.assertEqual(expected_score["recency_milli"], hit.score.recency_milli)
                    self.assertEqual(expected_score["importance_milli"], hit.score.importance_milli)
                    self.assertEqual(expected_score["trust_milli"], hit.score.trust_milli)



if __name__ == "__main__":
    unittest.main()
