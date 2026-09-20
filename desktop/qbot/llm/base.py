from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from qbot.prompt import PromptMessage


class ModelRole(StrEnum):
    DECISION = "decision"
    CHAT = "chat"
    SUMMARY = "summary"
    MEMORY = "memory"


LlmMessage = PromptMessage


class LlmRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: ModelRole
    messages: tuple[LlmMessage, ...]
    response_format: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LlmResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)


class LlmProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise NotImplementedError
