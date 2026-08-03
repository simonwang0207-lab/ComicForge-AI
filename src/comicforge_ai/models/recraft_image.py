"""Recraft image-generation Provider."""

from __future__ import annotations

from comicforge_ai.models.image_base import (
    ImageProviderCapabilities,
    ProviderResponseError,
)
from comicforge_ai.models.image_provider_utils import JsonObject
from comicforge_ai.models.json_image_provider import JsonImageProvider
from comicforge_ai.schemas import ImageGenerationRequest


class RecraftImageProvider(JsonImageProvider):
    model_id = "recraft"
    display_name = "Recraft Image"
    provider_type = "remote_http"
    api_key_environment = "RECRAFT_API_KEY"
    default_endpoint = "https://external.api.recraft.ai/v1/images/generations"
    capabilities = ImageProviderCapabilities(
        text_to_image=True,
        negative_prompt=True,
        batch=True,
    )
    supported_sizes = (
        "1024x1024",
        "1365x1024",
        "1024x1365",
        "1536x1024",
        "1024x1536",
        "1:1",
        "4:3",
        "3:4",
        "3:2",
        "2:3",
    )
    supported_formats = ("png",)

    def build_payload(self, request: ImageGenerationRequest) -> JsonObject:
        size = request.aspect_ratio or (
            f"{request.width}x{request.height}"
            if request.width and request.height
            else "1:1"
        )
        payload: JsonObject = {
            "model": request.model or self.model,
            "prompt": request.prompt,
            "n": request.count,
            "size": size,
            "response_format": "b64_json",
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        return payload

    def result_entries(self, payload: JsonObject) -> list[dict[str, object]]:
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderResponseError("Recraft 响应缺少 data 图片列表")
        return data
