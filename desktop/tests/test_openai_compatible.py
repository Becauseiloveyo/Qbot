from __future__ import annotations

import json
import unittest

import httpx
from pydantic import SecretStr

from qbot.llm import LlmMessage, LlmRequest, ModelRole
from qbot.llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)


class OpenAICompatibleProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completions_mapping(self) -> None:
        seen: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["authorization"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "provider-model",
                    "choices": [
                        {"message": {"content": "{\"ok\":true}"}}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            config = OpenAICompatibleConfig(
                base_url="https://example.invalid/v1",
                api_key=SecretStr("super-secret"),
                model="configured-model",
                supports_json_object=True,
            )
            provider = OpenAICompatibleProvider(
                config,
                client=client,
                provider_name="test-provider",
            )
            response = await provider.complete(
                LlmRequest(
                    role=ModelRole.DECISION,
                    messages=(LlmMessage(role="user", content="hello"),),
                    response_format="json_object",
                )
            )

            self.assertEqual(
                seen["url"],
                "https://example.invalid/v1/chat/completions",
            )
            self.assertEqual(seen["authorization"], "Bearer super-secret")
            self.assertEqual(
                seen["body"]["response_format"],
                {"type": "json_object"},
            )
            self.assertEqual(response.provider, "test-provider")
            self.assertEqual(response.model, "provider-model")
            self.assertEqual(response.usage["total_tokens"], 15)
            self.assertNotIn("super-secret", repr(config))
        finally:
            await client.aclose()


if __name__ == "__main__":
    unittest.main()
