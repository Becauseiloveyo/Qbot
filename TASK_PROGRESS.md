# Qbot Task Progress

Last updated: 2026-09-20
Architecture: Qbot Architecture v1.2 FINAL
Current milestone: v0.7 — Hybrid Memory
Current branch: `feature/v0.7-hybrid-memory`

## Current objective

Build Hybrid Memory as durable, provenance-aware state before retrieval complexity: candidate staging, trust/scope policy, authoritative promotion, append/supersede history, then deterministic keyword/entity/temporal/importance retrieval. Active Task/Checkpoint remains direct-loaded and outside normal memory retrieval.

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

- Android v0.5 Gradle/Compose project created on `feature/android-v0.5-standard-runtime` with AGP 9.4.0, Gradle 9.6, API 37, Room 2.8.5, WorkManager, DataStore, Coroutines, and KSP 2.3.10.
- Android CI installs the Android 17 `platforms;android-37.0` preview SDK package; Robolectric 4.17 tests run on Java 21 with the required module `--add-opens`, while application source/bytecode compatibility remains Java 17.
- Added Room schema v1 mappings for metadata, inbound events, AgentRuns, Tasks/TaskSteps/Checkpoints, Outbox, Journal, Persona, and ContactProfile with equivalent uniqueness/version/fencing fields to Desktop.
- Android Room migration registry is explicit from schema v1 and does not enable destructive fallback.
- Added platform-neutral Android `QQTransport` plus deterministic `FakeTransport` with dedupe-key delivery lookup and simulated acknowledgement loss after remote delivery.
- Added deterministic Android EventNormalizer, per-account/conversation coroutine serialization, and atomic Room inbound admission transaction: fingerprint dedupe + MESSAGE_RECEIVED + one primary AgentRun + RUN_CREATED.
- `AndroidCore` now transitions a new AgentRun to RESTORING and reloads the trigger event, active Task, and checkpoint matching the current Task version before further processing.
- Added validated Android AgentRun state machine with conditional transitions and non-terminal run enumeration for restart recovery.
- Added transactional Android Outbox state machine with `(account_id, dedupe_key)` idempotency, guarded transitions, SEND_UNKNOWN/MESSAGE_SENT journal entries, and crash-left SENDING -> SENDING_UNKNOWN recovery.
- Added Android RecoveryPlanner matching Desktop safety semantics: PENDING may be a safe send candidate; SENDING_UNKNOWN reconciles only with DELIVERY_LOOKUP, otherwise MANUAL_REVIEW; SENT+EXECUTING plans local finalization; blind unknown replay is forbidden.
- Added Android SendExecutor; ambiguous delivered sends reconcile through FakeTransport lookup without incrementing the transport attempt count a second time.
- Added Robolectric/real Room file-database tests for duplicate inbound admission, close/reopen durability, Task/Checkpoint version restore, AgentRun state-machine persistence, Outbox recovery classification, and ambiguous send reconciliation.
- Android Tests #53, Desktop Tests #290, and Conformance #316 all passed after the durable Room/Outbox/recovery test suite and Robolectric Java 21 fixes.
- Draft PR #5 is the Android v0.5 validation surface.

