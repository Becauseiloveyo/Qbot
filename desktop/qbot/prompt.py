from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PromptMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str = Field(pattern="^(system|user|assistant)$")
    content: str
