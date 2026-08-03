"""HTTP, retry, download, decoding, and normalization helpers for image providers."""

from __future__ import annotations

import base64
import binascii
import time
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.image_base import (
    AuthenticationError,
    ContentPolicyError,
    ImageDecodeError,
    ImageDownloadError,
    ImageGenerationResult,
    ImageModelConnectionError,
    ImageModelError,
    ImageModelHttpError,
    ImageModelRequestError,
    ImageSaveError,
    InsufficientBalanceError,
    InvalidGeneratedImageError,
    ProviderResponseError,
    ProviderTimeoutError,
    RateLimitError,
)

JsonObject = dict[str, Any]
JsonTransport = Callable[
    [str, str, dict[str, str], JsonObject | None, HttpTimeout], JsonObject
]
MultipartTransport = Callable[
    [str, dict[str, str], dict[str, str], list[tuple[str, tuple[str, bytes, str]]], HttpTimeout],
    JsonObject,
]
DownloadTransport = Callable[[str, HttpTimeout, int], bytes]
Sleeper = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 1
    base_delay: float = 0.5
    max_delay: float = 8


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.reason_phrase[:200]
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message") or payload.get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("type") or detail.get("code")
        if isinstance(detail, list):
            return "请求参数不符合 Provider 要求"
        if isinstance(detail, str):
            return detail[:300]
    return response.reason_phrase[:200]


