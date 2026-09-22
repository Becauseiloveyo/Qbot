# Qbot v0.1 Persistence Mapping

Status: authoritative for v0.1 persistence semantics.

This document maps the common Qbot contracts to equivalent durable storage semantics on:

- Android: Room over SQLite;
- Desktop: SQLAlchemy over SQLite WAL.

The concrete ORM class names may differ, but keys, uniqueness rules, version checks, transaction boundaries, and recovery behavior must remain equivalent.

## Global rules

- Database schema version is independent from individual JSON contract version.
- Persistent timestamps are stored as RFC 3339 UTC text or an equivalent lossless UTC representation.
- Boolean values may be stored as SQLite INTEGER 0/1.
- Structured arrays/maps may be normalized into child tables or encoded as canonical JSON text. The logical constraints below still apply.
- Authoritative mutations occur inside explicit database transactions.
- Large payloads and binary content are stored in BlobStore and referenced by ID/hash.
- Destructive migration without backup is forbidden.
- Android and Desktop must pass the same conformance fixtures.

## Recommended database metadata

Table: `qbot_meta`

| Column | Semantics |
| --- | --- |
| `key` | primary key |
| `value` | text value |

Required keys:

- `db_schema_version`
- `qbot_spec_version`
- `node_id`
- `last_integrity_check_at`

## inbound_events

Source contract: `spec/event.schema.json`

Required columns:

| Column | Constraint |
| --- | --- |
| `event_id` | PRIMARY KEY |
| `fingerprint` | UNIQUE NOT NULL |
| `schema_version` | NOT NULL |
| `platform` | NOT NULL |
| `transport` | nullable |
| `account_id` | NOT NULL |
| `conversation_id` | NOT NULL |
| `sender_id` | nullable |
| `platform_message_id` | nullable |
| `event_type` | NOT NULL |
| `message_type` | nullable |
| `text` | nullable |
| `content_ref` | nullable |
| `reply_to_message_id` | nullable |
| `occurred_at` | NOT NULL |
| `received_at` | NOT NULL |
| `raw_ref` | nullable |
| `metadata_json` | NOT NULL default `{}` |

Invariant:

`UNIQUE(fingerprint)` is the local inbound idempotency barrier. Duplicate delivery must return the already-known event rather than create a second AgentRun.

Recommended index:

`(account_id, conversation_id, occurred_at)`

## event_journal

Source contract: `spec/journal-event.schema.json`

Required columns:

- `journal_id` PRIMARY KEY
- `schema_version`
- `event_type`
- `actor`
- `account_id`
- `conversation_id`
- `task_id`
- `run_id`
- `related_id`
- `payload_json`
- `occurred_at`

The journal is append-only in normal operation. Runtime code must not rewrite prior journal history to make a failed action appear successful.

For routed external effects, `SEND_STARTED` records the selected stable `transport_id` with `related_id = outbox_id`. This event is the durable source of truth for which adapter owned an external attempt if the process dies before the result is committed.

Recommended indexes:

- `(conversation_id, occurred_at)`
- `(task_id, occurred_at)`
- `(run_id, occurred_at)`

## tasks

Source contract: `spec/task.schema.json`

Required columns:

- `task_id` PRIMARY KEY
- `schema_version`
- `conversation_id`
- `parent_task_id`
- `goal`
- `status`
- `phase`
- `constraints_json`
- `decisions_json`
- `blockers_json`
- `next_action`
- `writer_epoch`
- `version`
- `created_at`
- `updated_at`

Task steps are stored separately.

Authoritative update predicate in synchronized mode:

```sql
UPDATE tasks
SET ..., version = version + 1
WHERE task_id = :task_id
  AND version = :expected_version
  AND writer_epoch = :expected_writer_epoch;
```

An affected-row count of zero is a concurrency/fencing failure and must not be silently retried with overwritten state.

## task_steps

Logical child records of a Task.

Columns:

