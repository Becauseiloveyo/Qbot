from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from qbot.domain import NormalizedEvent
from qbot.transport import IncomingTransportEvent


def _rfc3339(value: datetime) -> str:
    resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class EventNormalizer:
    """Convert transport events into the common Qbot event contract."""

    def __init__(self, transport_name: str, platform: str = "qq") -> None:
        self.transport_name = transport_name
        self.platform = platform

    def normalize(self, event: IncomingTransportEvent) -> NormalizedEvent:
        identity = event.platform_message_id or "|".join(
            [
                event.sender_id or "",
                event.message_type,
                event.text or "",
                _rfc3339(event.occurred_at),
            ]
        )
        fingerprint_material = "\x1f".join(
            [
                self.platform,
                event.account_id,
                event.conversation_id,
                identity,
            ]
        )
        fingerprint = hashlib.sha256(
            fingerprint_material.encode("utf-8")
        ).hexdigest()

        return NormalizedEvent(
            event_id=f"evt-{uuid4()}",
            fingerprint=fingerprint,
            platform=self.platform,
            transport=self.transport_name,
            account_id=event.account_id,
            conversation_id=event.conversation_id,
            sender_id=event.sender_id,
            platform_message_id=event.platform_message_id,
            message_type=event.message_type,
            text=event.text,
            occurred_at=_rfc3339(event.occurred_at),
            received_at=_rfc3339(datetime.now(UTC)),
            metadata=event.metadata,
        )
