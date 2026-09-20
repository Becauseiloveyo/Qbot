# Qbot Common Specification

Spec version: 0.1.0

The files in this directory define the common contracts implemented by both Android and Desktop runtimes.

## Rules

- JSON Schema dialect: Draft 2020-12.
- Persistent records include an explicit schema version.
- IDs are opaque strings; implementations may use UUID/ULID internally.
- Timestamps use RFC 3339 UTC strings.
- External contact text is untrusted data.
- LLM outputs are proposals and must validate before execution.
- Active task/checkpoint state is loaded directly rather than retrieved through semantic memory.

## Core contracts

- `event.schema.json`: normalized inbound platform event.
- `task.schema.json`: durable task and task-step state.
- `checkpoint.schema.json`: resumable task snapshot.
- `agent-run.schema.json`: one durable reasoning/execution run.
- `action-proposal.schema.json`: structured model proposal.
- `memory.schema.json`: candidate/promoted memory with provenance.
- `outbox.schema.json`: durable outgoing side effect.
- `policy-decision.schema.json`: policy gate result.

State transition rules are documented in `../docs/STATE_MACHINES.md`.
