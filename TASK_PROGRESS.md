# Qbot Task Progress

Last updated: 2026-09-20
Architecture: Qbot Architecture v1.2 FINAL
Current milestone: v0.3 — LLM + Persona + Context
Current branch: `feature/desktop-v0.3-agent-context`

## Current objective

Build the model-facing layer without weakening durable-state guarantees: provider/router abstraction, Persona + Contact profiles, ContextBuilder with token budgets, and structured ActionProposal generation.

## Completed

- Repository initialized.
- Architecture frozen as **Qbot Architecture v1.2 FINAL**.
- Persistent handoff files added:
  - `AGENTS.md`
  - `TASK_PROGRESS.md`
  - `docs/ARCHITECTURE.md`
  - `docs/ROADMAP.md`
  - `docs/DECISIONS.md`
- Dual runtime strategy fixed:
  - Android: Kotlin / Compose / Room / recoverable event-driven execution.
  - Desktop: Python / FastAPI / SQLite WAL / NapCat-OneBot.
- Durable Task Engine model defined.
- Step checkpoint recovery defined.
- Persistent AgentRun model defined.
- Transactional Outbox with `SENDING_UNKNOWN` recovery defined.
- Input/output idempotency requirements defined.
- Per-conversation serialization defined.
- Hybrid memory + memory staging/provenance defined.
- Prompt-injection and memory-poisoning trust boundary defined.
- Safe Mode, backup, migration, and event journal requirements defined.
- Multi-node single-writer design defined: lease + fencing token + optimistic concurrency.
- Initial common JSON schemas added:
  - normalized event;
  - task/task step;
  - checkpoint;
  - agent run;
  - action proposal;
  - memory;
  - outbox;
  - policy decision;
  - journal event;
  - transport capabilities.
- State machines and invariants documented in `docs/STATE_MACHINES.md`.
- Conformance fixtures added:
  - durable task restore before reasoning;
  - ambiguous external send reconciliation without blind replay.
- All current JSON schema/fixture files were parsed successfully as valid JSON.
- Executable conformance validator added with JSON Schema Draft 2020-12 checks and cross-record invariants.
- GitHub Actions conformance workflow added for Python 3.12.
- `docs/PERSISTENCE.md` now defines equivalent Room/Desktop SQLite keys, transactions, optimistic concurrency, fencing, Outbox, journal, and migration semantics.
- Added conformance fixtures for duplicate inbound events, duplicate Outbox dedupe keys, stale writer epochs, stale Task versions, and journal ordering.
- Validator expanded to check those idempotency, fencing, versioning, checkpoint, and journal invariants.
- Draft PR #1 opened as the v0.1 validation/review surface.
- PR #1 Conformance workflow run #12 completed successfully; schema + invariant validator passed.
- v0.1 common contracts are stable enough for runtime implementation.
- Desktop Python package skeleton added (`desktop/pyproject.toml`).
- Desktop `QbotConfig` added with validated node/database/spec settings.
- SQLite bootstrap added with WAL, foreign keys, busy timeout, `qbot_meta`, and explicit transaction helper.
- Platform-neutral `QQTransport` abstraction added.
- Deterministic `MockTransport` added with idempotent dedupe-key delivery and delivery lookup.
- Unit tests added for SQLite durability settings and MockTransport behavior.
- Desktop GitHub Actions workflow added.
- Added normalized inbound event model and deterministic fingerprinting.
- Added persistent `inbound_events`, `event_journal`, and `agent_runs` tables.
- Added atomic inbound admission transaction with fingerprint dedupe and one primary AgentRun per admitted event.
- Added per-account/conversation async serialization locks.
- Added first durable runtime path: receive -> normalize -> serialize -> admit -> create run.
- Added unit tests for duplicate inbound admission, AgentRun creation, runtime processing, and conversation serialization.
- Desktop Tests run #21 passed and Conformance run #47 passed on the v0.2 stacked PR.
- Added AgentRun repository with durable restore/load and validated state transitions.
- Added persistent Outbox with unique `(account_id, dedupe_key)`, PENDING/SENDING/SENT/FAILED/SENDING_UNKNOWN transitions, and journal writes.
- Added SendExecutor plus MockTransport ambiguous-delivery reconciliation; a delivered-but-unacknowledged message is reconciled without resend.
- Added deterministic ActionProposal + R0-R3 policy gate and a durable mock reply flow.
- DesktopCore can now drive an admitted event through restore -> reasoning -> policy -> Outbox -> transport -> SENT -> AgentRun SUCCEEDED.
- Durable reply and ambiguous recovery tests passed; Desktop Tests #50 and Conformance #76 were successful.
- Added NapCat/OneBot v11 forward WebSocket adapter using the combined `/` endpoint, `echo` request correlation, private/group mapping, Bearer token support, and literal-text `auto_escape=true` sends.
- OneBot adapter intentionally does not advertise DELIVERY_LOOKUP yet, so uncertain sends are never blindly retried.
- Added fake-WebSocket tests proving event/API multiplexing, token header behavior, API response correlation, and timeout -> uncertain-delivery semantics.
- Desktop Tests #61 and Conformance #87 passed after OneBot transport integration.
- Added `docs/DESKTOP_NAPCAT.md` with current NapCat forward-WS setup and safety constraints.
- Added installable `qbot-desktop` CLI with explicit mock/onebot transport selection.
- OneBot token is read only from `QBOT_ONEBOT_TOKEN` at runtime; it is not persisted in normal config.
- Added OneBot connection supervisor with health states and exponential reconnect backoff.
- Added read-only NapCat diagnostic path using OneBot `get_status` and `get_version_info`; diagnostic does not send chat messages.
- Added structured OneBot connect/disconnect logging.
- Added tests for token header, event/API multiplexing, timeout uncertainty, read-only diagnostics, and actual reconnect to a second fake connection.
- Conformance #101 and Desktop Tests #75 passed after CLI/reconnect/diagnostic integration.
- v0.2 implementation is complete enough for v0.3; real NapCat live verification remains an environment check on a machine running QQ/NapCat.
- Added provider-neutral `LlmProvider`, `LlmRequest`, `LlmResponse`, and role-specific `ModelRole` contracts.
- Added deterministic `MockLlmProvider` and `ModelRouter` with independent decision/chat/summary/memory routes.
- Added immutable `Persona` and `ContactProfile` models with stable-prefix rendering.
- Added `ContextBuilder` with a conservative mixed Chinese/ASCII token estimator.
- ContextBuilder treats System/Persona/Active Task/Checkpoint/Current Message as mandatory; optional decisions/memory/summary/recent history are dropped first when budget is tight.
- External contact text is explicitly wrapped as `UNTRUSTED_EXTERNAL_MESSAGE`.
- Added tests proving a short context budget preserves Active Task + Checkpoint, and an impossible budget raises rather than silently dropping durable state.

