from __future__ import annotations

from .base import LlmProvider, LlmRequest, LlmResponse, ModelRole


class ModelRouter:
    """Route different Agent responsibilities to independently replaceable models."""

    def __init__(self) -> None:
        self._providers: dict[ModelRole, LlmProvider] = {}

    def register(self, role: ModelRole, provider: LlmProvider) -> None:
        self._providers[role] = provider

    def provider_for(self, role: ModelRole) -> LlmProvider:
        try:
            return self._providers[role]
        except KeyError as exc:
            raise KeyError(f"no LLM provider registered for role={role}") from exc

    async def complete(self, request: LlmRequest) -> LlmResponse:
        return await self.provider_for(request.role).complete(request)
