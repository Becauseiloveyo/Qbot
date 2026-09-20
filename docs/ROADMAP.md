# Qbot Project Roadmap

Architecture baseline: **Qbot Architecture v1.2 FINAL**

## v0.1 — Common Spec + Durable Core Model

Goal: freeze interoperable contracts before platform code diverges.

Deliverables:

- event schema;
- task and task-step schema;
- checkpoint schema;
- agent-run schema;
- action-proposal schema;
- memory/candidate-memory schema;
- outbox schema;
- policy-decision schema;
- state-machine documentation;
- conformance fixtures;
- schema versioning rules.

Exit condition: Android and Desktop teams could independently implement the same flow from the spec alone.

## v0.2 — Desktop Transport + Runtime Skeleton

Goal: first end-to-end usable runtime.

Deliverables:

- Python application skeleton;
- SQLite WAL persistence;
- NapCat/OneBot transport;
- inbound normalization and dedupe;
- per-conversation lock;
- AgentRun creation/restoration;
- mock LLM adapter;
- outbox with send result recording;
- CLI/logging diagnostics.

## v0.3 — LLM + Persona + Context

Deliverables:

- OpenAI-compatible provider interface;
- model router;
- context builder;
- token-budget manager;
- persona/contact profile;
- recent-history + rolling-summary support;
- structured decision/action proposal outputs.

## v0.4 — Durable Recovery + Policy

Deliverables:

- full step checkpoints;
- crash recovery;
- `SENDING_UNKNOWN` reconciliation;
- action policy R0-R3;
- human-approval state;
- event journal inspection;
- backup/migration/Safe Mode.

## v0.5 — Android Standard Runtime

Deliverables:

- Kotlin/Compose project;
- Room persistence;
- shared-spec model mapping;
- NotificationListener-based event adapter where supported;
- basic reply transport where supported;
- durable recovery after process death;
- local configuration UI.

## v0.6 — Android Enhanced Transports

Deliverables:

- Accessibility/Shizuku adapter;
- optional expert/root/hook adapter boundary;
- transport capability negotiation;
- adapter health/fallback reporting.

## v0.7 — Hybrid Memory

Deliverables:

- candidate memory staging;
- provenance/trust scoring;
- append/supersede history;
- FTS keyword retrieval;
- semantic retrieval;
- temporal/entity scoring;
- background summarization and memory extraction.

## v0.8 — PC/Phone Sync + Coordinator

Deliverables:

- coordinator protocol;
- lease;
- fencing epoch;
- optimistic concurrency;
- single-writer enforcement;
- task/memory/checkpoint sync;
- manual failover before automatic failover.

## v0.9 — Management UX + Operations

Deliverables:

- Desktop management UI;
- Android management UI;
- task timeline;
- memory browser;
- persona editor;
- prompt/context inspector;
- AgentRun replay/debug view;
- backup/export/restore;
- metrics and usage statistics.

## v1.0 — Release Hardening

Deliverables:

- crash injection tests;
- duplicate event tests;
- network partition tests;
- split-brain tests;
- migration tests;
- DB corruption/Safe Mode tests;
- long-context degradation tests;
- security boundary tests;
- Android lifecycle tests;
- release packaging and documentation.

## Post-v1 candidates

Potential later work, only if justified by observed needs:

- PostgreSQL for multi-user/server deployments;
- Redis-backed workers;
- Rust shared core;
- richer retrieval/index backends;
- plugin/tool ecosystem;
- optional self-hosted coordinator.
