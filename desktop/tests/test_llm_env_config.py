from __future__ import annotations

import unittest

from qbot.llm import ModelRole
from qbot.llm.env_config import (
    LlmEnvironmentError,
    build_router_from_environment,
)


class LlmEnvironmentConfigTests(unittest.TestCase):
    def test_role_specific_values_override_generic_values(self) -> None:
        router = build_router_from_environment(
            {
                "QBOT_LLM_BASE_URL": "https://generic.example/v1",
                "QBOT_LLM_MODEL": "generic-model",
                "QBOT_LLM_API_KEY": "generic-secret",
                "QBOT_LLM_DECISION_MODEL": "decision-model",
                "QBOT_LLM_DECISION_SUPPORTS_JSON_OBJECT": "true",
            }
        )

        decision = router.provider_for(ModelRole.DECISION)
        chat = router.provider_for(ModelRole.CHAT)

        self.assertEqual(decision.config.model, "decision-model")
        self.assertEqual(chat.config.model, "generic-model")
        self.assertTrue(decision.config.supports_json_object)
        self.assertNotIn("generic-secret", repr(decision.config))

    def test_incomplete_role_configuration_is_rejected(self) -> None:
        with self.assertRaises(LlmEnvironmentError):
            build_router_from_environment(
                {
                    "QBOT_LLM_DECISION_BASE_URL": "https://example/v1",
                    "QBOT_LLM_DECISION_MODEL": "model-only",
                }
            )

    def test_empty_environment_registers_no_roles(self) -> None:
        router = build_router_from_environment({})
        with self.assertRaises(KeyError):
            router.provider_for(ModelRole.DECISION)


if __name__ == "__main__":
    unittest.main()
