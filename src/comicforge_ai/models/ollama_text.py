"""Ollama text provider using the local HTTP API."""

from __future__ import annotations

import logging
import time
from typing import Any

from comicforge_ai.models.base import (
    RemoteTextModelProvider,
    TextModelHttpError,
    TextModelNotFoundError,
    TextModelRequestError,
    TextModelStatus,
)
from comicforge_ai.models.http import HttpTimeout, HttpTransport, request_json
from comicforge_ai.prompts import add_no_think_directive

logger = logging.getLogger(__name__)


class OllamaTextModel(RemoteTextModelProvider):
    """Generate comic plans through an optional local Ollama service."""

    model_id = "ollama"
    display_name = "Ollama 本地模型"
    provider_type = "local_http"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        connect_timeout: float = 10,
        generation_timeout: float = 300,
        status_timeout: float = 10,
        timeout: float | None = None,
        max_retries: int = 1,
        transport: HttpTransport = request_json,
    ) -> None:
        super().__init__(max_retries=max_retries)
        self.base_url = base_url.strip().rstrip("/")
        self._model_name = model.strip()
        # ``timeout`` is retained for callers from version 0.2.0. New code should
        # configure the separate connection and generation limits.
        if timeout is not None:
            generation_timeout = timeout
        self.connect_timeout = max(0.1, connect_timeout)
        self.generation_timeout = max(0.1, generation_timeout)
        self.status_timeout = max(0.1, status_timeout)
        self.transport = transport
        self.last_request_elapsed_seconds: float | None = None
        self.last_thinking_control = "not_requested"

    @property
    def model_name(self) -> str:
        return self._model_name or "未配置"

    def _configuration_status(self) -> TextModelStatus:
        missing: list[str] = []
        if not self.base_url:
            missing.append("OLLAMA_BASE_URL")
        if not self._model_name:
            missing.append("OLLAMA_MODEL")
        configured = not missing
        message = (
            "配置已读取，尚未检测服务。"
            if configured
            else "未配置：" + "、".join(missing)
        )
        return TextModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=configured,
            available=False,
            message=message,
        )

    def check_availability(self) -> TextModelStatus:
        configured = self._configuration_status()
        if not configured.configured:
            return configured
        try:
            started = time.perf_counter()
            response = self.transport(
                "GET",
                f"{self.base_url}/api/tags",
                {},
                None,
                HttpTimeout(
                    connect=self.connect_timeout,
                    read=self.status_timeout,
                ),
            )
            elapsed = time.perf_counter() - started
            models = response.get("models", [])
            names = {
                item.get("name")
                for item in models
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            available = self._model_name in names
            message = (
                f"Ollama 服务和模型均可用（检测耗时 {elapsed:.2f} 秒）。"
                if available
                else (
                    f"Ollama 服务已连接，但未找到模型 {self._model_name}"
                    f"（检测耗时 {elapsed:.2f} 秒）。"
                )
            )
        except TextModelRequestError as exc:
            available = False
            message = f"Ollama 不可用：{exc}"
        return TextModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=True,
            available=available,
            message=message,
        )

    def _chat(self, messages: list[dict[str, str]]) -> str:
        self.last_thinking_control = "api_think_false"
        try:
            response = self._send_chat(messages, include_think=False)
        except TextModelHttpError as exc:
            if self._is_model_not_found(exc):
                raise self._model_not_found_error(exc) from exc
            if not self._is_think_unsupported(exc):
                raise
            logger.warning(
                "Ollama API does not support think=false; retrying with /no_think: "
                "model=%s elapsed=%.2fs original_exception=%r",
                self._model_name,
                self.last_request_elapsed_seconds or 0,
                exc.original_exception or exc,
            )
            self.last_thinking_control = "prompt_no_think"
            try:
                response = self._send_chat(
                    add_no_think_directive(messages),
                    include_think=None,
                )
            except TextModelHttpError as retry_exc:
                if self._is_model_not_found(retry_exc):
                    raise self._model_not_found_error(retry_exc) from retry_exc
                raise
        message: Any = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise TextModelRequestError("Ollama 响应中缺少 message.content")
        return content

    def _send_chat(
        self,
        messages: list[dict[str, str]],
        *,
        include_think: bool | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.7},
        }
        if include_think is not None:
            payload["think"] = include_think

        started = time.perf_counter()
        try:
            response = self.transport(
                "POST",
                f"{self.base_url}/api/chat",
                {},
                payload,
                HttpTimeout(
                    connect=self.connect_timeout,
                    read=self.generation_timeout,
                ),
            )
        except TextModelRequestError as exc:
            self.last_request_elapsed_seconds = (
                exc.elapsed_seconds
                if exc.elapsed_seconds is not None
                else time.perf_counter() - started
            )
            raise
        self.last_request_elapsed_seconds = time.perf_counter() - started
        logger.info(
            "Ollama generation request completed: model=%s elapsed=%.2fs "
            "thinking_control=%s",
            self._model_name,
            self.last_request_elapsed_seconds,
            self.last_thinking_control,
        )
        return response

    @staticmethod
    def _is_think_unsupported(exc: TextModelHttpError) -> bool:
        if exc.status_code not in {400, 422}:
            return False
        detail = exc.detail.lower()
        return any(
            marker in detail
            for marker in ("think", "unknown field", "unsupported", "invalid option")
        )

    @staticmethod
    def _is_model_not_found(exc: TextModelHttpError) -> bool:
        detail = exc.detail.lower()
        return exc.status_code == 404 or (
            "model" in detail and any(word in detail for word in ("not found", "missing"))
        )

    def _model_not_found_error(
        self, exc: TextModelHttpError
    ) -> TextModelNotFoundError:
        return TextModelNotFoundError(
            f"Ollama 模型不存在：{self._model_name}。请先执行 ollama pull。",
            elapsed_seconds=exc.elapsed_seconds,
            original_exception=exc.original_exception or exc,
        )
