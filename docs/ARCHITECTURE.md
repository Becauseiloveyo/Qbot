# Qbot Architecture v1.2 FINAL

Status: **Architecture Frozen**

Qbot is a persistent personal messaging agent with two deployment runtimes:

- **Qbot Android**: runs on the phone and interacts with Android QQ through replaceable transports.
- **Qbot Desktop**: runs on PC/server and interacts with QQ through NapCat/OneBot or another compatible transport.

Both runtimes implement the same logical contracts from `spec/`, but they do not force code-level runtime sharing.

## Core processing pipeline

```text
Incoming QQ Event
  -> Transport
  -> Event Normalizer
  -> Event Journal
  -> Deduplicator
  -> Per-Conversation Ordering Lock
  -> Writer/Fencing Check (sync mode)
  -> Create AgentRun
  -> Restore Durable State
  -> Context Builder + Token Budget
  -> Decision / Planning
  -> ActionProposal
  -> Schema Validation
  -> State-Machine Validation
  -> Action Policy
  -> Executor
  -> Task/Memory Mutation and/or Outbox
  -> Checkpoint Commit
  -> Transport Send / Reconciliation
  -> Event Journal
  -> Async Summary/Memory Workers
```

## Non-negotiable invariant

The model context is never the authoritative state store.

Before every meaningful reasoning turn, Qbot reconstructs state from durable storage using:

```text
System policy
Persona core
Contact core
Active task
Current checkpoint
Important decisions / constraints
Trusted relevant memories
Rolling summary
Recent raw messages
Current incoming message
```

If context must be reduced, recent low-value raw history and low-relevance memory are removed before task/checkpoint/constraints.

## Android runtime

Recommended technologies:

```text
Kotlin
Jetpack Compose
Room SQLite
Coroutines / Flow
WorkManager
NotificationListenerService
OkHttp
DataStore
Android Keystore
```

Android QQ integration is capability-based:

```text
QQTransport
  - Standard adapter: notifications / platform-supported reply surfaces
  - Enhanced adapter: Accessibility / Shizuku
  - Expert adapter: optional root/LSPosed/hook implementation
```

The Android process is considered recoverable, not immortal. Any critical step must survive process death through durable checkpoints.

## Desktop runtime

Recommended technologies:

```text
Python 3.12+
FastAPI
Pydantic
SQLAlchemy
SQLite WAL
httpx
websockets
NapCat + OneBot 11
```

Desktop is the preferred always-on primary node.

NapCat APIs must remain behind a `QQTransport` adapter so the core can later support other OneBot-compatible transports.

## Durable execution

A task is not a prompt. It is structured state.

```text
Task
  goal
  constraints
  phase
  status
  steps[]
  decisions[]
  blockers[]
  next_action
```

Agent execution is split into durable runs and durable steps. Each successful side-effect boundary is committed before later work proceeds.

Typical step states:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
WAITING_USER
CANCELLED
```

Task states:

```text
NEW
PLANNING
READY
RUNNING
WAITING_USER
PAUSED
FAILED
CANCELLED
COMPLETED
```

## LLM authority boundary

LLM output is treated as a proposal, never a direct mutation.

```text
LLM -> ActionProposal -> validators -> policy -> executor
```

Examples of authoritative operations that only Qbot executors can perform:

- transition task state;
- complete a task step;
- promote candidate memory;
- write trusted persona changes;
- enqueue a QQ message;
- write files or invoke external tools;
- approve high-impact actions.

## Outbox and send uncertainty

Outgoing messages use a durable outbox.

```text
PENDING -> SENDING -> SENT
                  -> SENDING_UNKNOWN
                  -> FAILED
```

If the process loses certainty after an external send, Qbot reconciles with platform history/identifiers when possible. It does not blindly replay.

The engineering goal is effectively-once behavior, not a false claim of mathematically guaranteed exactly-once delivery.

## Idempotency and ordering

Incoming events have a stable fingerprint and are unique per platform/account/conversation/message identity.

Outgoing effects have a dedupe key.

Processing rules:

- same conversation: sequential;
- different conversations: may run concurrently;
- stale writer epochs cannot commit authoritative writes;
- state mutations use version checks where applicable.

## Memory model

Memory is not a single vector store.

```text
Candidate Memory
 -> validation/trust policy
 -> promoted memory

M0 Current message
M1 Recent raw messages
M2 Rolling summary
M3 Episodic memory
M4 Persona/contact memory
M5 Active task/checkpoint
```

Retrieval may combine:

```text
semantic relevance
keyword / FTS
entities
time/recency
importance
trust/provenance
```

Active tasks and checkpoints are always loaded directly and never depend on RAG.

Trusted scopes include:

- SYSTEM_POLICY
- USER_PERSONA
- CONTACT_PROFILE
- CONVERSATION_MEMORY
- TASK_MEMORY

External contact messages are untrusted input and cannot directly mutate system policy or trusted user persona.

## Action policy

Suggested risk classes:

```text
R0 low-risk automation
R1 automatic + audit
R2 human approval required
R3 automatic execution forbidden
```

Examples that generally require elevated treatment include money, credentials, verification codes, sensitive personal information, consequential account actions, major commitments, and significant real-world scheduling.

## Multi-node phone/PC mode

Standalone mode requires no coordinator.

Synchronized/high-availability mode uses:

```text
single authoritative writer
+ lease
+ monotonically increasing fencing epoch
+ optimistic concurrency/version checks
```

Without a trusted coordinator, automatic failover is not allowed. Manual active-node selection is safer than potential split-brain replies.

## Event journal

Important transitions append an event journal entry, such as:

```text
MESSAGE_RECEIVED
RUN_CREATED
TASK_RESTORED
STEP_STARTED
LLM_CALLED
ACTION_PROPOSED
ACTION_REJECTED
OUTBOX_CREATED
MESSAGE_SENT
CHECKPOINT_COMMITTED
MEMORY_PROMOTED
TASK_COMPLETED
```

The journal supports audit, debugging, crash reconstruction, and future replay tooling.

## Persistence and migration

- Every persistent schema has a version.
- Upgrades perform backup -> migration -> integrity check -> start.
- Failed migrations enter Safe Mode and preserve data for rollback/recovery.
- Large binary/huge textual artifacts live in a BlobStore; main relational rows hold references and hashes.
- Secrets use Android Keystore or OS credential/keyring facilities rather than ordinary plaintext config.

## Safe Mode

Safe Mode disables automatic sending and task execution while still allowing:

- data inspection;
- backup/export;
- integrity checks;
- recovery;
- migration repair;
- problematic task/outbox cleanup.

## Deferred complexity

Not part of the initial architecture unless later justified:

- Kubernetes;
- Redis for single-user first release;
- mandatory PostgreSQL;
- dedicated vector database;
- LangGraph runtime dependency;
- distributed multi-agent orchestration;
- forced shared cross-platform native core.

The macro architecture is considered frozen. Future work should evolve module internals without replacing these boundaries.