- Added standard Android QQ/TIM NotificationListener transport with package filtering, explicit identity-quality metadata, live RemoteInput/PendingIntent text replies, listener/transport health, and notification-access settings UI.
- Notification-derived account/conversation IDs are explicitly local aliases, not canonical QQ UINs; title fallback is scoped to the notification slot to avoid same-name contact collisions.
- Notification reply actions are ephemeral and never persisted; they are cleared on listener disconnect, transport stop, notification removal, or notification updates without RemoteInput.
- Notification transport intentionally does not advertise DELIVERY_LOOKUP; ambiguous sends remain SENDING_UNKNOWN/MANUAL_REVIEW and are never blindly replayed.
- Added transport send-readiness contract so temporary lack of a live RemoteInput action leaves durable PENDING effects untouched with zero transport attempts.
- Added Android RecoveryExecutor and WorkManager startup/event-driven recovery. Safe PENDING effects send only when the transport is currently ready; successful send/reconcile finalizes an EXECUTING AgentRun once all effects are terminal.
- Notification listener rehydrates reply capability from current active notifications after process restart and retriggers unique recovery whenever a new notification can restore reply capability.
- Recovery wakeups use WorkManager APPEND_OR_REPLACE so a notification arriving while recovery is already running cannot be dropped; the recovery operations remain idempotent.
- Added QbotApplication + AndroidRuntimeHost so the standard notification transport is started at process creation and inbound events are durably admitted/restored.
- Added Robolectric/Room tests for QQ/TIM filtering, RemoteInput dispatch, notification removal/expiry, temporary send unavailability, process restart restore, recovery finalization, deferred PENDING -> capability-returned send, and no-blind-replay behavior.
- Disabled Android automatic app backup for durable agent state; explicit Qbot backup/export remains the intended path.
- CI now verifies Room schema v1 export and uploads qbot-room-schema-v1 as an artifact.
- Android Tests #120, Desktop Tests #360, and Conformance #386 passed at the v0.5 exit point; Room schema verify/upload steps also passed.
- v0.5 roadmap deliverables are complete.

- v0.6 branch `feature/android-v0.6-enhanced-transports` created from the tested v0.5 head; draft PR #6 is the validation surface.
- Added `AdapterTier`, `AdapterHealth`, capability snapshots, deterministic `TransportSelector`, and `TransportRegistry`.
- Added `RoutedSendExecutor`: fallback is allowed only while an effect remains PENDING; once one adapter enters SENDING, no second adapter may automatically replay that Outbox effect.
- Added durable `SEND_STARTED` journaling at the PENDING -> SENDING transaction boundary with the selected stable adapter ID; the common journal schema and conformance fixture now recognize this event.
- Added routed restart recovery: `SENDING_UNKNOWN` looks up the original `SEND_STARTED.transport_id` and can reconcile only through that adapter; cross-adapter lookup/replay is forbidden.
- Startup WorkManager recovery now uses the Android transport registry rather than a notification-only recovery path.
- Added capability-bounded `AccessibilityQQTransport`. It is outbound-only in v0.6 and advertises SEND_TEXT only with a currently valid exact reply session.
- Added scoped `QbotAccessibilityService` for QQ/TIM with explicit user enablement, health reporting, and fail-closed lifecycle handling.
- Added versioned Accessibility UI profiles plus process-local conversation bindings. No unverified QQ/TIM view IDs are hard-coded into production.
- Accessibility sends require an exact conversation token plus exactly one editable composer and one clickable send action. The active window/token is revalidated for each text insertion and each click, including a second validation after text insertion and before the external send action.
- Accessibility service disconnect resets the enhanced transport to STOPPED and clears the reply session; process death requires trusted re-arming rather than restoring stale UI nodes.
- Added Shizuku 13.1.5 as an optional system-capability provider. Installation, binder, and permission state are reported separately; READY advertises only SYSTEM_API_BRIDGE and never infers QQ READ_TEXT/SEND_TEXT/DELIVERY_LOOKUP.
- Shizuku permission is requested only by an explicit local UI action; Qbot remains functional without the Shizuku manager/service.
- Added an experimental/root/hook provider boundary with no LSPosed/root dependency in the standard Android runtime. Experimental adapters are disabled by default and may be configured only before registry initialization.
- Added enhanced status UI for Notification, Accessibility, and Shizuku.
- Added regression tests for pre-send fallback, no fallback after an ambiguous external attempt, stable adapter-ID journaling, original-adapter-only reconciliation, Accessibility exact-addressing/session expiry, conversation changes between text entry and send, Shizuku state/permission mapping, and experimental-provider fail-closed behavior.
- Android Tests #216, Desktop Tests #464, and Conformance #490 all passed on the exact-token v0.6 code head.
- Real QQ/TIM Accessibility UI profiles/view IDs are intentionally not guessed. Live profile calibration/verification against an actual device/app version remains an environment validation item, analogous to live NapCat verification in v0.2.
- v0.6 roadmap deliverables are complete.

