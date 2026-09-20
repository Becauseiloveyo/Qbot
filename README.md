# Qbot

Qbot is an Android-first personal QQ reply agent.

## v0.1 goals

- Run locally on Android.
- Keep a persistent per-contact conversation state.
- Persist long-running task progress so a short model context window does not break continuity.
- Before every model execution, rebuild context from durable state instead of trusting the previous LLM turn.
- Keep recent raw messages, a rolling summary, durable facts, and explicit task checkpoints separately.
- Default to assisted reply mode; high-risk messages require manual confirmation.

## Context continuity model

Each conversation is reconstructed from:

1. Persona profile
2. Contact profile
3. Active task checkpoint
4. Durable memories/facts
5. Rolling conversation summary
6. Recent raw messages
7. Current incoming message

The active task checkpoint is stored independently from chat history. It contains the task goal, current phase, completed steps, pending steps, blockers, important decisions, and the next expected action.

## Repository workflow for coding agents

Read `AGENTS.md` and `TASK_PROGRESS.md` before making changes. Update `TASK_PROGRESS.md` after every meaningful implementation session.

## Status

Bootstrap in progress. See `TASK_PROGRESS.md`.
