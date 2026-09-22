from __future__ import annotations

from .base import LlmProvider, LlmRequest, LlmResponse, ModelRole


class LlmRoutingError(RuntimeError):
    pass


class ModelRouter:
    """Route Agent responsibilities to ordered provider chains.

    Fallback occurs only during the model call. The router never retries or
    repeats external Qbot side effects such as Outbox sends.
    """

    def __init__(self) -> None:
        self._providers: dict[ModelRole, list[LlmProvider]] = {}

    def register(self, role: ModelRole, provider: LlmProvider) -> None:
        self._providers[role] = [provider]

    def add_fallback(self, role: ModelRole, provider: LlmProvider) -> None:
        self._providers.setdefault(role, []).append(provider)

    def has_role(self, role: ModelRole) -> bool:
        return bool(self._providers.get(role))

    def providers_for(self, role: ModelRole) -> tuple[LlmProvider, ...]:
        providers = self._providers.get(role)
        if not providers:
            raise KeyError(f"no LLM provider registered for role={role}")
        return tuple(providers)

    def provider_for(self, role: ModelRole) -> LlmProvider:
        return self.providers_for(role)[0]

    async def complete(self, request: LlmRequest) -> LlmResponse:
        errors: list[str] = []
        for provider in self.providers_for(request.role):
            try:
                return await provider.complete(request)
            except Exception as exc:
                errors.append(
                    f"{provider.provider_name}: {type(exc).__name__}: {exc}"
                )

        raise LlmRoutingError(
            f"all providers failed for role={request.role}: "
            + " | ".join(errors)
        )