- Added Desktop durable Hybrid Memory persistence with schema v4, provenance/trust fields, deterministic candidate idempotency, Candidate -> Promoted/Rejected transitions, append/supersede history, and authoritative MEMORY_PROMOTED journaling.
- Desktop memory policy prevents CONTACT provenance from staging SYSTEM_POLICY or USER_PERSONA state and enforces required scope identity/provenance.
- Added Android Room MemoryEntity parity and bumped Android Room schema to v2 with explicit non-destructive v1->v2 migration.
- Added Android MemoryRepository parity for candidate staging, promotion/rejection, supersede-domain validation, idempotent provenance-derived candidates, and journaled authoritative promotion.
- Added Android Room tests for trust boundaries, provenance requirements, idempotency, append/supersede history, rejected-state protection, and migration registry coverage.
- v0.7 persistence/staging checkpoint passed: Android Tests #224, Desktop Tests #491, and Conformance #517 all succeeded on commit `cfa29a9`.
- Added Desktop deterministic `MemoryRetriever` over authoritative PROMOTED memory with explicit scope/domain requirements and temporal validity filtering.
- Frozen cross-runtime-friendly integer scoring contract: keyword 40%, entity 20%, recency 15%, importance 10%, trust 15%; score components use 0-1000 integer units and deterministic tie-breaking.
- Retrieval excludes CANDIDATE/REJECTED/SUPERSEDED records, wrong owner/conversation/task domains, future/not-yet-valid memory, expired memory, and lexical/entity-irrelevant records when the query supplies relevance signals.
- Added deterministic Desktop retrieval tests for state/domain isolation, stable ranking, component scoring, temporal validity, explicit domain requirements, relevance fail-closed behavior, and repeatable limits.
- ADR-021 records that FTS5/semantic backends may accelerate candidate discovery but cannot change eligibility, trust/domain boundaries, ranking semantics, or Active Task/Checkpoint force-loading.
- Desktop Tests #495 and Conformance #521 passed on deterministic retrieval commit `6aea7f2`; Android Tests #226 later completed successfully.
- Added Android deterministic `MemoryRetriever` parity with PROMOTED-only eligibility, explicit owner/conversation/task domain isolation, temporal validity, relevance fail-closed behavior, min-trust filtering, and the ADR-021 integer scoring weights/tie-break order.
- Android normalization mirrors Desktop NFKC + Unicode case-fold semantics using ICU `UCharacter.foldCase`; recency and created-at ordering preserve sub-second precision rather than reducing timestamps to epoch seconds.
- Added Android Room retrieval regression tests covering authoritative-state/domain isolation, deterministic component scores, temporal validity, relevance filtering, explicit domain requirements, min-trust filtering, stable ordering, and limits.
- Android deterministic retrieval required no Room schema change; schema remains v2 and FTS/index persistence is still deferred until cross-runtime parity fixtures pass.
- Latest retrieval parity checkpoint passed on `de842dc`: Android Tests #231, Desktop Tests #501, and Conformance #527 all succeeded.
- Added shared `tests/conformance/memory-retrieval-parity.json` as the cross-runtime deterministic retrieval oracle. It contains explicit persisted memory rows, fixed evaluation times, query/domain parameters, expected ordered IDs, and expected integer score components.
- Shared retrieval coverage includes PROMOTED-only state filtering, wrong-domain exclusion, future/expired filtering, min-trust filtering, relevance fail-closed behavior, weighted score ordering, Unicode NFKC + case-fold parity, and sub-second created-at tie-breaking.
- `tools/validate_conformance.py` now independently re-evaluates ADR-021 retrieval semantics and rejects fixture expectations that do not match the frozen deterministic contract.
- Desktop and Android retrieval tests consume the exact same shared JSON fixture rather than duplicated platform fixtures. Android Gradle receives the repository root explicitly for unit tests, and Android CI now reruns when the shared retrieval fixture changes.
- Cross-runtime deterministic retrieval parity passed on commit `5ec0aea`: Android Tests #234, Desktop Tests #505, and Conformance #531 all succeeded; Android Room schema remains v2.
- Added optional Desktop SQLite FTS5/trigram candidate acceleration as a disposable derived index; authoritative `memories` and ADR-021 scoring remain unchanged.
- FTS indexes NFKC + Unicode case-fold normalized content/entities, is used only for simple normalized ASCII alphanumeric relevance signals of length >=3, and falls back to deterministic scan for short/non-ASCII/structured/empty/unsupported queries or any FTS error.
- FTS candidate IDs are always rechecked through PROMOTED/state, scope/domain, trust, temporal validity, exact relevance components, ADR-021 integer scoring, and stable tie-break rules before returning results.
- The derived index lazily rebuilds when append-only Memory row count diverges from index row count; it is not part of the authoritative Desktop schema version, so lack of FTS5/trigram support cannot trigger Safe Mode.
- ADR-022 records the disposable/fallback FTS boundary.
- Desktop tests now explicitly prove indexed == scan on the shared parity fixture, Unicode-normalized queries, explicit scan mode, short/non-ASCII fallback, and index rebuild after Memory growth. Desktop #509 ran 92 tests successfully.
- Desktop FTS acceleration checkpoint passed on `09f4090`: Android Tests #236, Desktop Tests #509, and Conformance #535 all succeeded.
- Added Android Room-backed disposable FTS4 candidate acceleration without adding an authoritative Room Entity or schema migration; Room schema remains v2.
- Android FTS stores overlapping ASCII 3-grams derived from the same NFKC + Unicode case-fold normalized content/entities used by ADR-021. It is attempted only for simple normalized ASCII alphanumeric relevance signals of length >=3.
- Android FTS executes one MATCH per relevance signal and unions candidate IDs in Kotlin, avoiding SQLite FTS4 multi-signal OR parser differences; each signal uses implicit-AND 3-gram matching to produce a safe substring candidate superset.
- Short/non-ASCII/structured/empty/unsupported queries and FTS failures fall back to deterministic scan. Candidate IDs are then reloaded from authoritative `memories` and all ADR-021 state/domain/trust/temporal/relevance/scoring/tie-break rules are reapplied.
- The Android derived FTS index lazily rebuilds on append-only Memory row-count divergence and remains outside Room schema export/versioning. ADR-023 records this boundary.
- Android retrieval tests now prove indexed == scan against the shared cross-runtime fixture, explicit scan mode, short/non-ASCII fallback, and index rebuild after Memory growth.
- Initial Android FTS query-composition attempts exposed FTS4 parser differences; final per-signal union implementation passed on `5beb91f`.
- Android FTS checkpoint passed: Android Tests #243, Desktop Tests #517, and Conformance #543 all succeeded; Android Room schema verification/upload also passed.

