from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import SecretStr

from .base import ModelRole
from .openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)
from .router import ModelRouter


class LlmEnvironmentError(ValueError):
    pass


_ROLE_ENV = {
    ModelRole.DECISION: "DECISION",
    ModelRole.CHAT: "CHAT",
    ModelRole.SUMMARY: "SUMMARY",
    ModelRole.MEMORY: "MEMORY",
}


def _read(
    env: Mapping[str, str],
    *,
    role_prefix: str,
    suffix: str,
) -> str | None:
    role_value = env.get(f"QBOT_LLM_{role_prefix}_{suffix}")
    if role_value:
        return role_value
    generic = env.get(f"QBOT_LLM_{suffix}")
    return generic if generic else None


def build_router_from_environment(
    env: Mapping[str, str] | None = None,
) -> ModelRouter:
    """Build role routes without persisting credentials.

    Role-specific values override generic QBOT_LLM_* values.
    A role is registered only when BASE_URL, MODEL and API_KEY are complete.
    """

    values = env if env is not None else os.environ
    router = ModelRouter()

    for role, prefix in _ROLE_ENV.items():
        base_url = _read(values, role_prefix=prefix, suffix="BASE_URL")
        model = _read(values, role_prefix=prefix, suffix="MODEL")
        api_key = _read(values, role_prefix=prefix, suffix="API_KEY")

        provided = [base_url is not None, model is not None, api_key is not None]
        if not any(provided):
            continue
        if not all(provided):
            raise LlmEnvironmentError(
                f"incomplete LLM environment for role={role}: "
                "BASE_URL, MODEL and API_KEY must be provided together"
            )

        json_flag = _read(
            values,
            role_prefix=prefix,
            suffix="SUPPORTS_JSON_OBJECT",
        )
        supports_json = str(json_flag or "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        router.register(
            role,
            OpenAICompatibleProvider(
                OpenAICompatibleConfig(
                    base_url=base_url,
                    model=model,
                    api_key=SecretStr(api_key),
                    supports_json_object=supports_json,
                ),
                provider_name=f"env:{role}",
            ),
        )

    return router
