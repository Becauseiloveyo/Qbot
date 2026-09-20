# Qbot State Machines — v0.1

## Task

Allowed transitions:

```text
NEW -> PLANNING
NEW -> CANCELLED

PLANNING -> READY
PLANNING -> WAITING_USER
PLANNING -> FAILED
PLANNING -> CANCELLED

READY -> RUNNING
READY -> CANCELLED

RUNNING -> WAITING_USER
RUNNING -> PAUSED
RUNNING -> FAILED
RUNNING -> COMPLETED
RUNNING -> CANCELLED

WAITING_USER -> RUNNING
WAITING_USER -> CANCELLED

PAUSED -> RUNNING
PAUSED -> CANCELLED

FAILED -> RUNNING
FAILED -> CANCELLED
```

`COMPLETED` and `CANCELLED` are terminal in v0.1.

## Task Step

```text
PENDING -> RUNNING
PENDING -> CANCELLED

RUNNING -> SUCCEEDED
RUNNING -> FAILED
RUNNING -> WAITING_USER
RUNNING -> CANCELLED

WAITING_USER -> RUNNING
WAITING_USER -> CANCELLED

FAILED -> RUNNING
FAILED -> CANCELLED
```

## AgentRun

```text
CREATED -> RESTORING
RESTORING -> REASONING
RESTORING -> FAILED

REASONING -> WAITING_USER
REASONING -> EXECUTING
REASONING -> SUCCEEDED
REASONING -> FAILED

WAITING_USER -> REASONING
WAITING_USER -> CANCELLED

EXECUTING -> REASONING
EXECUTING -> SUCCEEDED
EXECUTING -> FAILED
```

## Outbox

```text
PENDING -> SENDING
PENDING -> CANCELLED

SENDING -> SENT
SENDING -> FAILED
SENDING -> SENDING_UNKNOWN

SENDING_UNKNOWN -> SENT
SENDING_UNKNOWN -> FAILED
SENDING_UNKNOWN -> SENDING

FAILED -> PENDING
FAILED -> CANCELLED
```

## Core invariants

- An active Task may have at most one `RUNNING` step in v0.1.
- A `COMPLETED` Task cannot contain a non-terminal required step.
- A checkpoint references an existing Task version.
- A stale `writer_epoch` cannot commit authoritative state in synchronized mode.
- One inbound event fingerprint is processed at most once locally.
- One outbox `dedupe_key` is unique per account.
- `SENDING_UNKNOWN` must be reconciled before automatic retry when platform history/IDs can establish prior delivery.
- An LLM may never bypass these state transitions.
