from __future__ import annotations

from collections.abc import Callable

from .base import LlmProvider, LlmRequest, LlmResponse


class MockLlmProvider(LlmProvider):
    def __init__(
        self,
        *,
        name: str = "mock",
        model: str = "mock-model",
        responder: Callable[[LlmRequest], str] | None = None,
    ) -> None:
        self._name = name
        self.model = model
        self.responder = responder or (lambda _request: "{}")

    @property
    def provider_name(self) -> str:
        return self._name

    async def complete(self, request: LlmRequest) -> LlmResponse:
        return LlmResponse(
            text=self.responder(request),
            model=self.model,
            provider=self.provider_name,
            usage={},
        )
