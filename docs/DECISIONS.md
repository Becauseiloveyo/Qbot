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


## ADR-019 — Enhanced Android transports negotiate capability before Outbox send

Decision: Android v0.6 introduces common adapter tier/health/capability snapshots and deterministic send selection. Fallback is permitted only while an Outbox effect is still PENDING and before any external adapter attempt. Once the selected adapter enters the durable SENDING boundary, Qbot never automatically tries another adapter for that effect; ambiguous results remain SENDING_UNKNOWN and require reconciliation/manual review.

Accessibility is an optional QQ UI adapter whose SEND_TEXT/READ_TEXT capabilities are advertised only while the relevant QQ/TIM UI is positively recognized. Unknown layouts fail closed. Shizuku is modeled separately as an optional privileged system-capability provider; Shizuku READY does not imply any QQTransport capability. Experimental/root/hook transports remain a separate tier.

Reason: Accessibility UI automation is layout-sensitive, Shizuku grants system-level execution context rather than QQ semantic access, and cross-adapter retry after an ambiguous effect would violate Qbot's effectively-once Outbox invariant.


## ADR-020 — Routed send identity is journaled before the external effect

Decision: for a routed Outbox effect, the selected stable adapter ID is committed as a `SEND_STARTED` journal event in the same transaction that moves the effect from `PENDING` to `SENDING` and increments the transport-attempt counter. The external adapter is called only after that commit. If the outcome later becomes `SENDING_UNKNOWN`, recovery may reconcile only through the adapter ID recorded by `SEND_STARTED`; another adapter may not perform lookup or replay the effect.

Accessibility enhanced sends additionally require a process-local exact conversation binding and a positively verified UI profile. The active conversation token and unambiguous composer/send controls are checked on each UI action; permission or service connectivity alone never implies `SEND_TEXT`.

Reason: multi-adapter fallback is safe only before an external attempt. Persisting the routing identity closes the crash window between adapter selection and result recording, while exact per-action Accessibility validation reduces misrouting risk when the QQ/TIM UI changes concurrently.

## ADR-021 — Deterministic memory retrieval precedes FTS and semantic acceleration

Decision: Qbot v0.7 freezes memory eligibility and ranking independently from any retrieval index. Normal retrieval reads only `PROMOTED` memories, requires explicit scope/domain identifiers, excludes records outside their validity window, and filters out lexical/entity-irrelevant records when the query supplies relevance signals. The deterministic score uses integer components on a 0-1000 scale: keyword 40%, entity 20%, recency 15%, importance 10%, and trust 15%. Ties are resolved by component scores, then newer creation time, then `memory_id`.

SQLite FTS5 and later semantic/embedding scorers are candidate accelerators or additional pluggable relevance signals only. They may not make CANDIDATE/REJECTED/SUPERSEDED memories eligible, bypass trust/domain boundaries, or change Active Task/Checkpoint force-loading.

Reason: Android and Desktop must be able to reproduce the same memory selection before backend-specific indexing is introduced. Integer scoring and explicit domain filters reduce cross-runtime drift, while separating eligibility from acceleration prevents an FTS/vector index from becoming an accidental authority boundary.

## ADR-022 — Desktop FTS5 is a disposable candidate accelerator

Decision: Desktop v0.7 may maintain a derived SQLite FTS5 `memory_search_fts` virtual table containing NFKC + case-fold normalized Memory content/entities. The index is not part of the authoritative schema version and may be deleted/rebuilt at any time. FTS is used only when all relevance signals are simple normalized ASCII alphanumeric strings of at least three characters, allowing the trigram tokenizer to provide a candidate superset for ADR-021 substring/entity relevance. Short, non-ASCII, structured, empty, unsupported, or FTS-error queries fall back to the deterministic scan path.

The authoritative `memories` table remains the source of truth. After FTS candidate IDs are selected, Qbot reapplies all PROMOTED/state, scope/domain, trust, temporal, relevance, integer scoring, and tie-break rules from ADR-021. The derived index is lazily rebuilt when append-only Memory row count diverges from the index row count. Failure to create/query FTS5 disables acceleration for that retriever instance and must not put the database into Safe Mode.

Reason: FTS should improve candidate discovery cost without creating a new authority boundary or making runtime correctness depend on a particular SQLite build. Keeping it derived and fail-open-to-scan preserves cross-runtime semantics and allows backups/migrations to remain valid even when FTS5/trigram support is absent.

## ADR-023 — Android FTS is a Room-backed disposable 3-gram index

Decision: Android v0.7 mirrors the Desktop FTS accelerator boundary inside the Room-managed SQLite file without adding an authoritative Room Entity or schema migration. `MemoryRetriever` may lazily create a disposable FTS4 virtual table named `memory_search_fts`. Its indexed document is a set of overlapping ASCII 3-grams derived from the same NFKC + Unicode case-fold normalized Memory content/entities used by ADR-021.

Acceleration is attempted only when every normalized relevance signal is ASCII alphanumeric and at least three characters long. Each signal is translated to an AND group of its 3-grams, while multiple signals are ORed to obtain a candidate superset. Short, non-ASCII, structured, empty, unsupported, or FTS-error queries use the deterministic scan path. Candidate IDs are then reloaded from the authoritative `memories` table and all ADR-021 state/domain/trust/temporal/relevance/scoring/tie-break rules are reapplied unchanged.

The virtual table is derived state: it may be deleted or rebuilt, is excluded from Room schema versioning/export, and row-count divergence after append-only Memory growth triggers lazy rebuild. Failure to create or query FTS4 disables acceleration for that retriever instance without changing authoritative state.

Reason: Android's broadly available FTS4 tokenizer does not provide the same native trigram tokenizer as Desktop SQLite FTS5. Explicit normalized 3-gram documents preserve substring candidate semantics while keeping the index non-authoritative, cross-runtime results deterministic, and Room schema v2 unchanged.

## ADR-024 — Semantic memory scoring is advisory and cannot change deterministic retrieval

Decision: v0.7 introduces a provider-neutral asynchronous `SemanticRelevanceScorer` contract only after ADR-021 deterministic eligibility and ordering have completed. The scorer receives only the already-selected deterministic Memory hits and may return an integer `score_milli` (0-1000) plus runtime provider/model provenance. Semantic scores are audit metadata in this milestone: they do not add, remove, reorder, promote, persist, or otherwise mutate Memory, and they do not contribute to the frozen ADR-021 `total_points`.

The semantic path is explicit opt-in through `retrieve_with_semantics()`. With no scorer configured it returns the same deterministic hits marked DISABLED. An intentionally unavailable backend returns the same hits marked UNAVAILABLE. Provider exceptions, duplicate IDs, unknown/ineligible IDs, non-integer scores, and scores outside 0-1000 fail closed to semantic metadata marked FAILED; deterministic IDs, ordering, and scores are preserved. Active Task/Checkpoint restoration remains a separate direct durable-state path and is never supplied to the semantic scorer.

Reason: embedding providers are optional, failure-prone, and may differ across platforms/models. Freezing a non-authoritative scorer contract first provides semantic observability without weakening trust/domain boundaries or making core correctness depend on embeddings. Any future semantic reranking or score fusion requires a separate explicit decision and cross-runtime contract rather than silently changing ADR-021 ranking semantics.
