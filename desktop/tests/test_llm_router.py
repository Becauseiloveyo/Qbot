from __future__ import annotations

import unittest

from qbot.llm import (
    LlmMessage,
    LlmRequest,
    MockLlmProvider,
    ModelRole,
    ModelRouter,
)


class ModelRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_roles_route_to_independent_providers(self) -> None:
        router = ModelRouter()
        router.register(
            ModelRole.DECISION,
            MockLlmProvider(name="decision-provider", model="fast"),
        )
        router.register(
            ModelRole.CHAT,
            MockLlmProvider(name="chat-provider", model="large"),
        )

        request = LlmRequest(
            role=ModelRole.CHAT,
            messages=(LlmMessage(role="user", content="hello"),),
        )
        response = await router.complete(request)
        self.assertEqual(response.provider, "chat-provider")
        self.assertEqual(response.model, "large")

    async def test_fallback_occurs_only_inside_model_call(self) -> None:
        calls: list[str] = []

        def fail(_request):
            calls.append("primary")
            raise RuntimeError("provider unavailable")

        def succeed(_request):
            calls.append("fallback")
            return "ok"

        router = ModelRouter()
        router.register(
            ModelRole.DECISION,
            MockLlmProvider(name="primary", responder=fail),
        )
        router.add_fallback(
            ModelRole.DECISION,
            MockLlmProvider(name="fallback", responder=succeed),
        )

        response = await router.complete(
            LlmRequest(
                role=ModelRole.DECISION,
                messages=(LlmMessage(role="user", content="hello"),),
            )
        )
        self.assertEqual(calls, ["primary", "fallback"])
        self.assertEqual(response.provider, "fallback")


if __name__ == "__main__":
    unittest.main()