- `step_id` PRIMARY KEY
- `task_id` NOT NULL
- `sequence` NOT NULL
- `description` NOT NULL
- `status` NOT NULL
- `result`
- `error`
- `started_at`
- `completed_at`

Constraints:

- `UNIQUE(task_id, sequence)`
- foreign key `task_id -> tasks.task_id`
- at most one `RUNNING` step per task is enforced transactionally by runtime validation in v0.1.

## task_checkpoints

Source contract: `spec/checkpoint.schema.json`

Columns:

- `checkpoint_id` PRIMARY KEY
- `schema_version`
- `task_id` NOT NULL
- `agent_run_id`
- `task_version` NOT NULL
- `summary`
- `completed_step_ids_json`
- `pending_step_ids_json`
- `current_step_id`
- `decisions_json`
- `blockers_json`
- `next_action`
- `context_digest`
- `writer_epoch`
- `created_at`

Recommended index:

`(task_id, created_at DESC)`

Recovery loads the newest checkpoint whose `task_version` matches the restored Task version or whose compatibility has been explicitly validated.

## agent_runs

Source contract: `spec/agent-run.schema.json`

Columns:

- `run_id` PRIMARY KEY
- `schema_version`
- `conversation_id`
- `trigger_event_id`
- `task_id`
- `status`
- `model_profile`
- `writer_epoch`
- `created_at`
- `updated_at`

Constraints:

- `trigger_event_id` references an inbound event.
- One duplicate inbound fingerprint must not create a second logical run.
- Implementations should enforce `UNIQUE(trigger_event_id)` for the primary reaction run in v0.1.

## agent_run_steps

Child records of AgentRun.

Columns:

- `run_step_id` PRIMARY KEY
- `run_id` NOT NULL
- `kind` NOT NULL
- `status` NOT NULL
- `attempt` NOT NULL
- `input_ref`
- `output_ref`
- `error`

Recommended index:

`(run_id)`

## outbox_messages

Source contract: `spec/outbox.schema.json`

Columns:

- `outbox_id` PRIMARY KEY
- `schema_version`
- `run_id`
- `account_id`
- `conversation_id`
- `dedupe_key`
- `status`
- `payload_kind`
- `payload_text`
- `content_ref`
- `reply_to_message_id`
- `platform_message_id`
- `transport_attempts`
- `last_error`
- `writer_epoch`
- `created_at`
- `sent_at`

Critical constraint:

`UNIQUE(account_id, dedupe_key)`

The transaction that creates an authoritative reply effect must insert the Outbox row before the network send occurs.

Recovery rules:

- `PENDING`: eligible to send after policy/writer checks; adapter fallback is allowed only while the effect remains PENDING.
- `SENDING`: after crash, convert to `SENDING_UNKNOWN` unless transport semantics prove no external write occurred.
- `SENDING_UNKNOWN`: reconcile only through the adapter recorded by the latest `SEND_STARTED.transport_id`; another adapter must not perform lookup or replay the effect.
- `SENT`: never automatically resend.

## memories

Source contract: `spec/memory.schema.json`

Columns:

- `memory_id` PRIMARY KEY
- `schema_version`
- `state`
- `scope`
- `owner_id`
- `conversation_id`
- `task_id`
- `content`
- `entities_json`
- `importance`
- `trust`
- `confidence`
- `source_type`
- `source_message_id`
- `source_event_id`
- `valid_from`
- `valid_to`
- `supersedes`
- `created_at`

Memory promotion is an authoritative Qbot operation. Contact-originated content begins as `CANDIDATE` and cannot directly become `SYSTEM_POLICY`.

Recommended indexes:

- `(conversation_id, state, created_at)`
- `(task_id, state, created_at)`
- `(scope, owner_id, state)`

Desktop may add SQLite FTS5 tables later without changing the logical memory contract. Android may use Room FTS once the retrieval milestone begins.


## conversation_summaries

Rolling summaries are derived optional context, not authoritative memory.

Columns:

