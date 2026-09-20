#!/usr/bin/env python3
"""Validate Qbot v0.1 schemas, fixtures, and selected cross-record invariants."""

from __future__ import annotations

import json
import sys
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


def assert_invariants(fixture: dict[str, Any], path: Path) -> None:
    given = fixture.get("given", {})
    task = given.get("active_task")
    checkpoint = given.get("checkpoint")
    outbox = given.get("outbox")

    if task is not None:
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

    if task is not None and checkpoint is not None:
        if checkpoint["task_id"] != task["task_id"]:
            raise ValidationFailure(f"{path}: checkpoint task_id does not match task")
        if checkpoint["task_version"] != task["version"]:
            raise ValidationFailure(
                f"{path}: checkpoint task_version does not match restored task version"
            )

        step_ids = {s["step_id"] for s in task["steps"]}
        referenced = (
            set(checkpoint["completed_step_ids"])
            | set(checkpoint["pending_step_ids"])
        )
        if not referenced.issubset(step_ids):
            raise ValidationFailure(
                f"{path}: checkpoint references step ids absent from task"
            )

    if outbox is not None and outbox["status"] == "SENDING_UNKNOWN":
        expected = fixture.get("expect", {})
        if expected.get("blind_resend") is True:
            raise ValidationFailure(
                f"{path}: SENDING_UNKNOWN fixture may not require blind resend"
            )


def validate_fixture(path: Path) -> None:
    fixture = load_json(path)
    if fixture.get("fixture_version") != "0.1.0":
        raise ValidationFailure(f"{path}: unsupported fixture_version")

    given = fixture.get("given", {})

    mapping = {
        "event": "event",
        "active_task": "task",
        "checkpoint": "checkpoint",
        "outbox": "outbox",
    }
    for key, schema_name in mapping.items():
        if key in given:
            validate_record(schema_name, given[key], f"{path}:{key}")

    assert_invariants(fixture, path)


def main() -> int:
    failures: list[str] = []

    for name, filename in SCHEMA_FILES.items():
        try:
            schema = load_json(SPEC / filename)
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            failures.append(f"schema {name}: {exc}")

    for path in sorted(FIXTURES.glob("*.json")):
        try:
            validate_fixture(path)
            print(f"PASS {path.relative_to(ROOT)}")
        except Exception as exc:
            failures.append(str(exc))

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1

    print(f"Validated {len(SCHEMA_FILES)} schemas and "
          f"{len(list(FIXTURES.glob('*.json')))} fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
