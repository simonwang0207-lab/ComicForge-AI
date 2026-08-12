import pytest

from comicforge_ai.models import MockTextModel, TextModelRegistry
from comicforge_ai.models.registry import build_default_registry


def test_default_registry_contains_all_three_provider_types() -> None:
    registry = build_default_registry({})

    assert [provider.model_id for provider in registry.list()] == [
        "mock",
        "ollama",
        "openai-compatible",
        "deepseek",
    ]
    assert registry.get("mock").display_name == "Mock 文本模型（离线）"


def test_registry_rejects_duplicate_ids_and_unknown_lookup() -> None:
    registry = TextModelRegistry([MockTextModel()])

    with pytest.raises(ValueError, match="ID 重复"):
        registry.register(MockTextModel())
    with pytest.raises(KeyError, match="未注册"):
        registry.get("missing")


def test_registry_configures_separate_ollama_timeouts() -> None:
    registry = build_default_registry(
        {
            "OLLAMA_MODEL": "qwen3:4b",
            "TEXT_MODEL_CONNECT_TIMEOUT": "4",
            "TEXT_MODEL_GENERATION_TIMEOUT": "345",
            "TEXT_MODEL_STATUS_TIMEOUT": "7",
        }
    )

    provider = registry.get("ollama")
    assert provider.connect_timeout == 4  # type: ignore[attr-defined]
    assert provider.generation_timeout == 345  # type: ignore[attr-defined]
    assert provider.status_timeout == 7  # type: ignore[attr-defined]
    assert provider.num_predict == 4096  # type: ignore[attr-defined]
    assert provider.num_ctx == 8192  # type: ignore[attr-defined]


def test_configured_choices_hide_unconfigured_text_providers() -> None:
    registry = build_default_registry({})

    assert [value for _, value in registry.configured_choices()] == ["mock"]

    configured = build_default_registry({"OLLAMA_MODEL": "qwen3:4b"})
    assert [value for _, value in configured.configured_choices()] == [
        "mock",
        "ollama",
    ]
