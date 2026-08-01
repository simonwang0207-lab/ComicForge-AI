"""Registration and environment-based construction of text providers."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

from comicforge_ai.models.base import TextModelProvider
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


def build_default_registry(
    environment: Mapping[str, str] | None = None,
) -> TextModelRegistry:
    """Build all supported providers without requiring them to be configured."""
    env = environment if environment is not None else os.environ
    connect_timeout = _number_setting(env, "TEXT_MODEL_CONNECT_TIMEOUT", 10)
    generation_timeout = _number_setting(env, "TEXT_MODEL_GENERATION_TIMEOUT", 300)
    status_timeout = _number_setting(env, "TEXT_MODEL_STATUS_TIMEOUT", 10)
    retries = _integer_setting(env, "TEXT_MODEL_MAX_RETRIES", 1)
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
                status_timeout=status_timeout,
                max_retries=retries,
            ),
            OpenAICompatibleTextModel(
                base_url=env.get("OPENAI_COMPATIBLE_BASE_URL", ""),
                api_key=env.get("OPENAI_COMPATIBLE_API_KEY", ""),
                model=env.get("OPENAI_COMPATIBLE_MODEL", ""),
                connect_timeout=connect_timeout,
                generation_timeout=generation_timeout,
                status_timeout=status_timeout,
                max_retries=retries,
            ),
        ]
    )
