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


if __name__ == "__main__":
    unittest.main()