## In progress

- Add semantic retrieval only as a pluggable, non-authoritative relevance scorer after deterministic + FTS retrieval are stable on both runtimes.
- Freeze semantic scorer interfaces/fallback behavior so embeddings can never bypass ADR-021 eligibility, trust/domain boundaries, temporal validity, or Active Task/Checkpoint direct loading.
- Keep Active Task/Checkpoint direct-loaded and outside normal memory retrieval.

## Not started

- Device-specific verified QQ/TIM Accessibility profile calibration.
- Persona/contact UI.
- Semantic retrieval as a pluggable scorer after deterministic retrieval is stable.
- Background candidate extraction/summarization.
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

1. Define a provider-neutral semantic relevance scorer contract whose output is advisory and cannot alter ADR-021 eligibility; include deterministic no-op/fallback behavior when no embedding backend is configured.
2. Integrate the semantic scorer into Desktop retrieval behind an explicit opt-in path, with deterministic retrieval/FTS remaining sufficient for correctness and with score provenance exposed for audit.
3. Add tests proving semantic scorer failure/unavailability cannot remove mandatory deterministic results, cannot admit ineligible memories, and cannot change Active Task/Checkpoint loading.
4. Mirror the stable semantic scorer contract on Android only after Desktop behavior is frozen, then add cross-runtime contract fixtures where practical.
5. Keep active Task/Checkpoint force-loaded outside memory retrieval.
6. Add background candidate extraction/summarization only after durable staging/promotion and retrieval work independently.
7. Run v0.7 cross-runtime exit tests and update memory/security documentation.

## Resume rule

A new AI session must read this file before coding and continue from the first unfinished concrete action unless the user explicitly changes priority.
