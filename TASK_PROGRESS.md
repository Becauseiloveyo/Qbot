# Qbot Task Progress

Last updated: 2026-09-20
Architecture: Qbot Architecture v1.2 FINAL
Current milestone: v0.5 — Android Standard Runtime
Current branch: `feature/desktop-v0.4-recovery-policy`

## Current objective

Build the first Android standard runtime that mirrors the frozen durable contracts: Kotlin/Compose project, Room persistence, common-spec mappings, recoverable event processing, and a capability-bounded standard QQ adapter.

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
- Added OpenAI-compatible `/chat/completions` provider with runtime-only `SecretStr` API key handling and optional JSON-object mode.
- Added strict `ActionProposalParser`: prose/fenced output, invalid schema, and mismatched AgentRun IDs are rejected rather than repaired heuristically.
- Added model fallback chains scoped only to the LLM call; fallback never replays committed Qbot side effects.
- Added LLM call journal metadata (role/provider/model/usage/message count/token estimate) without prompts or secrets.
- Fixed ContextBuilder/LLM circular dependency by moving prompt-message type to package-neutral `qbot.prompt`.
- Decision contract tokens are included in the total input budget instead of bypassing TokenBudget.
- Added async pluggable `DecisionEngine` interface and `ContextualLlmDecisionEngine` adapter.
- Added `ContextSource` contract whose `load()` is called for every reasoning execution; tests prove changed checkpoints are re-read rather than cached.
- Added Desktop SQLite `tasks`, `task_steps`, and `task_checkpoints` tables and bumped Desktop DB schema to version 2.
- Added read-only `ContextStateRepository` and `DurableSqliteContextSource` that load the active non-terminal Task, matching latest Checkpoint for the current task version, important decisions, and recent messages before each model call.
- Added a regression test that updates Task version/checkpoint between two decisions and proves the second prompt contains only the new checkpoint state.
- After fixes, Desktop Tests #127 / Conformance #153 passed for async decision integration; Desktop Tests #137 / Conformance #163 passed for SQLite-backed Task/Checkpoint context reload.

- Added persistent Persona and ContactProfile tables, default Persona selection, per-contact Persona override, and versioned updates; Desktop DB schema is now version 3.
- `DurableSqliteContextSource` reloads Persona, ContactProfile, active Task, matching Checkpoint, important decisions, and recent messages on every decision.
- Added role-based runtime-only LLM environment configuration for decision/chat/summary/memory with role-specific overrides and non-persisted API keys.
- Added explicit `--agent-mode observe|assist`; default is `observe`, while `assist` wires SQLite context + LLM DecisionEngine through existing Policy + Outbox.
- `REQUEST_HUMAN` is deterministically elevated to R2/REQUIRE_HUMAN even if the model labels it R0.
- Added tests proving R2 actions enter `WAITING_USER` and create zero Outbox effects.
- Added full restart/context-reset integration test: process closes DB/runtime, Task advances to a new version/checkpoint, fresh ContextSource/ModelRouter/model objects are created, and the next reply uses only the new durable state through LLM -> Policy -> Outbox.
- Conformance #190 / Desktop Tests #164 passed for persona/env/assist gating; Conformance #192 / Desktop Tests #166 passed for the full context-reset durable continuation path.
- v0.3 roadmap deliverables are complete.

- Added deterministic `RecoveryPlanner` for non-terminal AgentRuns and Outbox effects.
- Crash-left `SENDING` records are immediately reclassified to `SENDING_UNKNOWN` with a journaled uncertainty event.
- Recovery classifies PENDING as safe send candidates, unknown delivery as reconcile/manual-review depending on `DELIVERY_LOOKUP`, WAITING_USER as preserved, and SENT+EXECUTING as local-only finalization; unknown sends are never blindly replayed.
- Added recovery tests covering reconcile-capable and non-reconcile transports, PENDING effects, local finalization, resumable runs, and WAITING_USER preservation.
- Added `TaskRepository` with atomic `start_step` / `complete_step`: task version + writer epoch guards, one RUNNING step, Task/TaskStep mutation, Checkpoint creation, and Journal entries commit in one transaction.
- Added stale-version/stale-epoch rollback tests and automatic Task completion after the final step.
- Added read-only `JournalRepository.query()` and `qbot-desktop journal` filtering by run/task/conversation/event type; inspection does not bootstrap or mutate an existing DB.
- v0.4 draft PR #4 opened as the recovery/policy validation surface.
- Conformance #213 and Desktop Tests #187 passed after RecoveryPlanner, transactional Task checkpoints, and journal inspection were added.

- Added `RecoveryExecutor` and startup integration. Observe mode reports recovery only; assist mode executes only classified safe actions while MANUAL_REVIEW/WAITING_USER remain deferred.
- Startup assist safely sends durable PENDING effects once, reconciles `SENDING_UNKNOWN` only through delivery lookup, finalizes SENT-but-interrupted AgentRuns locally, and is idempotent across repeated restarts.
- Added startup restart integration tests proving observe performs no send and repeated assist restart does not duplicate an already SENT effect.
- Replaced implicit schema overwrite behavior with explicit Desktop migration registry (v1->v2->v3), SQLite backup before migration, required-table validation, `integrity_check`, `foreign_key_check`, and `last_integrity_check_at` metadata.
- Added in-memory BootstrapReport/Safe Mode state; authoritative `Database.transaction()` mutations are blocked while Safe Mode is active.
- Safe Mode prevents QQ transport startup and RecoveryExecutor execution; `qbot-desktop safe-mode` provides read-only health diagnostics and optional consistent SQLite snapshot export.
- Added migration tests proving the backup retains the pre-migration schema, known v1 migrates to v3, newer/unknown schema enters Safe Mode, and diagnostics do not mutate the database.
- Added crash-injection tests: failure before checkpoint commit rolls back Task+Step+Checkpoint atomically; failure after remote delivery but before local SENT commit restarts as SENDING_UNKNOWN and reconciles without a second send.
- Conformance #226 / Desktop Tests #200 passed for startup RecoveryExecutor integration; Conformance #241 / Desktop Tests #215 passed for backup/migration/Safe Mode; Conformance #243 / Desktop Tests #217 passed for crash-injection recovery.
- v0.4 roadmap deliverables are complete.

## In progress

- Create the Android v0.5 implementation branch and Gradle/Kotlin project skeleton.
- Map the core Task/Checkpoint/AgentRun/Outbox/Event contracts into Room entities and DAOs.

## Not started

- Android application skeleton.
- Android QQ transport adapters.
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

1. Create `feature/android-v0.5-standard-runtime` from the tested v0.4 head.
2. Add Android Gradle project using Kotlin, Jetpack Compose, Room, Coroutines/Flow, WorkManager, and DataStore without coupling Agent Core to QQ-specific APIs.
3. Add Room entities/DAOs for inbound event, AgentRun, Task/TaskStep/Checkpoint, Outbox, Persona/ContactProfile, Journal, and metadata with the same uniqueness/version invariants as Desktop.
4. Add Room migrations from the first schema onward; destructive migration fallback is forbidden.
5. Add platform-neutral Android `QQTransport` capability interface and deterministic FakeTransport for tests.
6. Add recoverable Android event pipeline: normalize -> dedupe -> per-conversation serialization -> AgentRun -> restore durable state.
7. Add standard NotificationListener adapter boundary only after the durable fake end-to-end path passes tests.

## Resume rule

A new AI session must read this file before coding and continue from the first unfinished concrete action unless the user explicitly changes priority.
