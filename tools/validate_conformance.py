#!/usr/bin/env python3
"""Validate Qbot v0.1 schemas, fixtures, and cross-record invariants."""

from __future__ import annotations

import json
import sys
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


def assert_invariants(fixture: dict[str, Any], path: Path) -> None:
    given = fixture.get("given", {})
    task = given.get("active_task")
    checkpoint = given.get("checkpoint")
    outbox = given.get("outbox")
    events = given.get("events", [])
    outboxes = given.get("outboxes", [])
    journal_events = given.get("journal_events", [])

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
    }
    for key, schema_name in singular_mapping.items():
        if key in given:
            validate_record(schema_name, given[key], f"{path}:{key}")

    plural_mapping = {
        "events": "event",
        "outboxes": "outbox",
        "journal_events": "journal_event",
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
