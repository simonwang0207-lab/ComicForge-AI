"""Gemini native image generation and reference-image editing provider."""

from __future__ import annotations

import base64
import binascii
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from PIL import Image, UnidentifiedImageError

from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.image_base import (
    ConfigurationError,
    ImageGenerationResult,
    ImageModelError,
    ImageModelStatus,
    ImageProvider,
    ImageProviderCapabilities,
    ProviderResponseError,
)
from comicforge_ai.models.image_provider_utils import (
    DownloadTransport,
    JsonObject,
    JsonTransport,
    RetryPolicy,
    download_image,
    normalized_result,
    request_json,
    with_retry,
)
from comicforge_ai.schemas import ImageGenerationRequest


class GeminiImageProvider(ImageProvider):
    """Generate or edit one panel through a supported Gemini image API."""

    model_id = "gemini"
    display_name = "Gemini Image"
    provider_type = "remote_http"
    prompt_profile = "neutral"
    supported_sizes = (
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
        "1:4",
        "4:1",
        "1:8",
        "8:1",
    )
    supported_formats = ("png", "jpeg")
    supported_image_sizes = ("512", "1K", "2K", "4K")
    supported_api_modes = ("interactions", "generate-content")
    supported_generate_content_config_modes = (
        "image-config",
        "response-format",
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-3.1-flash-image",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        api_mode: str = "interactions",
        generate_content_config_mode: str = "image-config",
        image_size: str = "1K",
        connect_timeout: float = 10,
        generation_timeout: float = 300,
        status_timeout: float = 10,
        max_retries: int = 1,
        retry_base_delay: float = 0.5,
        max_download_bytes: int = 20 * 1024 * 1024,
        max_inline_request_bytes: int = 20 * 1024 * 1024,
        transport: JsonTransport = request_json,
        download_transport: DownloadTransport = download_image,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.api_mode = api_mode.strip().lower().replace("_", "-")
        self.generate_content_config_mode = (
            generate_content_config_mode.strip().lower().replace("_", "-")
        )
        self.image_size = image_size.strip().upper()
        if self.api_mode == "generate-content":
            # The tested generateContent gateway returns PNG inlineData. Do not
            # advertise JPEG and then silently ignore the requested format.
            self.supported_formats = ("png",)
        self.timeout = HttpTimeout(
            connect=max(0.1, connect_timeout),
            read=max(0.1, generation_timeout),
        )
        self.status_timeout = max(0.1, status_timeout)
        self.max_retries = max(0, max_retries)
        self.retry_policy = RetryPolicy(
            max_retries=self.max_retries,
            base_delay=max(0, retry_base_delay),
        )
        self.max_download_bytes = max(1024, max_download_bytes)
        self.max_inline_request_bytes = max(1024, max_inline_request_bytes)
        self.transport = transport
        self.download_transport = download_transport
        self.sleeper = sleeper

    @property
    def model_name(self) -> str:
        return self.model or "未配置"

    @property
    def endpoint(self) -> str:
        return self._generation_endpoint(self.model)

    @property
    def model_endpoint(self) -> str:
        if self.api_mode == "generate-content":
            return f"{self._service_root}/v1/models"
        return f"{self.base_url}/models/{quote(self.model, safe='-._')}"

    @property
    def _service_root(self) -> str:
        root = self.base_url
        for suffix in ("/v1beta", "/v1"):
            if root.lower().endswith(suffix):
                return root[: -len(suffix)]
        return root

    def _generation_endpoint(self, model: str) -> str:
        if self.api_mode == "generate-content":
            model_path = quote(model, safe="-._")
            encoded_key = quote(self.api_key, safe="")
            return (
                f"{self._service_root}/v1beta/models/{model_path}"
                f":generateContent?key={encoded_key}"
            )
        return f"{self.base_url}/interactions"

    @property
    def _headers(self) -> dict[str, str]:
        if self.api_mode == "generate-content":
            return {"Content-Type": "application/json"}
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    @property
    def _health_headers(self) -> dict[str, str]:
        if self.api_mode == "generate-content":
            return {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        return self._headers

    def get_capabilities(self) -> ImageProviderCapabilities:
        return ImageProviderCapabilities(
            text_to_image=True,
            image_to_image=True,
            multi_reference=True,
            negative_prompt=True,
        )

    def validate_config(self) -> ImageModelStatus:
        missing = tuple(
            name
            for name, value in (
                ("GEMINI_API_KEY", self.api_key),
                ("GEMINI_IMAGE_MODEL", self.model),
                ("GEMINI_BASE_URL", self.base_url),
            )
            if not value
        )
        problem = ""
        parsed = urlparse(self.base_url)
        if not missing and (
            parsed.scheme not in {"http", "https"} or not parsed.netloc
        ):
            problem = "GEMINI_BASE_URL 必须是有效的 HTTP(S) 地址"
        if not missing and self.image_size not in self.supported_image_sizes:
            problem = "GEMINI_IMAGE_SIZE 必须是 512、1K、2K 或 4K"
        if not missing and self.api_mode not in self.supported_api_modes:
            problem = (
                "GEMINI_API_MODE 必须是 interactions 或 generate-content"
            )
        if (
            not missing
            and self.api_mode == "generate-content"
            and self.generate_content_config_mode
            not in self.supported_generate_content_config_modes
        ):
            problem = (
                "GEMINI_GENERATE_CONTENT_CONFIG_MODE must be image-config "
                "or response-format"
            )
        configured = not missing and not problem
        if missing:
            message = "未配置：缺少 " + "、".join(missing)
        elif problem:
            message = "配置无效：" + problem
        else:
            message = (
                f"配置完整（{self.api_mode}）；"
                "可通过状态检测验证鉴权和模型访问。"
            )
        return ImageModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=configured,
            available=configured,
            message=message,
            missing_settings=missing,
            connect_timeout=self.timeout.connect,
            generation_timeout=self.timeout.read,
        )

    def health_check(self) -> ImageModelStatus:
        configured = self.validate_config()
        if not configured.configured:
            return configured
        try:
            payload = self.transport(
                "GET",
                self.model_endpoint,
                self._health_headers,
                None,
                HttpTimeout(
                    connect=self.timeout.connect,
                    read=self.status_timeout,
                ),
            )
            if self.api_mode == "generate-content":
                models = payload.get("data")
                model_ids = {
                    str(item.get("id", ""))
                    for item in models
                    if isinstance(item, dict)
                } if isinstance(models, list) else set()
                if self.model not in model_ids:
                    raise ProviderResponseError(
                        "模型列表接口可访问，但未返回配置的 Gemini 图片模型"
                    )
        except ImageModelError as exc:
            return ImageModelStatus(
                model_id=self.model_id,
                display_name=self.display_name,
                provider_type=self.provider_type,
                model_name=self.model_name,
                configured=True,
                available=False,
                message=f"Gemini API 不可用：{self.redact_secrets(str(exc))}",
                connect_timeout=self.timeout.connect,
                generation_timeout=self.timeout.read,
            )
        return ImageModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=True,
            available=True,
            message=(
                f"Gemini API 鉴权成功，目标图片模型可访问"
                f"（{self.api_mode}）。"
            ),
            connect_timeout=self.timeout.connect,
            generation_timeout=self.timeout.read,
        )

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        return self._generate(request, output_path, operation="text_to_image")

    def edit(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        return self._generate(request, output_path, operation="edit")

    def _generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None,
        *,
        operation: str,
    ) -> ImageGenerationResult:
        status = self.validate_config()
        if not status.configured:
            raise ConfigurationError(status.message)
        self.validate_request(request, operation=operation)

        prompt = request.prompt
        if request.negative_prompt.strip():
            prompt += "\nAvoid these visual elements: " + request.negative_prompt.strip()
        reference_blocks: list[dict[str, str]] = []
        encoded_size = len(prompt.encode("utf-8"))
        for path in request.reference_images:
            block = self._reference_image_block(path)
            encoded_size += len(block["data"])
            if encoded_size > self.max_inline_request_bytes:
                raise ConfigurationError(
                    "Gemini 内联参考图请求超过安全上限；请减少图片数量或压缩图片。"
                )
            reference_blocks.append(block)

        aspect_ratio = request.aspect_ratio or "1:1"
        model = request.model or self.model
        request_payload = self._request_payload(
            model=model,
            prompt=prompt,
            reference_blocks=reference_blocks,
            aspect_ratio=aspect_ratio,
            output_format=request.output_format,
        )
        started = time.perf_counter()
        payload, retry_count = with_retry(
            lambda: self.transport(
                "POST",
                self._generation_endpoint(model),
                self._headers,
                request_payload,
                self.timeout,
            ),
            self.retry_policy,
            sleeper=self.sleeper,
        )
        entries = (
            self._generate_content_image_entries(payload)
            if self.api_mode == "generate-content"
            else self._image_entries(payload)
        )
        self._enforce_inline_output_limit(entries)
        safe_fields = (
            ("responseId", "modelVersion", "usageMetadata", "promptFeedback")
            if self.api_mode == "generate-content"
            else ("id", "model", "object", "status", "usage")
        )
        safe_payload = {key: payload[key] for key in safe_fields if key in payload}
        request_id = str(payload.get("responseId") or payload.get("id") or "")
        actual_parameters: dict[str, Any] = {
            "aspect_ratio": aspect_ratio,
            "image_size": self.image_size,
            "output_format": request.output_format,
            "reference_count": len(request.reference_images),
            "retry_count": retry_count,
            "api_mode": self.api_mode,
        }
        if self.api_mode == "generate-content":
            actual_parameters["generate_content_config_mode"] = (
                self.generate_content_config_mode
            )
        return normalized_result(
            provider=self.model_id,
            provider_name=self.display_name,
            model=model,
            operation=operation,
            payload=safe_payload,
            entries=entries,
            duration=time.perf_counter() - started,
            output_path=output_path,
            downloader=self.download_transport,
            timeout=self.timeout,
            max_bytes=self.max_download_bytes,
            actual_parameters=actual_parameters,
            request_id=request_id,
        )

    def _request_payload(
        self,
        *,
        model: str,
        prompt: str,
        reference_blocks: list[dict[str, str]],
        aspect_ratio: str,
        output_format: str,
    ) -> JsonObject:
        if self.api_mode == "generate-content":
            parts: list[dict[str, Any]] = [{"text": prompt}]
            parts.extend(
                {
                    "inline_data": {
                        "mime_type": block["mime_type"],
                        "data": block["data"],
                    }
                }
                for block in reference_blocks
            )
            generation_config: dict[str, Any] = {
                "responseModalities": ["TEXT", "IMAGE"],
            }
            image_config = {
                "aspectRatio": aspect_ratio,
                "imageSize": self.image_size,
            }
            if self.generate_content_config_mode == "image-config":
                generation_config["imageConfig"] = image_config
            else:
                generation_config["responseFormat"] = {
                    "image": image_config,
                }
            return {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": generation_config,
            }

        response_mime = "image/jpeg" if output_format == "jpeg" else "image/png"
        inputs: list[dict[str, str]] = [{"type": "text", "text": prompt}]
        inputs.extend(reference_blocks)
        return {
            "model": model,
            "input": inputs,
            "response_format": {
                "type": "image",
                "delivery": "inline",
                "mime_type": response_mime,
                "aspect_ratio": aspect_ratio,
                "image_size": self.image_size,
            },
        }

    def _reference_image_block(self, path: Path) -> dict[str, str]:
        try:
            data = path.read_bytes()
            with Image.open(path) as image:
                image.verify()
                image_format = (image.format or "").upper()
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise ConfigurationError(f"Gemini 参考图无效：{path.name}") from exc
        mime_type = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "WEBP": "image/webp",
        }.get(image_format)
        if not mime_type:
            raise ConfigurationError(
                f"Gemini 参考图格式不支持：{path.name}；请使用 PNG、JPEG 或 WebP。"
            )
        return {
            "type": "image",
            "data": base64.b64encode(data).decode("ascii"),
            "mime_type": mime_type,
        }

    @staticmethod
    def _image_entries(payload: JsonObject) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        steps = payload.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict) or step.get("type") != "model_output":
                    continue
                content = step.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "image":
                        continue
                    data = block.get("data")
                    uri = block.get("uri")
                    if isinstance(data, str) and data:
                        entries.append({"b64_json": data})
                    elif isinstance(uri, str) and uri:
                        entries.append({"url": uri})
        if not entries:
            raise ProviderResponseError(
                "Gemini 响应中没有可用图片；请求可能被安全策略拒绝或未完成。"
            )
        return entries[-1:]

    @staticmethod
    def _generate_content_image_entries(
        payload: JsonObject,
    ) -> list[dict[str, Any]]:
        images: list[tuple[bool, dict[str, Any]]] = []
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                if not isinstance(content, dict):
                    continue
                parts = content.get("parts")
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    inline = part.get("inlineData") or part.get("inline_data")
                    if not isinstance(inline, dict):
                        continue
                    data = inline.get("data")
                    if isinstance(data, str) and data:
                        images.append((bool(part.get("thought")), {"b64_json": data}))
        if not images:
            raise ProviderResponseError(
                "Gemini generateContent 响应中没有可用 inlineData 图片；"
                "请求可能被安全策略拒绝或中转未返回图片。"
            )
        visible = [entry for thought, entry in images if not thought]
        return (visible or [entry for _, entry in images])[-1:]

    def _enforce_inline_output_limit(self, entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            encoded = entry.get("b64_json")
            if not isinstance(encoded, str):
                continue
            if len(encoded) > ((self.max_download_bytes + 2) // 3) * 4:
                raise ProviderResponseError("Gemini 返回图片超过安全大小上限。")
            try:
                decoded_size = len(base64.b64decode(encoded, validate=True))
            except (binascii.Error, ValueError) as exc:
                raise ProviderResponseError("Gemini 返回的图片 base64 无效。") from exc
            if decoded_size > self.max_download_bytes:
                raise ProviderResponseError("Gemini 返回图片超过安全大小上限。")
