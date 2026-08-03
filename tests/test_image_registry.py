import pytest

from comicforge_ai.models import MockImageModel
from comicforge_ai.models.image_registry import (
    ImageProviderRegistry,
    build_default_image_registry,
)
from comicforge_ai.models.openai_compatible_image import OpenAICompatibleImageModel


def test_default_image_registry_reads_environment_configuration() -> None:
    registry = build_default_image_registry(
        {
            "OPENAI_IMAGE_BASE_URL": "https://images.invalid/v1",
            "OPENAI_IMAGE_API_KEY": "placeholder-key",
            "OPENAI_IMAGE_MODEL": "demo-image-model",
            "OPENAI_IMAGE_SIZE": "768x768",
            "IMAGE_MODEL_CONNECT_TIMEOUT": "4",
            "IMAGE_MODEL_GENERATION_TIMEOUT": "120",
            "IMAGE_MODEL_MAX_RETRIES": "2",
        }
    )

    provider = registry.get("openai-compatible-image")
    assert isinstance(provider, OpenAICompatibleImageModel)
    status = provider.check_availability()

    assert status.configured is True
    assert status.provider_type == "remote_http"
    assert status.connect_timeout == 4
    assert status.generation_timeout == 120
    assert provider.size == "768x768"
    assert provider.max_retries == 2
    assert [value for _, value in registry.choices()] == [
        "mock-image",
        "openai-compatible-image",
        "recraft",
        "together",
        "siliconflow",
        "fal",
        "comfyui",
    ]
    assert registry.capabilities("fal").async_task is True
    assert registry.capabilities("siliconflow").multi_reference is True
    assert registry.model_choices("openai-compatible-image")


def test_image_registry_rejects_duplicate_provider_ids() -> None:
    with pytest.raises(ValueError, match="图片模型 ID 重复"):
        ImageProviderRegistry([MockImageModel(), MockImageModel()])
