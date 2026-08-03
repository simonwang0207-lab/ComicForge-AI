"""OpenAI-compatible Images API provider with local PNG persistence."""

from __future__ import annotations

import base64
import binascii
import logging
import mimetypes
import re
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.image_base import (
    ConfigurationError,
    ImageDecodeError,
    ImageDownloadError,
    ImageGeneration,
    ImageModelConfigurationError,
    ImageModelConnectionError,
    ImageModelError,
    ImageModelGenerationTimeoutError,
    ImageModelHttpError,
    ImageModelRequestError,
    ImageModelResponseError,
    ImageModelStatus,
    ImageProvider,
    ImageProviderCapabilities,
    ImageSaveError,
    InvalidGeneratedImageError,
    ProviderResponseError,
)
from comicforge_ai.models.image_provider_utils import (
    MultipartTransport,
    RetryPolicy,
    download_image,
    normalized_result,
    request_json,
    request_multipart,
    should_retry,
    with_retry,
)
from comicforge_ai.schemas import PanelImageRequest

logger = logging.getLogger(__name__)
JsonObject = dict[str, Any]
ImageJsonTransport = Callable[
    [str, str, dict[str, str], JsonObject, HttpTimeout], JsonObject
]
ImageDownloadTransport = Callable[[str, HttpTimeout], bytes]


def build_images_endpoint(base_url: str) -> str:
    """Normalize a service root or `/v1` URL to one images endpoint."""
    clean = base_url.strip().rstrip("/")
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImageModelConfigurationError("OPENAI_IMAGE_BASE_URL 不是有效的 HTTP(S) 地址")
    if parsed.query or parsed.fragment:
        raise ImageModelConfigurationError("OPENAI_IMAGE_BASE_URL 不能包含查询参数或片段")
    if clean.endswith("/images/generations"):
        return clean
    if clean.endswith("/v1"):
        return clean + "/images/generations"
    return clean + "/v1/images/generations"


def _safe_http_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.reason_phrase[:200]
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message") or payload.get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("type")
        if isinstance(detail, str):
            return detail[:300]
    return response.reason_phrase[:200]


