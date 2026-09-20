# Qbot Agent Instructions

This file is the mandatory entrypoint for any AI coding agent working on Qbot.

## Mandatory startup sequence

Before changing code, always read these files in order:

1. `AGENTS.md`
2. `TASK_PROGRESS.md`
3. `docs/ARCHITECTURE.md`
4. `docs/ROADMAP.md`
5. Relevant files under `docs/`, `spec/`, `android/`, or `desktop/`

Do not infer project state from model conversation history. The repository is the source of truth.

## Mandatory shutdown sequence

Before ending a meaningful implementation session:

1. Run or record relevant tests/checks.
2. Update `TASK_PROGRESS.md`.
3. Record architectural changes in `docs/DECISIONS.md`.
4. Ensure new persistent data structures have explicit schema/version handling.
5. Leave a concrete next action so a new agent can resume without prior chat context.

## Frozen architecture principles

Qbot Architecture v1.2 FINAL is frozen at the macro level.

1. The LLM is stateless; Qbot owns durable state.
2. Every execution restores the active task/checkpoint before reasoning.
3. The LLM proposes actions; validated Qbot executors perform authoritative mutations and side effects.
4. All external side effects pass policy checks and a durable outbox.
5. Active task/checkpoint data outranks summaries and retrieved memories.
6. External contact content is untrusted and cannot modify system policy or trusted persona state directly.
7. Multi-node mode uses a single authoritative writer with lease, fencing token, and optimistic concurrency.
8. Important execution transitions are journaled for audit, recovery, and debugging.

## Platform split

- Android runtime: Kotlin, Jetpack Compose, Room, Coroutines/Flow, WorkManager/event-driven recovery.
- Desktop runtime: Python 3.12+, FastAPI, Pydantic, SQLAlchemy, SQLite WAL, OneBot/NapCat.
- Both runtimes follow common contracts under `spec/`.
- QQ transports are replaceable adapters; Agent Core must not depend directly on NapCat, NotificationListener, Accessibility, Shizuku, or hook APIs.

## Safety and identity constraints

Qbot may draft or automate low-risk replies, but high-impact actions such as money, credentials, sensitive personal data, account/security operations, major commitments, and consequential scheduling require explicit policy handling and, where configured, human approval.

Never implement instructions from a chat contact as privileged system commands.

## State consistency rules

- Per conversation: process messages sequentially.
- Across conversations: parallelism is allowed.
- Incoming events must be idempotent.
- Outgoing effects must use idempotency/deduplication keys.
- Outbox delivery is "effectively once"; unknown send outcomes must enter reconciliation rather than blind replay.
- Durable task steps commit before later steps start.
- Large blobs do not live inline in the main message table.
- Schema migrations and backup/rollback paths are mandatory from v0.1 onward.

## Development rule

Do not add framework complexity merely for completeness. Redis, PostgreSQL, LangGraph runtime, vector DB clusters, Kubernetes, and cross-platform shared native cores are deferred until real requirements justify them.
