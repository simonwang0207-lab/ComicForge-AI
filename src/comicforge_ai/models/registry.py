"""Registration and environment-based construction of text providers."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from comicforge_ai.models.base import TextModelProvider
from comicforge_ai.models.deepseek_text import DeepSeekTextModel
from comicforge_ai.models.mock_text import MockTextModel
from comicforge_ai.models.ollama_text import OllamaTextModel
from comicforge_ai.models.openai_compatible_text import OpenAICompatibleTextModel


class TextModelRegistry:
    """A small explicit registry keyed by stable model IDs."""

    def __init__(self, providers: Iterable[TextModelProvider] = ()) -> None:
        self._providers: dict[str, TextModelProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: TextModelProvider) -> None:
        if provider.model_id in self._providers:
            raise ValueError(f"文本模型 ID 重复：{provider.model_id}")
        self._providers[provider.model_id] = provider

    def get(self, model_id: str) -> TextModelProvider:
        try:
            return self._providers[model_id]
        except KeyError as exc:
            raise KeyError(f"未注册的文本模型：{model_id}") from exc

    def list(self) -> list[TextModelProvider]:
        return list(self._providers.values())

    def choices(self) -> list[tuple[str, str]]:
        return [
            (f"{provider.display_name} · {provider.model_name}", provider.model_id)
            for provider in self.list()
        ]

    def configured_choices(self) -> list[tuple[str, str]]:
        """Return only locally configured providers for interactive UIs."""
        return [
            (f"{provider.display_name} · {provider.model_name}", provider.model_id)
            for provider in self.list()
            if provider.configuration_status().configured
        ]


def _number_setting(
    environment: Mapping[str, str], name: str, default: float
) -> float:
    try:
        return float(environment.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _integer_setting(
    environment: Mapping[str, str], name: str, default: int
) -> int:
    try:
        return int(environment.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _optional_boolean_setting(
    environment: Mapping[str, str], name: str
) -> bool | None:
    value = environment.get(name, "auto").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def build_default_registry(
    environment: Mapping[str, str] | None = None,
) -> TextModelRegistry:
    """Build all supported providers without requiring them to be configured."""
    env = environment if environment is not None else os.environ
    connect_timeout = _number_setting(env, "TEXT_MODEL_CONNECT_TIMEOUT", 10)
    generation_timeout = _number_setting(env, "TEXT_MODEL_GENERATION_TIMEOUT", 300)
    status_timeout = _number_setting(env, "TEXT_MODEL_STATUS_TIMEOUT", 10)
    retries = _integer_setting(env, "TEXT_MODEL_MAX_RETRIES", 1)
    language_repair_attempts = _integer_setting(
        env, "TEXT_MODEL_LANGUAGE_REPAIR_ATTEMPTS", 2
    )
    return TextModelRegistry(
        [
            MockTextModel(),
            OllamaTextModel(
                base_url=env.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
                model=env.get("OLLAMA_MODEL", ""),
                connect_timeout=_number_setting(
                    env, "OLLAMA_CONNECT_TIMEOUT", connect_timeout
                ),
                generation_timeout=_number_setting(
                    env, "OLLAMA_GENERATION_TIMEOUT", generation_timeout
                ),
                review_timeout=_number_setting(
                    env,
                    "OLLAMA_REVIEW_TIMEOUT",
                    _number_setting(env, "TEXT_MODEL_REVIEW_TIMEOUT", 90),
                ),
                status_timeout=status_timeout,
                num_predict=_integer_setting(env, "OLLAMA_NUM_PREDICT", 4096),
                num_ctx=_integer_setting(env, "OLLAMA_NUM_CTX", 8192),
                max_retries=retries,
                language_repair_attempts=language_repair_attempts,
            ),
            OpenAICompatibleTextModel(
                base_url=env.get("OPENAI_COMPATIBLE_BASE_URL", ""),
                api_key=env.get("OPENAI_COMPATIBLE_API_KEY", ""),
                model=env.get("OPENAI_COMPATIBLE_MODEL", ""),
                connect_timeout=connect_timeout,
                generation_timeout=generation_timeout,
                review_timeout=_number_setting(
                    env, "TEXT_MODEL_REVIEW_TIMEOUT", 90
                ),
                status_timeout=status_timeout,
                max_retries=retries,
                language_repair_attempts=language_repair_attempts,
                max_tokens=_integer_setting(
                    env, "OPENAI_COMPATIBLE_MAX_TOKENS", 4096
                ),
                disable_thinking=_optional_boolean_setting(
                    env, "OPENAI_COMPATIBLE_DISABLE_THINKING"
                ),
                reasoning_effort=env.get(
                    "OPENAI_COMPATIBLE_REASONING_EFFORT", ""
                ),
            ),
            DeepSeekTextModel(
                base_url=env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                api_key=env.get("DEEPSEEK_API_KEY", ""),
                model=env.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                connect_timeout=_number_setting(
                    env, "DEEPSEEK_CONNECT_TIMEOUT", connect_timeout
                ),
                generation_timeout=_number_setting(
                    env, "DEEPSEEK_GENERATION_TIMEOUT", generation_timeout
                ),
                review_timeout=_number_setting(
                    env,
                    "DEEPSEEK_REVIEW_TIMEOUT",
                    _number_setting(env, "TEXT_MODEL_REVIEW_TIMEOUT", 90),
                ),
                status_timeout=_number_setting(
                    env, "DEEPSEEK_STATUS_TIMEOUT", status_timeout
                ),
                max_retries=retries,
                language_repair_attempts=language_repair_attempts,
                max_tokens=_integer_setting(env, "DEEPSEEK_MAX_TOKENS", 32768),
                max_retry_tokens=_integer_setting(
                    env, "DEEPSEEK_MAX_RETRY_TOKENS", 65536
                ),
                disable_thinking=False,
            ),
        ]
    )
