# Qbot

Qbot is a persistent personal QQ agent with two deployment targets:

- **Qbot Android** — runs locally on the phone with replaceable Android QQ transport adapters.
- **Qbot Desktop** — runs on PC/server, primarily through NapCat + OneBot.

The two runtimes share the same behavioral contracts, task/checkpoint model, memory rules, policy rules, and conformance tests under `spec/`.

## Core design

Qbot does not rely on the model's chat context as durable memory.

Before each meaningful Agent run it restores:

1. system/persona policy;
2. contact state;
3. active task;
4. latest checkpoint;
5. important decisions/constraints;
6. trusted relevant memories;
7. rolling summary;
8. recent raw messages;
9. current message.

The LLM produces structured **ActionProposals**. Qbot validates them against schema, state-machine rules, action policy, transport capabilities, and writer ownership before performing side effects.

## Durable execution

Long-running work is represented as structured tasks and steps. Progress is checkpointed so a model-context reset, model switch, app restart, Android process kill, network interruption, or later continuation does not require the model to remember prior turns.

Outgoing messages pass through a durable Outbox. Ambiguous sends enter `SENDING_UNKNOWN` and are reconciled rather than blindly resent.

## Repository continuity

For any AI coding agent:

1. read `AGENTS.md`;
2. read `TASK_PROGRESS.md`;
3. read `docs/ARCHITECTURE.md`;
4. continue the first unfinished task recorded in the repository;
5. update `TASK_PROGRESS.md` before ending meaningful work.

Do not use conversation history as the source of truth for project progress.

## Documentation

- `docs/ARCHITECTURE.md` — frozen Qbot Architecture v1.2 FINAL.
- `docs/ROADMAP.md` — v0.1 to v1.0 project plan.
- `docs/STATE_MACHINES.md` — authoritative state transitions and invariants.
- `docs/DECISIONS.md` — architecture decision log.
- `spec/` — shared machine-readable contracts.
- `tests/conformance/` — cross-runtime behavior fixtures.

## Current status

Development is in **v0.1: Common Spec + Durable Core Model**.

See `TASK_PROGRESS.md` for the exact resumable development state.
