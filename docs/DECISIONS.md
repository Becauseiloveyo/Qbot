# Architecture Decision Log

## ADR-001 — Two runtimes, one specification

Decision: Android and Desktop use platform-appropriate implementations while conforming to common schemas and invariants under `spec/`.

Reason: forcing one runtime across Android and Desktop would increase platform risk and build complexity.

## ADR-002 — LLM is not the state store

Decision: model context is ephemeral. Tasks, checkpoints, memory, persona, outbox, and execution state are persisted by Qbot.

Reason: context truncation, model switching, crashes, and long delays must not break task continuity.

## ADR-003 — Action proposals instead of direct model execution

Decision: the model emits structured `ActionProposal` values. Validators, policy, and deterministic executors own actual mutations and side effects.

Reason: reduces hallucination, prompt-injection impact, and invalid state transitions.

## ADR-004 — Step-level durable execution

Decision: AgentRuns and task steps are checkpointed at durable boundaries.

Reason: process death must resume after the last committed step rather than repeat successful work.

## ADR-005 — Transactional outbox with uncertainty state

Decision: outgoing effects use an outbox and include `SENDING_UNKNOWN` for ambiguous external results.

Reason: external messaging systems cannot guarantee atomic commit with the local database.

## ADR-006 — Single-writer synchronized mode

Decision: phone/PC synchronized mode uses lease + fencing epoch + optimistic concurrency. Without a coordinator, failover is manual.

Reason: prevents split-brain duplicate or conflicting replies.

## ADR-007 — Memory staging and provenance

Decision: untrusted messages create candidate memories. Promotion into trusted memory requires policy checks and provenance.

Reason: prevents contact-driven persona poisoning and incorrect permanent state.

## ADR-008 — NapCat is a Desktop adapter

Decision: NapCat/OneBot is the primary Desktop transport, not a foundational Agent Core dependency and not the required Android path.

Reason: preserves portability and matches platform constraints.

## ADR-009 — Android execution is recoverable

Decision: Android runtime assumes process death can happen at any time and persists critical state accordingly.

Reason: Android background execution constraints make permanent-daemon assumptions unsafe.

## ADR-010 — Keep v0.x infrastructure minimal

Decision: SQLite first; no mandatory Redis, PostgreSQL, vector database, Kubernetes, or LangGraph runtime.

Reason: Qbot is initially a single-user personal agent; extra distributed infrastructure would slow iteration without solving current requirements.


## ADR-011 — Persona and contact selection are durable state

Decision: Persona records, ContactProfile records, the default Persona selection, and per-contact Persona overrides are stored in Qbot persistence and reloaded before each model decision.

Reason: style/relationship behavior must survive context truncation, model replacement, and process restarts just like Task/Checkpoint state.

## ADR-012 — Real transports default to observe mode

Decision: the Desktop CLI defaults to `--agent-mode observe`. Model-driven replies require explicit `assist` selection and still pass through ActionProposal validation, deterministic Policy, and the durable Outbox.

Reason: connecting a real QQ transport must not implicitly enable autonomous external side effects.

## ADR-013 — LLM credentials are runtime-only

Decision: OpenAI-compatible provider base URL/model routing may come from environment configuration, but API keys remain runtime secrets (`SecretStr`) and are not persisted to the ordinary Qbot database/config.

Reason: provider credentials are not agent memory or application state and should not leak through backups, prompts, journals, or normal configuration exports.


## ADR-014 — Recovery plans classify before executing

Decision: startup recovery first converts crash-left `SENDING` effects to `SENDING_UNKNOWN`, then builds a deterministic RecoveryPlan. Unknown delivery is reconciled only when the transport advertises `DELIVERY_LOOKUP`; otherwise it requires manual review. A locally `SENT` effect may finalize an interrupted AgentRun without resending.

Reason: restart recovery must distinguish safe local repair from potentially duplicated external side effects.


## ADR-015 — Database startup is backup/migrate/verify or Safe Mode

Decision: Desktop persistence performs an explicit schema-version check. An older known schema is backed up with SQLite's online backup API before a contiguous registered migration runs; the migrated database must pass `PRAGMA integrity_check`, `foreign_key_check`, and required-table validation. Unknown/newer schemas or failed validation enter Safe Mode.

Reason: schema drift or a failed migration must never be hidden by `create_all` or by overwriting the stored schema version.

## ADR-016 — Safe Mode starts no messaging transport

Decision: when database bootstrap enters Safe Mode, Desktop Runtime does not start QQ transport and does not execute startup recovery. Read-only journal/diagnostic operations and consistent database snapshot export remain available.

Reason: inspection and recovery must remain possible without allowing task execution or external side effects against an untrusted database state.


## ADR-017 — Android standard runtime mirrors durable contracts in Room

Decision: Android v0.5 uses native Kotlin/Room implementations of the common Event, AgentRun, Task/Checkpoint, Outbox, Persona/ContactProfile, and Journal contracts. Inbound admission, Outbox creation/transitions, and recovery classification remain transactional/deterministic; Android does not share the Desktop Python runtime.

Reason: cross-platform correctness depends on invariant equivalence, not code reuse. Android lifecycle/process death requires platform-native persistence while preserving the same idempotency and uncertainty semantics.


## ADR-018 — Standard Android notification identities and reply actions are capability-bounded

Decision: the NotificationListener standard adapter treats QQ/TIM notification-derived account/conversation identifiers as local aliases with explicit identity-quality metadata, never as canonical QQ UINs. Shortcut/locus identifiers are preferred; title fallback is scoped to the notification slot to avoid merging same-name contacts. RemoteInput/PendingIntent reply actions are process-local ephemeral capabilities: they are cleared on listener disconnect, transport stop, notification removal, or an update that no longer exposes RemoteInput. They are never persisted. The notification transport does not advertise DELIVERY_LOOKUP.

Reason: Android notification APIs do not guarantee canonical QQ identity or durable delivery history. Conservatively losing reply availability is safer than misrouting a reply or blindly replaying an ambiguous external send.