def _request_image_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: JsonObject,
    timeout: HttpTimeout,
) -> JsonObject:
    started = time.perf_counter()
    request_timeout = httpx.Timeout(
        connect=timeout.connect,
        read=timeout.read,
        write=timeout.connect,
        pool=timeout.connect,
    )
    try:
        response = httpx.request(
            method,
            url,
            headers={"Accept": "application/json", **headers},
            json=payload,
            timeout=request_timeout,
        )
    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        elapsed = time.perf_counter() - started
        message = (
            f"连接图片服务超时（连接上限 {timeout.connect:g} 秒）"
            if isinstance(exc, httpx.ConnectTimeout)
            else "无法连接图片服务"
        )
        raise ImageModelConnectionError(
            message,
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
        elapsed = time.perf_counter() - started
        raise ImageModelGenerationTimeoutError(
            f"图片生成超时（读取上限 {timeout.read:g} 秒）",
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc
    except httpx.RequestError as exc:
        elapsed = time.perf_counter() - started
        raise ImageModelConnectionError(
            "图片服务请求失败",
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc

    elapsed = time.perf_counter() - started
    if response.is_error:
        original = httpx.HTTPStatusError(
            f"HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
        raise ImageModelHttpError(
            response.status_code,
            _safe_http_detail(response),
            elapsed_seconds=elapsed,
            original_exception=original,
        )
    try:
        parsed = response.json()
    except ValueError as exc:
        raise ImageModelResponseError("图片服务返回了无效的 JSON") from exc
    if not isinstance(parsed, dict):
        raise ImageModelResponseError("图片服务返回的 JSON 不是对象")
    return parsed


def _download_image(url: str, timeout: HttpTimeout) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImageDownloadError("图片服务返回了无效的下载地址")
    started = time.perf_counter()
    request_timeout = httpx.Timeout(
        connect=timeout.connect,
        read=timeout.read,
        write=timeout.connect,
        pool=timeout.connect,
    )
    try:
        response = httpx.get(url, timeout=request_timeout)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ImageDownloadError(
            "图片 URL 下载超时",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise ImageDownloadError(
            f"图片 URL 下载失败（状态码 {exc.response.status_code}）",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    except httpx.RequestError as exc:
        raise ImageDownloadError(
            "图片 URL 下载连接失败",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    return response.content


class OpenAICompatibleImageModel(ImageProvider):
    """Generate panel images using a generic OpenAI-compatible Images API."""

    model_id = "openai-compatible-image"
    display_name = "OpenAI-compatible Image API"
    provider_type = "remote_http"
    supported_sizes = ("1024x1024", "1536x1024", "1024x1536")
    supported_formats = ("png", "jpeg", "webp")

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        size: str = "1024x1024",
        connect_timeout: float = 10,
        generation_timeout: float = 300,
        max_retries: int = 1,
        retry_base_delay: float = 0.5,
        max_download_bytes: int = 20 * 1024 * 1024,
        transport: ImageJsonTransport | None = None,
        download_transport: ImageDownloadTransport | None = None,
        multipart_transport: MultipartTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.size = size.strip()
        self.timeout = HttpTimeout(
            connect=max(0.1, connect_timeout),
            read=max(0.1, generation_timeout),
        )
        self.max_retries = max(0, max_retries)
        self.retry_policy = RetryPolicy(
            max_retries=self.max_retries,
            base_delay=max(0, retry_base_delay),
        )
        self.max_download_bytes = max(1024, max_download_bytes)
        self.transport = transport or request_json
        self.download_transport = download_transport or (
            lambda url, timeout: download_image(
                url,
                timeout,
                self.max_download_bytes,
            )
        )
        self.multipart_transport = multipart_transport or request_multipart
        self.sleeper = sleeper

    @property
    def model_name(self) -> str:
        return self.model or "未配置"

    @property
    def endpoint(self) -> str:
        return build_images_endpoint(self.base_url)

    def check_availability(self) -> ImageModelStatus:
        return self.validate_config()

    def validate_config(self) -> ImageModelStatus:
        missing = tuple(
            name
            for name, value in (
                ("OPENAI_IMAGE_BASE_URL", self.base_url),
                ("OPENAI_IMAGE_API_KEY", self.api_key),
                ("OPENAI_IMAGE_MODEL", self.model),
            )
            if not value
        )
        problem = ""
        if not missing:
            try:
                _ = self.endpoint
            except ImageModelConfigurationError as exc:
                problem = str(exc)
            if not re.fullmatch(r"[1-9]\d*x[1-9]\d*", self.size):
                problem = "OPENAI_IMAGE_SIZE 必须采用宽x高格式，例如 1024x1024"
        configured = not missing and not problem
        if missing:
            message = "未配置：缺少 " + "、".join(missing)
        elif problem:
            message = "配置无效：" + problem
        else:
            message = "配置完整；连接和返回格式将在实际生成时验证"
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
        request: PanelImageRequest,
        output_path: Path | None = None,
    ) -> ImageGeneration:
        status = self.check_availability()
        if not status.configured:
            raise ConfigurationError(status.message)
        self.validate_request(request, operation="text_to_image")

        started = time.perf_counter()
        last_error: ImageModelError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                size = (
                    f"{request.width}x{request.height}"
                    if request.width and request.height
                    else self.size
                )
                request_payload: JsonObject = {
                    "model": request.model or self.model,
                    "prompt": request.prompt,
                    "size": size,
                    "n": request.count,
                }
                if request.quality != "auto":
                    request_payload["quality"] = request.quality
                if request.output_format != "png":
                    request_payload["output_format"] = request.output_format
                background = request.metadata.get("background")
                if background:
                    request_payload["background"] = background
                payload = self.transport(
                    "POST",
                    self.endpoint,
                    {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    request_payload,
                    self.timeout,
                )
                elapsed = time.perf_counter() - started
                logger.info(
                    "Image generation completed: provider=%s model=%s panel=%s elapsed=%.2fs retries=%s",
                    self.model_id,
                    self.model,
                    request.panel.sequence if request.panel else 0,
                    elapsed,
                    attempt,
                )
                result = self.normalize_result(
                    payload,
                    request,
                    operation="text_to_image",
                    output_path=output_path,
                )
                result.duration = elapsed
                actual = dict(result.actual_parameters or {})
                actual["retries"] = attempt
                result.actual_parameters = actual
                return result
            except ImageModelError as exc:
                safe_error = self._redact_error(exc)
                last_error = safe_error
                logger.warning(
                    "Image generation failed: provider=%s model=%s panel=%s error_type=%s attempt=%s",
                    self.model_id,
                    self.model,
                    request.panel.sequence if request.panel else 0,
                    type(safe_error).__name__,
                    attempt + 1,
                )
                if attempt >= self.max_retries:
                    if safe_error is exc:
                        raise
                    raise safe_error from exc
                if not should_retry(safe_error):
                    if safe_error is exc:
                        raise
                    raise safe_error from exc
                self.sleeper(
                    min(
                        self.retry_policy.max_delay,
                        self.retry_policy.base_delay * (2**attempt),
                    )
                )
        raise ImageModelRequestError("图片生成失败") from last_error

    def _redact_error(self, error: ImageModelError) -> ImageModelError:
        """Prevent a service that echoes credentials from leaking them."""
        original_message = str(error)
        safe_message = original_message.replace(self.api_key, "[REDACTED]")
        safe_message = re.sub(
            r"Bearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer [REDACTED]",
            safe_message,
            flags=re.IGNORECASE,
        )
        if safe_message == original_message:
            return error
        return ImageModelRequestError(
            safe_message,
            elapsed_seconds=getattr(error, "elapsed_seconds", None),
            original_exception=error,
        )

    def _extract_image_bytes(self, payload: JsonObject) -> bytes:
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ImageModelResponseError(
                "图片服务返回结构不兼容：缺少 data[0]"
            )
        first = data[0]
        encoded = first.get("b64_json")
        if isinstance(encoded, str) and encoded:
            try:
                return base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ImageDecodeError("图片服务返回的 b64_json 无法解码") from exc
        url = first.get("url")
        if isinstance(url, str) and url:
            return self.download_transport(url, self.timeout)
        raise ImageModelResponseError(
            "图片服务返回结构不兼容：data[0] 中没有 url 或 b64_json"
        )

    def get_capabilities(self) -> ImageProviderCapabilities:
        return ImageProviderCapabilities(
            text_to_image=True,
            image_to_image=True,
            multi_reference=True,
            mask_edit=True,
            inpainting=True,
            batch=True,
            transparent_background=True,
            quality=True,
        )

    def edit(
        self,
        request: PanelImageRequest,
        output_path: Path | None = None,
    ) -> ImageGeneration:
        status = self.validate_config()
        if not status.configured:
            raise ConfigurationError(status.message)
        self.validate_request(request, operation="edit")
        if not request.reference_images:
            raise ProviderResponseError("OpenAI 图片编辑至少需要一张参考图")
        data = {
            "model": request.model or self.model,
            "prompt": request.prompt,
            "n": str(request.count),
            "size": (
                f"{request.width}x{request.height}"
                if request.width and request.height
                else self.size
            ),
            "quality": request.quality,
            "output_format": request.output_format,
            "response_format": "b64_json",
        }
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for image_path in request.reference_images:
            files.append(("image[]", self._multipart_file(image_path)))
        if request.mask_image is not None:
            files.append(("mask", self._multipart_file(request.mask_image)))
        started = time.perf_counter()
        payload, retries = with_retry(
            lambda: self.multipart_transport(
                self.endpoint.replace("/generations", "/edits"),
                {"Authorization": f"Bearer {self.api_key}"},
                data,
                files,
                self.timeout,
            ),
            self.retry_policy,
            sleeper=self.sleeper,
        )
        result = self.normalize_result(
            payload,
            request,
            operation="edit",
            output_path=output_path,
        )
        result.duration = time.perf_counter() - started
        actual = dict(result.actual_parameters or {})
        actual["retries"] = retries
        result.actual_parameters = actual
        return result

    def normalize_result(
        self,
        payload: JsonObject,
        request: PanelImageRequest,
        *,
        operation: str,
        output_path: Path | None = None,
    ) -> ImageGeneration:
        data = payload.get("data")
        if not isinstance(data, list) or not all(
            isinstance(entry, dict) for entry in data
        ):
            raise ProviderResponseError("OpenAI Images 响应缺少 data 图片列表")
        return normalized_result(
            provider=self.model_id,
            provider_name=self.display_name,
            model=request.model or self.model,
            operation=operation,
            payload=payload,
            entries=data,
            duration=0,
            output_path=output_path,
            downloader=lambda url, timeout, max_bytes: self.download_transport(
                url, timeout
            ),
            timeout=self.timeout,
            max_bytes=self.max_download_bytes,
            actual_parameters={
                "width": request.width,
                "height": request.height,
                "quality": request.quality,
                "count": request.count,
                "output_format": request.output_format,
                "reference_count": len(request.reference_images),
                "mask": request.mask_image is not None,
            },
            seed=request.seed,
            request_id=str(payload.get("id", "")),
        )

    @staticmethod
    def _multipart_file(path: Path) -> tuple[str, bytes, str]:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ProviderResponseError(f"参考图读取失败：{path.name}") from exc
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        return path.name, content, media_type

    @staticmethod
    def _decode_image(image_bytes: bytes) -> Image.Image:
        try:
            with Image.open(BytesIO(image_bytes)) as source:
                source.load()
                image = source.convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidGeneratedImageError("图片服务返回的内容不是有效图片") from exc
        return image

    @staticmethod
    def _save_image(image: Image.Image, output_path: Path) -> None:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, format="PNG")
        except OSError as exc:
            raise ImageSaveError(f"真实分镜图片保存失败：{output_path.name}") from exc

    @classmethod
    def _decode_and_save(cls, image_bytes: bytes, output_path: Path) -> Image.Image:
        """Backward-compatible helper retained for existing callers."""
        image = cls._decode_image(image_bytes)
        cls._save_image(image, output_path)
        return image


# Provider 2.0 preferred name; old class name remains import-compatible.
OpenAIImageProvider = OpenAICompatibleImageModel