- `conversation_id` PRIMARY KEY
- `schema_version`
- `summary`
- `source_digest`
- `source_event_count`
- `source_from_at`
- `source_to_at`
- `provider`
- `model`
- `updated_at`

The source digest is computed from the bounded durable message window and is the idempotency barrier for regeneration. A rolling summary may be replaced when the window changes, but it cannot mutate or supersede System Policy, Persona, Active Task, Checkpoint, or promoted Memory. Model failure leaves the previous summary unchanged.

## policy_decisions

Source contract: `spec/policy-decision.schema.json`

Columns:

- `decision_id` PRIMARY KEY
- `schema_version`
- `proposal_id`
- `risk_class`
- `outcome`
- `reasons_json`
- `required_capabilities_json`
- `created_at`

Policy decisions are audit records and should not be retroactively mutated except through explicit migration/repair tooling.

## blob_store

Not a shared JSON contract in v0.1, but implementations must preserve these semantics:

- immutable blob ID;
- SHA-256;
- MIME type;
- byte size;
- storage path/key;
- created timestamp.

Main relational records hold `content_ref`/blob ID rather than oversized content.

## Transaction boundaries

### Inbound event admission

Single transaction:

1. insert `inbound_events` by unique fingerprint;
2. append `MESSAGE_RECEIVED` journal event;
3. if this is a new event, create the primary `agent_runs` row.

If the fingerprint already exists, no second primary AgentRun is created.

### Task step commit

Single transaction:

1. validate current task version/epoch;
2. mutate Task/TaskStep;
3. increment Task `version`;
4. insert new checkpoint;
5. append `CHECKPOINT_COMMITTED` journal entry.

### Reply creation

Single transaction:

1. validate ActionProposal and PolicyDecision;
2. validate writer epoch;
3. insert Outbox row using unique `(account_id, dedupe_key)`;
4. append `OUTBOX_CREATED` journal entry.

Network transmission happens after commit.

### Send attempt start

Before invoking one selected external adapter, a single transaction:

1. validates the Outbox effect is still `PENDING`;
2. transitions it to `SENDING`;
3. increments `transport_attempts`;
4. appends `SEND_STARTED` with the selected stable `transport_id` and `related_id = outbox_id`.

The external adapter call occurs only after this transaction commits. Once this boundary is crossed, automatic fallback to a different adapter is forbidden. If the result is ambiguous, the effect becomes `SENDING_UNKNOWN` and recovery uses only the recorded original adapter.

## Android Room mapping

- Entity primary keys mirror logical primary keys above.
- `@Index(unique = true)` is required for event fingerprint and `(account_id, dedupe_key)`.
- DAO methods that implement the transaction boundaries above use `@Transaction`.
- Task optimistic concurrency uses an UPDATE query constrained by `task_id + version + writer_epoch` and checks affected row count.
- Room migrations are explicit; destructive fallback is forbidden for production data.

## Desktop SQLite mapping

- SQLAlchemy models mirror the same uniqueness and foreign-key semantics.
- SQLite runs with WAL mode enabled.
- Each authoritative boundary uses `Session.begin()` or equivalent explicit transaction.
- Foreign keys are enabled per connection.
- Alembic or an equivalent explicit migration system is introduced before the first persistent public release.
- SQLite busy/retry handling must not bypass version/fencing failures.

## Cross-runtime equivalence tests

Both runtimes must eventually prove:

1. duplicate inbound fingerprint -> one logical event / one primary run;
2. same `(account_id, dedupe_key)` -> one Outbox effect;
3. stale `writer_epoch` -> authoritative mutation rejected;
4. stale Task `version` -> authoritative mutation rejected;
5. task checkpoint survives process/runtime restart;
6. `SENDING_UNKNOWN` does not blindly resend when reconciliation is available;
7. contact-originated memory cannot mutate System Policy directly;
8. a routed send persists the selected adapter before the external call, and `SENDING_UNKNOWN` cannot reconcile through a different adapter.
