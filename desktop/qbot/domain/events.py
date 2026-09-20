from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NormalizedEvent(BaseModel):
    """Desktop representation of spec/event.schema.json for message admission."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["0.1.0"] = "0.1.0"
    event_id: str = Field(min_length=1)
    fingerprint: str = Field(min_length=16)
    platform: Literal["qq", "mock"] = "qq"
    transport: str
    account_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    sender_id: str | None = None
    platform_message_id: str | None = None
    event_type: Literal["MESSAGE_RECEIVED"] = "MESSAGE_RECEIVED"
    message_type: str | None = "private"
    text: str | None = None
    content_ref: str | None = None
    reply_to_message_id: str | None = None
    occurred_at: str
    received_at: str
    raw_ref: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
