# Qbot Task Progress

Last updated: 2026-09-20
Architecture: Qbot Architecture v1.2 FINAL
Current milestone: v0.1 — Spec + durable core model
Current branch: `feature/android-agent-persistence`

## Current objective

Establish the common contracts and durable execution model that both Android and Desktop implementations must follow.

## Completed

- Repository initialized.
- Android-first and Desktop deployment paths defined.
- Macro architecture frozen as v1.2 FINAL.
- Dual runtime strategy selected:
  - Android: Kotlin/Compose/Room.
  - Desktop: Python/FastAPI/SQLite WAL/NapCat-OneBot.
- Durable Task Engine design agreed.
- Step checkpoint recovery agreed.
- Persistent AgentRun model agreed.
- Transactional Outbox with `SENDING_UNKNOWN` recovery agreed.
- Input/output idempotency requirement agreed.
- Per-conversation serialization agreed.
- Hybrid memory + memory staging/provenance agreed.
- Prompt injection / memory poisoning trust boundary agreed.
- Safe Mode, backup, migration, and event journal requirements agreed.
- Multi-node single-writer design agreed: lease + fencing token + optimistic concurrency.

## In progress

- Write repository continuity documentation.
- Create v0.1 common JSON schemas under `spec/`.
- Define initial state machines and invariants.
- Prepare conformance test vectors shared by Android and Desktop.

## Not started

- Desktop runtime implementation.
- NapCat/OneBot transport.
- Android application skeleton.
- Android QQ transport adapters.
- LLM router.
- Persona/contact UI.
- Memory retrieval implementation.
- Coordinator and phone/PC synchronization.
- Full management UI.

## v0.1 exit criteria

v0.1 is complete when:

- Common schemas exist for events, tasks, checkpoints, agent runs, memories, action proposals, outbox records, and policy decisions.
- Task and AgentRun state transitions are documented and testable.
- Idempotency, ordering, recovery, and schema-version rules are explicit.
- At least one conformance fixture demonstrates:
  - message received,
  - task restored,
  - action proposed,
  - checkpoint committed,
  - outbox created,
  - send result recorded.
- No runtime implementation depends on undocumented chat context.

## Known decisions

- No LangChain/LangGraph runtime dependency in v0.x.
- LangGraph-style durable execution concepts are implemented directly.
- No Redis/PostgreSQL/vector DB in the first usable version.
- NapCat is Desktop transport, not Android transport.
- Android background execution is recoverable/event-driven rather than assuming a permanent daemon.
- Active tasks are loaded directly, not discovered through RAG.

## Next concrete actions

1. Finish the initial `spec/` schemas.
2. Add `docs/STATE_MACHINES.md`.
3. Add first conformance fixtures.
4. Start Desktop v0.2 only after the v0.1 contracts are stable.

## Resume rule

A new AI session must read this file before coding and continue from the first unfinished concrete action unless the user explicitly changes priority.