def _raise_http_error(response: httpx.Response, elapsed: float) -> None:
    status = response.status_code
    detail = _safe_error_detail(response)
    kwargs = {"elapsed_seconds": elapsed}
    if status in {401, 403}:
        raise AuthenticationError("图片 Provider 鉴权失败", **kwargs)
    if status == 402:
        raise InsufficientBalanceError("图片 Provider 余额或额度不足", **kwargs)
    if status == 429:
        raise RateLimitError("图片 Provider 请求过于频繁", **kwargs)
    if status == 400 and any(
        marker in detail.lower()
        for marker in ("safety", "policy", "moderation", "content filter")
    ):
        raise ContentPolicyError("图片请求被内容安全策略拒绝", **kwargs)
    raise ProviderResponseError(
        f"图片 Provider HTTP {status}",
        status_code=status,
        **kwargs,
    )


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: JsonObject | None,
    timeout: HttpTimeout,
) -> JsonObject:
    """Send JSON while classifying provider errors without exposing headers."""
    started = time.perf_counter()
    limits = httpx.Timeout(
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
            timeout=limits,
        )
    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        raise ImageModelConnectionError(
            "无法连接图片 Provider",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    except httpx.TimeoutException as exc:
        raise ProviderTimeoutError(
            f"图片 Provider 超时（上限 {timeout.read:g} 秒）",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    except httpx.RequestError as exc:
        raise ImageModelConnectionError(
            "图片 Provider 网络请求失败",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    elapsed = time.perf_counter() - started
    if response.is_error:
        _raise_http_error(response, elapsed)
    try:
        parsed = response.json()
    except ValueError as exc:
        raise ProviderResponseError(
            "图片 Provider 返回了无效 JSON",
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderResponseError("图片 Provider 返回的 JSON 不是对象")
    return parsed


def request_multipart(
    url: str,
    headers: dict[str, str],
    data: dict[str, str],
    files: list[tuple[str, tuple[str, bytes, str]]],
    timeout: HttpTimeout,
) -> JsonObject:
    """Send an image-edit multipart request with the same error taxonomy."""
    started = time.perf_counter()
    limits = httpx.Timeout(
        connect=timeout.connect,
        read=timeout.read,
        write=timeout.read,
        pool=timeout.connect,
    )
    try:
        response = httpx.post(
            url,
            headers={"Accept": "application/json", **headers},
            data=data,
            files=files,
            timeout=limits,
        )
    except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
        raise ImageModelConnectionError(
            "无法连接图片编辑 Provider",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    except httpx.TimeoutException as exc:
        raise ProviderTimeoutError(
            f"图片编辑超时（上限 {timeout.read:g} 秒）",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    except httpx.RequestError as exc:
        raise ImageModelConnectionError(
            "图片编辑网络请求失败",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    elapsed = time.perf_counter() - started
    if response.is_error:
        _raise_http_error(response, elapsed)
    try:
        parsed = response.json()
    except ValueError as exc:
        raise ProviderResponseError("图片编辑接口返回了无效 JSON") from exc
    if not isinstance(parsed, dict):
        raise ProviderResponseError("图片编辑接口返回的 JSON 不是对象")
    return parsed


def download_image(url: str, timeout: HttpTimeout, max_bytes: int) -> bytes:
    """Download only image content and enforce a hard byte limit."""
    started = time.perf_counter()
    limits = httpx.Timeout(
        connect=timeout.connect,
        read=timeout.read,
        write=timeout.connect,
        pool=timeout.connect,
    )
    try:
        with httpx.stream("GET", url, timeout=limits) as response:
            if response.is_error:
                raise ImageDownloadError(
                    f"图片下载失败（状态码 {response.status_code}）"
                )
            content_type = response.headers.get("content-type", "").split(";")[0]
            if not content_type.startswith("image/"):
                raise ImageDownloadError(
                    f"图片下载返回了非图片 Content-Type：{content_type or '未知'}"
                )
            declared = response.headers.get("content-length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise ImageDownloadError("图片下载 Content-Length 无效") from exc
                if declared_size > max_bytes:
                    raise ImageDownloadError("图片下载大小超过安全上限")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ImageDownloadError("图片下载大小超过安全上限")
                chunks.append(chunk)
            return b"".join(chunks)
    except ImageDownloadError:
        raise
    except httpx.TimeoutException as exc:
        raise ImageDownloadError(
            "图片下载超时",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc
    except httpx.RequestError as exc:
        raise ImageDownloadError(
            "图片下载连接失败",
            elapsed_seconds=time.perf_counter() - started,
            original_exception=exc,
        ) from exc


def decode_image_bytes(data: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            return source.convert("RGBA" if source.mode == "RGBA" else "RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidGeneratedImageError("Provider 返回内容不是有效图片") from exc


def image_bytes_from_entry(
    entry: dict[str, Any],
    *,
    downloader: DownloadTransport,
    timeout: HttpTimeout,
    max_bytes: int,
) -> bytes:
    encoded = entry.get("b64_json") or entry.get("b64") or entry.get("base64")
    if isinstance(encoded, str) and encoded:
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageDecodeError("Provider 返回的 base64 图片无法解码") from exc
    url = entry.get("url")
    if isinstance(url, str) and url:
        return downloader(url, timeout, max_bytes)
    raise ProviderResponseError("图片结果中缺少 url 或 base64 数据")


def save_images(images: list[Image.Image], output_path: Path | None) -> list[Path]:
    if output_path is None:
        return []
    paths: list[Path] = []
    for index, image in enumerate(images, start=1):
        path = (
            output_path
            if index == 1
            else output_path.with_name(
                f"{output_path.stem}_variant_{index:02d}{output_path.suffix}"
            )
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, format="PNG")
        except OSError as exc:
            raise ImageSaveError(f"生成图片保存失败：{path.name}") from exc
        paths.append(path)
    return paths


def normalized_result(
    *,
    provider: str,
    provider_name: str,
    model: str,
    operation: str,
    payload: JsonObject,
    entries: list[dict[str, Any]],
    duration: float,
    output_path: Path | None,
    downloader: DownloadTransport,
    timeout: HttpTimeout,
    max_bytes: int,
    actual_parameters: dict[str, Any],
    seed: int | None = None,
    request_id: str = "",
) -> ImageGenerationResult:
    if not entries:
        raise ProviderResponseError("Provider 没有返回任何图片")
    images = [
        decode_image_bytes(
            image_bytes_from_entry(
                entry,
                downloader=downloader,
                timeout=timeout,
                max_bytes=max_bytes,
            )
        )
        for entry in entries
    ]
    paths = save_images(images, output_path)
    raw_metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"data", "images", "output", "artifacts"}
    }
    return ImageGenerationResult(
        images=images,
        provider=provider,
        provider_name=provider_name,
        model=model,
        operation=operation,
        request_id=request_id,
        seed=seed,
        revised_prompt=str(payload.get("revised_prompt", "")),
        duration=duration,
        actual_parameters=actual_parameters,
        raw_metadata=raw_metadata,
        errors=[],
        output_paths=paths,
    )


def should_retry(error: ImageModelError) -> bool:
    if isinstance(error, (AuthenticationError, InsufficientBalanceError, ContentPolicyError)):
        return False
    if isinstance(
        error,
        (RateLimitError, ProviderTimeoutError, ImageModelConnectionError),
    ):
        return True
    if isinstance(error, ImageModelHttpError):
        return error.status_code >= 500 or error.status_code == 429
    if isinstance(error, ProviderResponseError):
        return bool(error.status_code and error.status_code >= 500)
    return isinstance(error, ImageModelRequestError)


def with_retry(
    operation: Callable[[], JsonObject],
    policy: RetryPolicy,
    *,
    sleeper: Sleeper = time.sleep,
) -> tuple[JsonObject, int]:
    """Retry only transient errors with bounded exponential backoff."""
    for attempt in range(policy.max_retries + 1):
        try:
            return operation(), attempt
        except ImageModelError as exc:
            if attempt >= policy.max_retries or not should_retry(exc):
                raise
            delay = min(policy.max_delay, policy.base_delay * (2**attempt))
            sleeper(delay)
    raise ProviderResponseError("图片 Provider 重试流程异常结束")
