"""Reusable synchronous JSON image-provider base class."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.image_base import (
    ConfigurationError,
    ImageGenerationResult,
    ImageModelDefinition,
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
    Sleeper,
    download_image,
    normalized_result,
    request_json,
    with_retry,
)
from comicforge_ai.schemas import ImageGenerationRequest


class JsonImageProvider(ImageProvider):
    """Common configuration, retry, and normalization for sync JSON APIs."""

    api_key_environment = "IMAGE_API_KEY"
    default_endpoint = ""
    capabilities = ImageProviderCapabilities()
    supported_sizes: tuple[str, ...] = ()
    supported_formats: tuple[str, ...] = ("png", "jpeg", "webp")

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        endpoint: str | None = None,
        connect_timeout: float = 10,
        generation_timeout: float = 300,
        max_retries: int = 1,
        retry_base_delay: float = 0.5,
        max_download_bytes: int = 20 * 1024 * 1024,
        transport: JsonTransport | None = None,
        download_transport: DownloadTransport | None = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.endpoint = (endpoint or self.default_endpoint).strip().rstrip("/")
        self.timeout = HttpTimeout(
            connect=max(0.1, connect_timeout),
            read=max(0.1, generation_timeout),
        )
        self.retry_policy = RetryPolicy(
            max_retries=max(0, max_retries),
            base_delay=max(0, retry_base_delay),
        )
        self.max_download_bytes = max(1024, max_download_bytes)
        self.transport = transport or request_json
        self.download_transport = download_transport or download_image
        self.sleeper = sleeper

    @property
    def model_name(self) -> str:
        return self.model or "未配置"

    def get_capabilities(self) -> ImageProviderCapabilities:
        return self.capabilities

    def model_definitions(self) -> list[ImageModelDefinition]:
        return [
            ImageModelDefinition(
                provider_id=self.model_id,
                model_id=self.model_name,
                display_name=self.model_name,
                capabilities=self.capabilities,
                supported_sizes=self.supported_sizes,
                supported_formats=self.supported_formats,
                default_parameters=self.default_parameters(),
                requires_async_polling=self.capabilities.async_task,
                supports_reference_images=self.capabilities.image_to_image,
                supports_image_edit=self.capabilities.image_to_image,
            )
        ]

    def default_parameters(self) -> dict[str, object]:
        return {"count": 1, "output_format": "png"}

    def validate_config(self) -> ImageModelStatus:
        missing = tuple(
            name
            for name, value in (
                (self.api_key_environment, self.api_key),
                (f"{self.model_id.upper().replace('-', '_')}_MODEL", self.model),
            )
            if not value
        )
        problem = ""
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            problem = "Provider endpoint 不是有效 HTTP(S) 地址"
        configured = not missing and not problem
        if missing:
            message = "未配置：缺少 " + "、".join(missing)
        elif problem:
            message = "配置无效：" + problem
        else:
            message = "配置完整；连接将在实际生成时验证"
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

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        status = self.validate_config()
        if not status.configured:
            raise ConfigurationError(status.message)
        self.validate_request(request, operation="text_to_image")
        started = time.perf_counter()
        try:
            payload, retries = with_retry(
                lambda: self.transport(
                    "POST",
                    self.endpoint,
                    self.request_headers(),
                    self.build_payload(request),
                    self.timeout,
                ),
                self.retry_policy,
                sleeper=self.sleeper,
            )
            result = self.normalize_result(
                payload,
                request,
                operation="text_to_image",
                output_path=output_path,
            )
            result.duration = time.perf_counter() - started
            actual = dict(result.actual_parameters or {})
            actual["retries"] = retries
            result.actual_parameters = actual
            return result
        except ImageModelError as exc:
            safe = self.redact_secrets(str(exc))
            if safe != str(exc):
                exc.args = (safe,)
            raise

    def request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def build_payload(self, request: ImageGenerationRequest) -> JsonObject:
        raise NotImplementedError

    def result_entries(self, payload: JsonObject) -> list[dict[str, object]]:
        raise NotImplementedError

    def normalize_result(
        self,
        payload: JsonObject,
        request: ImageGenerationRequest,
        *,
        operation: str,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        entries = self.result_entries(payload)
        if not all(isinstance(entry, dict) for entry in entries):
            raise ProviderResponseError("Provider 图片列表结构无效")
        return normalized_result(
            provider=self.model_id,
            provider_name=self.display_name,
            model=request.model or self.model,
            operation=operation,
            payload=payload,
            entries=entries,
            duration=0,
            output_path=output_path,
            downloader=self.download_transport,
            timeout=self.timeout,
            max_bytes=self.max_download_bytes,
            actual_parameters=self.actual_parameters(request),
            seed=self.result_seed(payload, request),
            request_id=self.result_request_id(payload),
        )

    def actual_parameters(self, request: ImageGenerationRequest) -> dict[str, object]:
        return {
            "width": request.width,
            "height": request.height,
            "aspect_ratio": request.aspect_ratio,
            "quality": request.quality,
            "count": request.count,
            "seed": request.seed,
            "style": request.style,
            "output_format": request.output_format,
        }

    @staticmethod
    def result_seed(
        payload: JsonObject,
        request: ImageGenerationRequest,
    ) -> int | None:
        value = payload.get("seed", request.seed)
        return value if isinstance(value, int) else request.seed

    @staticmethod
    def result_request_id(payload: JsonObject) -> str:
        value = payload.get("id") or payload.get("request_id")
        return str(value) if value else ""
