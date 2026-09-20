from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .base import LlmProvider, LlmRequest, LlmResponse


class OpenAICompatibleConfig(BaseModel):
    """Runtime-only HTTP provider configuration."""

    model_config = ConfigDict(frozen=True)

    base_url: str = Field(min_length=1)
    api_key: SecretStr
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(default=30.0, gt=0)
    supports_json_object: bool = False


class OpenAICompatibleProvider(LlmProvider):
    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        client: httpx.AsyncClient | None = None,
        provider_name: str = "openai-compatible",
    ) -> None:
        self.config = config
        self._client = client
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    async def complete(self, request: LlmRequest) -> LlmResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if (
            request.response_format == "json_object"
            and self.config.supports_json_object
        ):
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": "Bearer " + self.config.api_key.get_secret_value(),
            "Content-Type": "application/json",
        }
        url = self.config.base_url.rstrip("/") + "/chat/completions"

        if self._client is not None:
            response = await self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                )

        response.raise_for_status()
        body = response.json()

        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("invalid OpenAI-compatible response shape") from exc
        if not isinstance(text, str):
            raise ValueError("OpenAI-compatible response content must be text")

        raw_usage = body.get("usage") or {}
        usage: dict[str, int] = {}
        if isinstance(raw_usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = raw_usage.get(key)
                if isinstance(value, int):
                    usage[key] = value

        model = body.get("model")
        return LlmResponse(
            text=text,
            model=str(model) if model is not None else self.config.model,
            provider=self.provider_name,
            usage=usage,
        )
