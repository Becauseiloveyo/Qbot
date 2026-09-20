# Qbot Desktop + NapCat

Qbot Desktop uses NapCat's **OneBot v11 forward WebSocket server** as its first real QQ transport.

## NapCat side

In NapCat WebUI create a **WebSocket server / 正向 WS** entry.

Recommended local-only development settings:

- host: `127.0.0.1`
- port: `3001`
- token: set a strong token if the port is reachable by anything except the local machine
- reportSelfMessage: false

Qbot connects to:

```text
ws://127.0.0.1:3001/
```

The root OneBot v11 WebSocket endpoint carries both events and API calls. Qbot correlates API responses through the OneBot `echo` field.

## Authentication

When a token is configured, Qbot supplies:

```text
Authorization: Bearer <token>
```

The token is runtime-only and must not be committed to the repository or written into ordinary plaintext Qbot configuration.

## Conversation IDs

Qbot normalizes OneBot conversations as:

```text
private:<qq-number>
group:<group-id>
```

This allows the generic Outbox and Agent Core to remain independent of NapCat-specific API structures.

## Safety

Qbot sends generated text with OneBot `auto_escape=true`.

This means model output is treated as literal text rather than CQ-code commands. Rich media / mentions / replies will be implemented later through explicit typed actions rather than allowing arbitrary model text to become protocol commands.

## Delivery uncertainty

A OneBot API response returns `message_id` on successful send. If Qbot loses the WebSocket response after attempting the send, it records the effect as `SENDING_UNKNOWN`.

The initial OneBot adapter intentionally does **not** advertise `DELIVERY_LOOKUP`, because Qbot does not yet have a reliable dedupe-key-to-platform-message lookup protocol. Therefore ambiguous sends are not blindly replayed.
