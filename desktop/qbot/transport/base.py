from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TransportCapability(StrEnum):
    READ_TEXT = "READ_TEXT"
    SEND_TEXT = "SEND_TEXT"
    SEND_IMAGE = "SEND_IMAGE"
    READ_HISTORY = "READ_HISTORY"
    QUOTE_REPLY = "QUOTE_REPLY"
    GROUP_MESSAGE = "GROUP_MESSAGE"
    SEND_FILE = "SEND_FILE"
    REACTION = "REACTION"
    RECALL = "RECALL"
    DELIVERY_LOOKUP = "DELIVERY_LOOKUP"


class IncomingTransportEvent(BaseModel):
    """Transport-level event before Qbot event normalization."""

    model_config = ConfigDict(frozen=True)

    account_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    sender_id: str | None = None
    platform_message_id: str | None = None
    message_type: str = "private"
    text: str | None = None
    occurred_at: datetime
    metadata: dict[str, object] = Field(default_factory=dict)


class OutgoingMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    dedupe_key: str = Field(min_length=8)
    text: str
    reply_to_message_id: str | None = None


class SendResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool
    platform_message_id: str | None = None
    uncertain: bool = False
    error: str | None = None


class DeliveryLookupResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    found: bool
    platform_message_id: str | None = None


class QQTransport(ABC):
    """Platform adapter boundary.

    Agent Core may depend on this abstraction but never on NapCat-specific
    APIs. Android implements the same logical capability contract separately.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[TransportCapability]:
        raise NotImplementedError

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def receive(self) -> IncomingTransportEvent:
        raise NotImplementedError

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> SendResult:
        raise NotImplementedError

    async def lookup_delivery(
        self,
        account_id: str,
        dedupe_key: str,
    ) -> DeliveryLookupResult:
        return DeliveryLookupResult(found=False)
