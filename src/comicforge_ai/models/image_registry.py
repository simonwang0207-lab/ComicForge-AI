"""Registration and environment-based construction of image providers."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from comicforge_ai.models.comfyui_image import ComfyUIImageProvider
from comicforge_ai.models.fal_image import FalImageProvider
from comicforge_ai.models.image_base import (
    ImageModelDefinition,
    ImageProvider,
    ImageProviderCapabilities,
)
from comicforge_ai.models.mock_image import MockImageModel
from comicforge_ai.models.openai_compatible_image import OpenAICompatibleImageModel
from comicforge_ai.models.recraft_image import RecraftImageProvider
from comicforge_ai.models.siliconflow_image import SiliconFlowImageProvider
from comicforge_ai.models.together_image import TogetherImageProvider


class ImageProviderRegistry:
    """Explicit provider/model registry used by services and dynamic UI controls."""

    def __init__(self, providers: Iterable[ImageProvider] = ()) -> None:
        self._providers: dict[str, ImageProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ImageProvider) -> None:
        if provider.model_id in self._providers:
            raise ValueError(f"图片模型 ID 重复：{provider.model_id}")
        self._providers[provider.model_id] = provider

    def get(self, model_id: str) -> ImageProvider:
        try:
            return self._providers[model_id]
        except KeyError as exc:
            raise KeyError(f"未注册的图片模型：{model_id}") from exc

    def list(self) -> list[ImageProvider]:
        return list(self._providers.values())

    def choices(self) -> list[tuple[str, str]]:
        """Backward-compatible provider choices."""
        return self.provider_choices()

    def provider_choices(self) -> list[tuple[str, str]]:
        return [
            (f"{provider.display_name} · {provider.model_name}", provider.model_id)
            for provider in self.list()
        ]

    def model_definitions(self, provider_id: str) -> list[ImageModelDefinition]:
        return self.get(provider_id).model_definitions()

    def model_choices(self, provider_id: str) -> list[tuple[str, str]]:
        return [
            (definition.display_name, definition.model_id)
            for definition in self.model_definitions(provider_id)
        ]

    def capabilities(self, provider_id: str) -> ImageProviderCapabilities:
        return self.get(provider_id).get_capabilities()


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


def _load_comfy_workflow(environment: Mapping[str, str]) -> dict[str, Any] | None:
    value = environment.get("COMFYUI_WORKFLOW_PATH", "").strip()
    if not value:
        return None
    path = Path(value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def build_default_image_registry(
    environment: Mapping[str, str] | None = None,
) -> ImageProviderRegistry:
    """Build all implemented P0 providers without requiring paid credentials."""
    env = environment if environment is not None else os.environ
    connect_timeout = _number_setting(env, "IMAGE_MODEL_CONNECT_TIMEOUT", 10)
    generation_timeout = _number_setting(
        env, "IMAGE_MODEL_GENERATION_TIMEOUT", 300
    )
    retries = _integer_setting(env, "IMAGE_MODEL_MAX_RETRIES", 1)
    retry_delay = _number_setting(env, "IMAGE_MODEL_RETRY_BASE_DELAY", 0.5)
    max_download_bytes = _integer_setting(
        env, "IMAGE_DOWNLOAD_MAX_BYTES", 20 * 1024 * 1024
    )
    common: dict[str, object] = {
        "connect_timeout": connect_timeout,
        "generation_timeout": generation_timeout,
        "max_retries": retries,
        "retry_base_delay": retry_delay,
        "max_download_bytes": max_download_bytes,
    }
    return ImageProviderRegistry(
        [
            MockImageModel(),
            OpenAICompatibleImageModel(
                base_url=env.get("OPENAI_IMAGE_BASE_URL", ""),
                api_key=env.get("OPENAI_IMAGE_API_KEY", ""),
                model=env.get("OPENAI_IMAGE_MODEL", ""),
                size=env.get("OPENAI_IMAGE_SIZE", "1024x1024"),
                **common,
            ),
            RecraftImageProvider(
                api_key=env.get("RECRAFT_API_KEY", ""),
                model=env.get("RECRAFT_MODEL", ""),
                endpoint=env.get("RECRAFT_IMAGE_ENDPOINT") or None,
                **common,
            ),
            TogetherImageProvider(
                api_key=env.get("TOGETHER_API_KEY", ""),
                model=env.get("TOGETHER_MODEL", ""),
                endpoint=env.get("TOGETHER_IMAGE_ENDPOINT") or None,
                **common,
            ),
            SiliconFlowImageProvider(
                api_key=env.get("SILICONFLOW_API_KEY", ""),
                model=env.get("SILICONFLOW_MODEL", ""),
                endpoint=env.get("SILICONFLOW_IMAGE_ENDPOINT") or None,
                **common,
            ),
            FalImageProvider(
                api_key=env.get("FAL_KEY", ""),
                model=env.get("FAL_MODEL", ""),
                base_url=env.get("FAL_BASE_URL", "https://queue.fal.run"),
                max_poll_seconds=_number_setting(
                    env, "IMAGE_MODEL_MAX_POLL_SECONDS", 300
                ),
                poll_interval=_number_setting(env, "IMAGE_MODEL_POLL_INTERVAL", 1),
                **common,
            ),
            ComfyUIImageProvider(
                base_url=env.get("COMFYUI_BASE_URL", ""),
                workflow=_load_comfy_workflow(env),
                prompt_node_id=env.get("COMFYUI_PROMPT_NODE_ID", ""),
                model=env.get("COMFYUI_MODEL", "comfyui-workflow"),
                width_node_id=env.get("COMFYUI_WIDTH_NODE_ID", ""),
                height_node_id=env.get("COMFYUI_HEIGHT_NODE_ID", ""),
                seed_node_id=env.get("COMFYUI_SEED_NODE_ID", ""),
                connect_timeout=connect_timeout,
                generation_timeout=generation_timeout,
                max_retries=retries,
                max_poll_seconds=_number_setting(
                    env, "IMAGE_MODEL_MAX_POLL_SECONDS", 300
                ),
                poll_interval=_number_setting(env, "IMAGE_MODEL_POLL_INTERVAL", 1),
                max_download_bytes=max_download_bytes,
            ),
        ]
    )