## In progress

- Validate v0.3 model-facing contracts in CI.
- Next: add OpenAI-compatible HTTP provider after deterministic interfaces pass.

## Not started

- Android application skeleton.
- Android QQ transport adapters.
- LLM router.
- Persona/contact UI.
- Memory retrieval implementation.
- Coordinator and phone/PC synchronization.
- Full management UI.

## v0.1 exit criteria

v0.1 is complete when:

- Common schemas exist for all core persistent/interchange records.
- Task, TaskStep, AgentRun, and Outbox transitions are documented and machine-tested.
- Idempotency, ordering, recovery, trust, and schema-version rules are explicit.
- Conformance fixtures cover normal resume and ambiguous send recovery.
- A small validator can check fixtures and required invariants.
- Android and Desktop persistence mappings are documented.
- No runtime implementation depends on undocumented chat context.

## Known decisions

- No LangChain/LangGraph runtime dependency in v0.x.
- LangGraph-style durable execution concepts are implemented directly.
- No Redis/PostgreSQL/vector DB in the first usable version.
- NapCat is a Desktop transport, not an Android transport.
- Android execution is recoverable/event-driven instead of assuming a permanent daemon.
- Active tasks are loaded directly, not discovered through RAG.
- LLM output is an `ActionProposal`; deterministic validators/policy/executors own side effects.
- Multi-node automatic failover is not enabled until a coordinator can provide a fencing epoch.

## Next concrete actions

1. Run Desktop Tests + Conformance on the v0.3 branch and fix failures.
2. Add OpenAI-compatible HTTP provider with runtime-only API key/base URL configuration.
3. Add structured JSON ActionProposal parser/validator for the decision model.
4. Add model call journaling metadata without persisting secrets.
5. Wire ContextBuilder + ModelRouter into a new decision path while keeping MockLLM as the default test provider.
6. Add retry/fallback rules that never re-run already committed side effects.

## Resume rule

A new AI session must read this file before coding and continue from the first unfinished concrete action unless the user explicitly changes priority.
