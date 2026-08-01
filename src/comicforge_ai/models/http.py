"""Small httpx-based JSON transport with split connection/read timeouts."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from comicforge_ai.models.base import (
    TextModelConnectionError,
    TextModelGenerationTimeoutError,
    TextModelHttpError,
    TextModelRequestError,
)

logger = logging.getLogger(__name__)
JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class HttpTimeout:
    """Separate limits for establishing a connection and reading a response."""

    connect: float = 10
    read: float = 300


HttpTransport = Callable[
    [str, str, dict[str, str], JsonObject | None, HttpTimeout], JsonObject
]


def _safe_http_error_detail(response: httpx.Response) -> str:
    """Return only a short structured error message, never the full body."""
    try:
        payload = response.json()
    except ValueError:
        return response.reason_phrase[:300]
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message") or payload.get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("type")
        if isinstance(detail, str):
            return detail[:500]
    return response.reason_phrase[:300]


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: JsonObject | None,
    timeout: HttpTimeout,
) -> JsonObject:
    """Send one JSON request while retaining timing and original exceptions."""
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
        logger.warning(
            "Model connection failed: method=%s url=%s elapsed=%.2fs exception=%r",
            method,
            url,
            elapsed,
            exc,
        )
        message = (
            f"连接模型服务超时（连接上限 {timeout.connect:g} 秒）"
            if isinstance(exc, httpx.ConnectTimeout)
            else "无法连接模型服务"
        )
        raise TextModelConnectionError(
            message,
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
        elapsed = time.perf_counter() - started
        logger.warning(
            "Model generation timed out: method=%s url=%s elapsed=%.2fs exception=%r",
            method,
            url,
            elapsed,
            exc,
        )
        raise TextModelGenerationTimeoutError(
            f"模型生成超时（读取上限 {timeout.read:g} 秒）",
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc
    except httpx.RequestError as exc:
        elapsed = time.perf_counter() - started
        logger.warning(
            "Model request failed: method=%s url=%s elapsed=%.2fs exception=%r",
            method,
            url,
            elapsed,
            exc,
        )
        raise TextModelConnectionError(
            "模型服务请求失败",
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc

    elapsed = time.perf_counter() - started
    if response.is_error:
        detail = _safe_http_error_detail(response)
        original = httpx.HTTPStatusError(
            f"HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
        logger.warning(
            "Model HTTP error: method=%s url=%s status=%s elapsed=%.2fs exception=%r",
            method,
            url,
            response.status_code,
            elapsed,
            original,
        )
        raise TextModelHttpError(
            response.status_code,
            detail,
            elapsed_seconds=elapsed,
            original_exception=original,
        )

    try:
        parsed = response.json()
    except ValueError as exc:
        logger.warning(
            "Invalid model HTTP JSON: method=%s url=%s elapsed=%.2fs exception=%r",
            method,
            url,
            elapsed,
            exc,
        )
        raise TextModelRequestError(
            "模型服务返回了无效的 HTTP JSON",
            elapsed_seconds=elapsed,
            original_exception=exc,
        ) from exc
    if not isinstance(parsed, dict):
        raise TextModelRequestError(
            "模型服务返回的 HTTP JSON 不是对象",
            elapsed_seconds=elapsed,
        )
    logger.info(
        "Model HTTP request completed: method=%s url=%s status=%s elapsed=%.2fs",
        method,
        url,
        response.status_code,
        elapsed,
    )
    return parsed
