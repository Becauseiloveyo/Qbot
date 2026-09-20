# Android Enhanced Transports (v0.6)

Status: design baseline for feature/android-v0.6-enhanced-transports.

## Principle

Enhanced Android access does not bypass Qbot's durable execution rules.

All external messages still follow:

ActionProposal -> Policy -> durable Outbox -> one selected transport -> result recording

A fallback adapter is selected before an Outbox effect enters SENDING. Once an external send attempt begins, another adapter must not automatically replay the same Outbox effect. Ambiguous outcomes remain SENDING_UNKNOWN.

## AccessibilityService

Accessibility is an optional enhanced QQ UI adapter.

It may advertise a capability only while that capability is directly recognized in the current QQ/TIM UI. SEND_TEXT requires a supported active package plus a writable composer and an unambiguous send action. READ_TEXT is limited to UI content actually exposed through accessibility nodes/events. DELIVERY_LOOKUP is not advertised unless a future implementation can prove delivery from a stable platform identifier.

The service remains PERMISSION_REQUIRED/disabled until the user explicitly enables it. A connected service with an unknown QQ layout is DEGRADED or unavailable for the affected capability, not implicitly READY.

Package/UI selectors are version-sensitive and unknown layouts fail closed.

## Shizuku

Shizuku is an optional system capability provider, not a QQ transport.

Its adb/root-backed service can expose privileged Android system APIs, but that does not itself prove access to QQ conversation identity, private message history, or send semantics.

Therefore Qbot can run without Shizuku; Shizuku state/permission is health information for adapters that consume it; system capabilities are reported separately from QQTransport capabilities; and no READ_TEXT, SEND_TEXT, READ_HISTORY, or DELIVERY_LOOKUP is inferred merely because Shizuku is READY.

## Selection and fallback

For an Outbox text send:

1. take fresh adapter health/capability snapshots;
2. ignore adapters without SEND_TEXT;
3. prefer READY over DEGRADED;
4. use deterministic configured priority within the same health class;
5. call checkSendReadiness() before committing to a transport;
6. select exactly one ready adapter;
7. transition the Outbox effect to SENDING;
8. invoke only the selected adapter;
9. record SENT, FAILED, or SENDING_UNKNOWN;
10. never try a second adapter after an attempted external effect.

Recommended initial text-send priority:

1. Standard Notification RemoteInput when a live reply action exists;
2. Accessibility adapter when the current QQ UI is positively recognized;
3. experimental/root/hook adapters only when explicitly enabled.

## Health

Common adapter health states are READY, DEGRADED, PERMISSION_REQUIRED, STOPPED, and UNAVAILABLE. Health is diagnostic and never overrides Outbox state or policy.

## Experimental/root/hook boundary

LSPosed/root/hook integration remains a separate experimental adapter and is never a prerequisite for Standard or Accessibility operation.