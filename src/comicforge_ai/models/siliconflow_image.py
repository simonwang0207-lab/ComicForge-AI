"""SiliconFlow image-generation Provider with its native response schema."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from comicforge_ai.models.image_base import (
    ImageGenerationResult,
    ImageProviderCapabilities,
    ProviderResponseError,
)
from comicforge_ai.models.image_provider_utils import JsonObject
from comicforge_ai.models.json_image_provider import JsonImageProvider
from comicforge_ai.schemas import ImageGenerationRequest


class SiliconFlowImageProvider(JsonImageProvider):
    model_id = "siliconflow"
    display_name = "SiliconFlow Image"
    provider_type = "remote_http"
    api_key_environment = "SILICONFLOW_API_KEY"
    default_endpoint = "https://api.siliconflow.cn/v1/images/generations"
    capabilities = ImageProviderCapabilities(
        text_to_image=True,
        image_to_image=True,
        multi_reference=True,
        negative_prompt=True,
        seed=True,
        batch=True,
        arbitrary_size=True,
    )
    supported_formats = ("png",)

    def build_payload(self, request: ImageGenerationRequest) -> JsonObject:
        size = (
            f"{request.width}x{request.height}"
            if request.width and request.height
            else request.aspect_ratio or "1024x1024"
        )
        payload: JsonObject = {
            "model": request.model or self.model,
            "prompt": request.prompt,
            "image_size": size,
            "batch_size": request.count,
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            payload["seed"] = request.seed
        for index, image in enumerate(request.reference_images[:3], start=1):
            key = "image" if index == 1 else f"image{index}"
            payload[key] = _path_to_data_url(image)
        return payload

    def result_entries(self, payload: JsonObject) -> list[dict[str, object]]:
        images = payload.get("images")
        if not isinstance(images, list):
            raise ProviderResponseError("SiliconFlow 响应缺少 images 图片列表")
        return images

    def edit(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        if not request.reference_images:
            raise ProviderResponseError("SiliconFlow 图生图至少需要一张参考图")
        self.validate_request(request, operation="edit")
        result = super().generate(request, output_path)
        result.operation = "edit"
        return result


def _path_to_data_url(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ProviderResponseError(f"参考图读取失败：{path.name}") from exc
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"
