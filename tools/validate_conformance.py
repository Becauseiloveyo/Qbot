#!/usr/bin/env python3
"""Validate Qbot v0.1 schemas, fixtures, and cross-record invariants."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec"
FIXTURES = ROOT / "tests" / "conformance"

SCHEMA_FILES = {
    "event": "event.schema.json",
    "task": "task.schema.json",
    "checkpoint": "checkpoint.schema.json",
    "agent_run": "agent-run.schema.json",
    "action_proposal": "action-proposal.schema.json",
    "memory": "memory.schema.json",
    "outbox": "outbox.schema.json",
    "policy_decision": "policy-decision.schema.json",
    "journal_event": "journal-event.schema.json",
    "transport_capabilities": "transport-capabilities.schema.json",
}


class ValidationFailure(Exception):
    pass


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validator(name: str) -> Draft202012Validator:
    schema = load_json(SPEC / SCHEMA_FILES[name])
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_record(name: str, value: dict[str, Any], where: str) -> None:
    errors = sorted(validator(name).iter_errors(value), key=lambda e: list(e.path))
    if errors:
        rendered = "\n".join(
            f"{where}: {'/'.join(map(str, err.path)) or '<root>'}: {err.message}"
            for err in errors
        )
        raise ValidationFailure(rendered)


def validate_records(
    name: str,
    values: list[dict[str, Any]],
    where: str,
) -> None:
    for index, value in enumerate(values):
        validate_record(name, value, f"{where}[{index}]")


def assert_task_invariants(
    fixture: dict[str, Any],
    path: Path,
    task: dict[str, Any],
) -> None:
    running = [s for s in task["steps"] if s["status"] == "RUNNING"]
    if len(running) > 1:
        raise ValidationFailure(f"{path}: active task has more than one RUNNING step")

    if task["status"] == "COMPLETED":
        non_terminal = [
            s for s in task["steps"]
            if s["status"] not in {"SUCCEEDED", "CANCELLED"}
        ]
        if non_terminal:
            raise ValidationFailure(
                f"{path}: COMPLETED task contains non-terminal steps"
            )

    given = fixture.get("given", {})
    attempt = given.get("write_attempt")
    if attempt is None:
        return

    expected = fixture.get("expect", {})
    coordinator_epoch = given.get("coordinator_epoch", task["writer_epoch"])

    if attempt["writer_epoch"] != coordinator_epoch:
        derived_allowed = False
        derived_reason = "STALE_WRITER_EPOCH"
    elif attempt["expected_version"] != task["version"]:
        derived_allowed = False
        derived_reason = "STALE_TASK_VERSION"
    else:
        derived_allowed = True
        derived_reason = None

    if expected.get("authoritative_write_allowed") != derived_allowed:
        raise ValidationFailure(
            f"{path}: authoritative_write_allowed expectation does not match "
            f"derived fencing/version result"
        )

    if not derived_allowed and expected.get("reason") != derived_reason:
        raise ValidationFailure(
            f"{path}: expected rejection reason {expected.get('reason')!r}, "
            f"derived {derived_reason!r}"
        )

    expected_version_after = expected.get("task_version_after")
    if not derived_allowed and expected_version_after != task["version"]:
        raise ValidationFailure(
            f"{path}: rejected write must preserve task version "
            f"{task['version']}"
        )


def assert_checkpoint_invariants(
    fixture: dict[str, Any],
    path: Path,
    task: dict[str, Any] | None,
    checkpoint: dict[str, Any],
) -> None:
    completed = set(checkpoint["completed_step_ids"])
    pending = set(checkpoint["pending_step_ids"])

    if completed & pending:
        raise ValidationFailure(
            f"{path}: checkpoint step cannot be both completed and pending"
        )

    current = checkpoint.get("current_step_id")
    if current is not None and current not in pending:
        raise ValidationFailure(
            f"{path}: checkpoint current_step_id must be pending"
        )

    if task is None:
        return

    if checkpoint["task_id"] != task["task_id"]:
        raise ValidationFailure(f"{path}: checkpoint task_id does not match task")
    if checkpoint["task_version"] != task["version"]:
        raise ValidationFailure(
            f"{path}: checkpoint task_version does not match restored task version"
        )

    step_ids = {s["step_id"] for s in task["steps"]}
    referenced = completed | pending
    if not referenced.issubset(step_ids):
        raise ValidationFailure(
            f"{path}: checkpoint references step ids absent from task"
        )


def assert_event_idempotency(
    fixture: dict[str, Any],
    path: Path,
    events: list[dict[str, Any]],
) -> None:
    if not events:
        return

    expected = fixture.get("expect", {})
    fingerprints = [event["fingerprint"] for event in events]
    unique_count = len(set(fingerprints))

    if "unique_fingerprints" in expected:
        if expected["unique_fingerprints"] != unique_count:
            raise ValidationFailure(
                f"{path}: unique_fingerprints expectation does not match input"
            )

    if "primary_agent_runs_created" in expected:
        if expected["primary_agent_runs_created"] != unique_count:
            raise ValidationFailure(
                f"{path}: primary run count must equal admitted unique events"
            )

    has_duplicate = unique_count < len(events)
    if has_duplicate and expected.get("duplicate_is_noop") is not True:
        raise ValidationFailure(
            f"{path}: duplicate event fixture must require duplicate_is_noop"
        )


def assert_outbox_idempotency(
    fixture: dict[str, Any],
    path: Path,
    outboxes: list[dict[str, Any]],
) -> None:
    if not outboxes:
        return

    expected = fixture.get("expect", {})
    pairs = [(item["account_id"], item["dedupe_key"]) for item in outboxes]
    unique_count = len(set(pairs))

    if "unique_account_dedupe_pairs" in expected:
        if expected["unique_account_dedupe_pairs"] != unique_count:
            raise ValidationFailure(
                f"{path}: unique account/dedupe expectation does not match input"
            )

    if "effects_created" in expected and expected["effects_created"] != unique_count:
        raise ValidationFailure(
            f"{path}: effect count must equal unique account/dedupe pairs"
        )

    has_duplicate = unique_count < len(outboxes)
    if has_duplicate and expected.get("second_insert_rejected") is not True:
        raise ValidationFailure(
            f"{path}: duplicate outbox fixture must reject the second insert"
        )


def assert_journal_invariants(
    fixture: dict[str, Any],
    path: Path,
    events: list[dict[str, Any]],
) -> None:
    if not events:
        return

    expected = fixture.get("expect", {})
    ids = [event["journal_id"] for event in events]
    unique_ids = len(set(ids)) == len(ids)

    if expected.get("journal_ids_unique") is True and not unique_ids:
        raise ValidationFailure(f"{path}: journal IDs are not unique")

    times = [parse_time(event["occurred_at"]) for event in events]
    chronological = times == sorted(times)
    if expected.get("chronological") is True and not chronological:
        raise ValidationFailure(f"{path}: journal is not chronological")

    required_order = expected.get("required_order")
    if required_order is not None:
        actual = [event["event_type"] for event in events]
        if actual != required_order:
            raise ValidationFailure(
                f"{path}: journal event order {actual!r} does not match "
                f"{required_order!r}"
            )


def assert_memory_invariants(
    fixture: dict[str, Any],
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    if not records:
        return

    by_id = {item["memory_id"]: item for item in records}
    for item in records:
        source_type = item["provenance"]["source_type"]
        scope = item["scope"]

        if source_type == "CONTACT" and scope in {
            "SYSTEM_POLICY",
            "USER_PERSONA",
        }:
            raise ValidationFailure(
                f"{path}: CONTACT memory may not target trusted scope {scope}"
            )

        if scope == "SYSTEM_POLICY" and source_type != "SYSTEM":
            raise ValidationFailure(
                f"{path}: SYSTEM_POLICY memory must have SYSTEM provenance"
            )

        supersedes = item.get("supersedes")
        if item["state"] == "PROMOTED" and supersedes is not None:
            old = by_id.get(supersedes)
            if old is None:
                raise ValidationFailure(
                    f"{path}: promoted memory supersedes missing record {supersedes}"
                )
            if old["state"] != "SUPERSEDED":
                raise ValidationFailure(
                    f"{path}: superseded predecessor {supersedes} "
                    f"must be SUPERSEDED"
                )
            domain_keys = (
                "scope",
                "owner_id",
                "conversation_id",
                "task_id",
            )
            if any(item.get(key) != old.get(key) for key in domain_keys):
                raise ValidationFailure(
                    f"{path}: supersede relation crosses memory domain"
                )


_RETRIEVAL_SCOPES = {
    "SYSTEM_POLICY",
    "USER_PERSONA",
    "CONTACT_PROFILE",
    "CONVERSATION_MEMORY",
    "TASK_MEMORY",
}
_RETRIEVAL_OWNER_SCOPES = {"USER_PERSONA", "CONTACT_PROFILE"}
_RETRIEVAL_WORD_RE = re.compile(r"[0-9a-z]+|[\u3400-\u4dbf\u4e00-\u9fff]+")
_RETRIEVAL_WEIGHTS = {
    "keyword_milli": 40,
    "entity_milli": 20,
    "recency_milli": 15,
    "importance_milli": 10,
    "trust_milli": 15,
}


def _retrieval_normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(normalized.split())


def _retrieval_terms(value: str) -> tuple[str, ...]:
    normalized = _retrieval_normalize(value)
    return tuple(dict.fromkeys(_RETRIEVAL_WORD_RE.findall(normalized)))


def _retrieval_entities(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = _retrieval_normalize(raw)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _retrieval_unit_to_milli(value: float) -> int:
    number = min(1.0, max(0.0, float(value)))
    return int(number * 1000 + 0.5)


def _retrieval_recency(record: dict[str, Any], now: datetime) -> int:
    anchor = parse_time(record["valid_from"]) if record.get("valid_from") else None
    if anchor is None:
        anchor = parse_time(record["created_at"])
    age_days = max(0.0, (now - anchor).total_seconds()) / 86_400
    if age_days <= 1:
        return 1000
    if age_days <= 7:
        return 850
    if age_days <= 30:
        return 700
    if age_days <= 180:
        return 450
    if age_days <= 365:
        return 250
    return 100


def _retrieval_domain_matches(
    record: dict[str, Any],
    query: dict[str, Any],
) -> bool:
    scope = record["scope"]
    if scope in _RETRIEVAL_OWNER_SCOPES:
        return record.get("owner_id") == query.get("owner_id")
    if scope == "CONVERSATION_MEMORY":
        return record.get("conversation_id") == query.get("conversation_id")
    if scope == "TASK_MEMORY":
        return record.get("task_id") == query.get("task_id")
    return scope == "SYSTEM_POLICY"


def _validate_retrieval_query(
    query: dict[str, Any],
    path: Path,
    case_id: str,
) -> tuple[str, ...]:
    raw_scopes = query.get("scopes")
    if not isinstance(raw_scopes, list) or not raw_scopes:
        raise ValidationFailure(
            f"{path}:{case_id}: retrieval query requires non-empty scopes"
        )
    scopes = tuple(dict.fromkeys(str(scope).strip().upper() for scope in raw_scopes))
    unknown = sorted(set(scopes) - _RETRIEVAL_SCOPES)
    if unknown:
        raise ValidationFailure(
            f"{path}:{case_id}: unsupported retrieval scopes {unknown!r}"
        )
    if any(scope in _RETRIEVAL_OWNER_SCOPES for scope in scopes) and not query.get(
        "owner_id"
    ):
        raise ValidationFailure(
            f"{path}:{case_id}: owner_id required for owner-scoped retrieval"
        )
    if "CONVERSATION_MEMORY" in scopes and not query.get("conversation_id"):
        raise ValidationFailure(
            f"{path}:{case_id}: conversation_id required for conversation retrieval"
        )
    if "TASK_MEMORY" in scopes and not query.get("task_id"):
        raise ValidationFailure(
            f"{path}:{case_id}: task_id required for task retrieval"
        )
    min_trust = float(query.get("min_trust", 0.0))
    if not 0.0 <= min_trust <= 1.0:
        raise ValidationFailure(
            f"{path}:{case_id}: min_trust must be between 0 and 1"
        )
    limit = int(query.get("limit", 10))
    if limit < 1 or limit > 100:
        raise ValidationFailure(
            f"{path}:{case_id}: limit must be between 1 and 100"
        )
    entities = query.get("entities", [])
    if not isinstance(entities, list) or not all(
        isinstance(value, str) for value in entities
    ):
        raise ValidationFailure(
            f"{path}:{case_id}: query entities must be a string array"
        )
    return scopes


def _evaluate_retrieval_case(
    memories: list[dict[str, Any]],
    case: dict[str, Any],
    path: Path,
) -> list[dict[str, Any]]:
    case_id = str(case.get("case_id") or "<missing-case-id>")
    query = case.get("query")
    if not isinstance(query, dict):
        raise ValidationFailure(f"{path}:{case_id}: missing retrieval query")
    scopes = _validate_retrieval_query(query, path, case_id)

    evaluation_time = case.get("evaluation_time")
    if not isinstance(evaluation_time, str):
        raise ValidationFailure(
            f"{path}:{case_id}: evaluation_time must be a date-time string"
        )
    now = parse_time(evaluation_time)
    terms = _retrieval_terms(str(query.get("text", "")))
    query_entities = _retrieval_entities(query.get("entities", []))
    requires_relevance = bool(terms or query_entities)
    min_trust = float(query.get("min_trust", 0.0))
    limit = int(query.get("limit", 10))

    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for record in memories:
        if record["state"] != "PROMOTED":
            continue
        if record["scope"] not in scopes:
            continue
        if float(record["trust"]) < min_trust:
            continue
        if not _retrieval_domain_matches(record, query):
            continue

        valid_from = record.get("valid_from")
        if valid_from is not None and now < parse_time(valid_from):
            continue
        valid_to = record.get("valid_to")
        if valid_to is not None and now >= parse_time(valid_to):
            continue

        searchable = _retrieval_normalize(
            " ".join([record["content"], *record.get("entities", [])])
        )
        keyword_milli = 0
        if terms:
            keyword_milli = (
                sum(1 for term in terms if term in searchable) * 1000 // len(terms)
            )

        record_entities = set(_retrieval_entities(record.get("entities", [])))
        entity_milli = 0
        if query_entities:
            entity_milli = (
                sum(1 for entity in query_entities if entity in record_entities)
                * 1000
                // len(query_entities)
            )

        if requires_relevance and keyword_milli == 0 and entity_milli == 0:
            continue

        score = {
            "keyword_milli": keyword_milli,
            "entity_milli": entity_milli,
            "recency_milli": _retrieval_recency(record, now),
            "importance_milli": _retrieval_unit_to_milli(
                record.get("importance", 0.5)
            ),
            "trust_milli": _retrieval_unit_to_milli(record["trust"]),
        }
        score["total_points"] = sum(
            score[name] * weight for name, weight in _RETRIEVAL_WEIGHTS.items()
        )

        created_stamp = parse_time(record["created_at"]).timestamp()
        sort_key = (
            -score["total_points"],
            -score["keyword_milli"],
            -score["entity_milli"],
            -score["recency_milli"],
            -score["importance_milli"],
            -score["trust_milli"],
            -created_stamp,
            record["memory_id"],
        )
        ranked.append(
            (
                sort_key,
                {
                    "memory_id": record["memory_id"],
                    "score": {
                        "total_points": score["total_points"],
                        "keyword_milli": score["keyword_milli"],
                        "entity_milli": score["entity_milli"],
                        "recency_milli": score["recency_milli"],
                        "importance_milli": score["importance_milli"],
                        "trust_milli": score["trust_milli"],
                    },
                },
            )
        )

    ranked.sort(key=lambda item: item[0])
    return [item[1] for item in ranked[:limit]]


def assert_retrieval_invariants(
    fixture: dict[str, Any],
    path: Path,
    memories: list[dict[str, Any]],
) -> None:
    cases = fixture.get("given", {}).get("retrieval_cases", [])
    if not cases:
        return
    if not isinstance(cases, list):
        raise ValidationFailure(f"{path}: retrieval_cases must be an array")

    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValidationFailure(f"{path}: retrieval_cases[{index}] must be an object")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValidationFailure(f"{path}: retrieval case requires case_id")
        if case_id in seen_ids:
            raise ValidationFailure(f"{path}: duplicate retrieval case_id {case_id!r}")
        seen_ids.add(case_id)

        expected = case.get("expect", {}).get("hits")
        if not isinstance(expected, list):
            raise ValidationFailure(
                f"{path}:{case_id}: expect.hits must be an array"
            )
        actual = _evaluate_retrieval_case(memories, case, path)
        if actual != expected:
            raise ValidationFailure(
                f"{path}:{case_id}: retrieval result mismatch\n"
                f"expected={expected!r}\nactual={actual!r}"
            )


_SEMANTIC_STATUSES = {
    "DISABLED",
    "SCORED",
    "MISSING",
    "UNAVAILABLE",
    "FAILED",
}


def _semantic_expected_hits(
    *,
    deterministic_ids: list[str],
    scorer: dict[str, Any] | None,
    path: Path,
    case_id: str,
) -> list[dict[str, Any]]:
    if scorer is None:
        return [
            {
                "memory_id": memory_id,
                "semantic": {
                    "status": "DISABLED",
                    "provider": None,
                    "model": None,
                    "score_milli": None,
                    "error_type": None,
                },
            }
            for memory_id in deterministic_ids
        ]

    behavior = scorer.get("behavior")
    provider = scorer.get("provider")
    model = scorer.get("model")
    if not isinstance(provider, str) or not provider.strip():
        raise ValidationFailure(
            f"{path}:{case_id}: semantic scorer provider must be non-empty"
        )
    provider = provider.strip()

    if behavior == "unavailable":
        return [
            {
                "memory_id": memory_id,
                "semantic": {
                    "status": "UNAVAILABLE",
                    "provider": provider,
                    "model": model,
                    "score_milli": None,
                    "error_type": "SemanticScorerUnavailable",
                },
            }
            for memory_id in deterministic_ids
        ]

    if behavior != "scores":
        raise ValidationFailure(
            f"{path}:{case_id}: unsupported semantic scorer behavior {behavior!r}"
        )

    outputs = scorer.get("outputs", [])
    if not isinstance(outputs, list):
        raise ValidationFailure(
            f"{path}:{case_id}: semantic scorer outputs must be an array"
        )

    score_by_id: dict[str, int] = {}
    validation_error = False
    for output in outputs:
        if not isinstance(output, dict):
            validation_error = True
            break
        memory_id = output.get("memory_id")
        score = output.get("score_milli")
        if (
            not isinstance(memory_id, str)
            or memory_id not in deterministic_ids
            or memory_id in score_by_id
            or isinstance(score, bool)
            or not isinstance(score, int)
            or not 0 <= score <= 1000
        ):
            validation_error = True
            break
        score_by_id[memory_id] = score

    if validation_error:
        return [
            {
                "memory_id": memory_id,
                "semantic": {
                    "status": "FAILED",
                    "provider": provider,
                    "model": model,
                    "score_milli": None,
                    "error_type": "MemoryRetrievalError",
                },
            }
            for memory_id in deterministic_ids
        ]

    return [
        {
            "memory_id": memory_id,
            "semantic": {
                "status": (
                    "SCORED" if memory_id in score_by_id else "MISSING"
                ),
                "provider": provider,
                "model": model,
                "score_milli": score_by_id.get(memory_id),
                "error_type": None,
            },
        }
        for memory_id in deterministic_ids
    ]


def assert_semantic_invariants(
    fixture: dict[str, Any],
    path: Path,
    memories: list[dict[str, Any]],
) -> None:
    cases = fixture.get("given", {}).get("semantic_cases", [])
    if not cases:
        return
    if not isinstance(cases, list):
        raise ValidationFailure(f"{path}: semantic_cases must be an array")

    retrieval_cases = fixture.get("given", {}).get("retrieval_cases", [])
    retrieval_by_id = {
        case.get("case_id"): case
        for case in retrieval_cases
        if isinstance(case, dict)
    }
    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValidationFailure(
                f"{path}: semantic_cases[{index}] must be an object"
            )
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValidationFailure(f"{path}: semantic case requires case_id")
        if case_id in seen_ids:
            raise ValidationFailure(
                f"{path}: duplicate semantic case_id {case_id!r}"
            )
        seen_ids.add(case_id)

        retrieval_case_id = case.get("retrieval_case_id")
        retrieval_case = retrieval_by_id.get(retrieval_case_id)
        if retrieval_case is None:
            raise ValidationFailure(
                f"{path}:{case_id}: unknown retrieval_case_id "
                f"{retrieval_case_id!r}"
            )

        deterministic = _evaluate_retrieval_case(
            memories,
            retrieval_case,
            path,
        )
        deterministic_ids = [
            item["memory_id"] for item in deterministic
        ]
        actual_expected = case.get("expect", {}).get("hits")
        if not isinstance(actual_expected, list):
            raise ValidationFailure(
                f"{path}:{case_id}: expect.hits must be an array"
            )

        derived = _semantic_expected_hits(
            deterministic_ids=deterministic_ids,
            scorer=case.get("scorer"),
            path=path,
            case_id=case_id,
        )
        if derived != actual_expected:
            raise ValidationFailure(
                f"{path}:{case_id}: semantic result mismatch\n"
                f"expected={actual_expected!r}\nderived={derived!r}"
            )

        for hit in actual_expected:
            semantic = hit.get("semantic", {})
            if semantic.get("status") not in _SEMANTIC_STATUSES:
                raise ValidationFailure(
                    f"{path}:{case_id}: unsupported semantic status"
                )

def assert_invariants(fixture: dict[str, Any], path: Path) -> None:
    given = fixture.get("given", {})
    task = given.get("active_task")
    checkpoint = given.get("checkpoint")
    outbox = given.get("outbox")
    events = given.get("events", [])
    outboxes = given.get("outboxes", [])
    journal_events = given.get("journal_events", [])
    memory_records = given.get("memories", [])

    if task is not None:
        assert_task_invariants(fixture, path, task)

    if checkpoint is not None:
        assert_checkpoint_invariants(fixture, path, task, checkpoint)

    if outbox is not None and outbox["status"] == "SENDING_UNKNOWN":
        expected = fixture.get("expect", {})
        if expected.get("blind_resend") is True:
            raise ValidationFailure(
                f"{path}: SENDING_UNKNOWN fixture may not require blind resend"
            )

    assert_event_idempotency(fixture, path, events)
    assert_outbox_idempotency(fixture, path, outboxes)
    assert_journal_invariants(fixture, path, journal_events)
    assert_memory_invariants(fixture, path, memory_records)
    assert_retrieval_invariants(fixture, path, memory_records)
    assert_semantic_invariants(fixture, path, memory_records)


def validate_fixture(path: Path) -> None:
    fixture = load_json(path)
    if fixture.get("fixture_version") != "0.1.0":
        raise ValidationFailure(f"{path}: unsupported fixture_version")

    given = fixture.get("given", {})

    singular_mapping = {
        "event": "event",
        "active_task": "task",
        "checkpoint": "checkpoint",
        "outbox": "outbox",
        "memory": "memory",
    }
    for key, schema_name in singular_mapping.items():
        if key in given:
            validate_record(schema_name, given[key], f"{path}:{key}")

    plural_mapping = {
        "events": "event",
        "outboxes": "outbox",
        "journal_events": "journal_event",
        "memories": "memory",
    }
    for key, schema_name in plural_mapping.items():
        if key in given:
            validate_records(schema_name, given[key], f"{path}:{key}")

    assert_invariants(fixture, path)


def main() -> int:
    failures: list[str] = []

    for name, filename in SCHEMA_FILES.items():
        try:
            schema = load_json(SPEC / filename)
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            failures.append(f"schema {name}: {exc}")

    fixture_paths = sorted(FIXTURES.glob("*.json"))
    for path in fixture_paths:
        try:
            validate_fixture(path)
            print(f"PASS {path.relative_to(ROOT)}")
        except Exception as exc:
            failures.append(str(exc))

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print(
        f"Validated {len(SCHEMA_FILES)} schemas and "
        f"{len(fixture_paths)} fixtures."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
