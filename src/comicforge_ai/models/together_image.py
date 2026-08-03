"""Together AI image-generation Provider."""

from __future__ import annotations

from comicforge_ai.models.image_base import (
    ImageProviderCapabilities,
    ProviderResponseError,
)
from comicforge_ai.models.image_provider_utils import JsonObject
from comicforge_ai.models.json_image_provider import JsonImageProvider
from comicforge_ai.schemas import ImageGenerationRequest


class TogetherImageProvider(JsonImageProvider):
    model_id = "together"
    display_name = "Together Image"
    provider_type = "remote_http"
    api_key_environment = "TOGETHER_API_KEY"
    default_endpoint = "https://api.together.xyz/v1/images/generations"
    capabilities = ImageProviderCapabilities(
        text_to_image=True,
        negative_prompt=True,
        seed=True,
        batch=True,
        arbitrary_size=True,
    )
    supported_formats = ("png", "jpeg")

    def build_payload(self, request: ImageGenerationRequest) -> JsonObject:
        payload: JsonObject = {
            "model": request.model or self.model,
            "prompt": request.prompt,
            "n": request.count,
            "response_format": "base64",
            "output_format": request.output_format,
        }
        if request.width and request.height:
            payload.update({"width": request.width, "height": request.height})
        elif request.aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            payload["seed"] = request.seed
        return payload

    def result_entries(self, payload: JsonObject) -> list[dict[str, object]]:
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderResponseError("Together 响应缺少 data 图片列表")
        return data
