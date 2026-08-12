"""Ollama text provider using the local HTTP API."""

from __future__ import annotations

import logging
import time
from typing import Any

from comicforge_ai.models.base import (
    RemoteTextModelProvider,
    TextModelHttpError,
    TextModelNotFoundError,
    TextModelOutputError,
    TextModelRequestError,
    TextModelResourceReleaseStatus,
    TextModelStatus,
)
from comicforge_ai.models.http import HttpTimeout, HttpTransport, request_json
from comicforge_ai.prompts import (
    add_no_think_directive,
    add_truncation_retry_directive,
)

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
        review_timeout: float = 90,
        status_timeout: float = 10,
        num_predict: int = 4096,
        num_ctx: int = 8192,
        timeout: float | None = None,
        max_retries: int = 1,
        language_repair_attempts: int = 2,
        transport: HttpTransport = request_json,
    ) -> None:
        super().__init__(
            max_retries=max_retries,
            language_repair_attempts=language_repair_attempts,
        )
        self.base_url = base_url.strip().rstrip("/")
        self._model_name = model.strip()
        # ``timeout`` is retained for callers from version 0.2.0. New code should
        # configure the separate connection and generation limits.
        if timeout is not None:
            generation_timeout = timeout
        self.connect_timeout = max(0.1, connect_timeout)
        self.generation_timeout = max(0.1, generation_timeout)
        self.review_timeout = max(0.1, review_timeout)
        self.status_timeout = max(0.1, status_timeout)
        self.num_predict = max(1024, int(num_predict))
        self.num_ctx = max(4096, int(num_ctx))
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

    def release_resources(self) -> TextModelResourceReleaseStatus:
        """Ask Ollama to unload this model without disrupting the workflow."""
        if not self.base_url or not self._model_name:
            return TextModelResourceReleaseStatus(
                attempted=False,
                released=False,
                message="Ollama 未配置，无需释放显存",
            )
        started = time.perf_counter()
        try:
            self.transport(
                "POST",
                f"{self.base_url}/api/generate",
                {},
                {
                    "model": self._model_name,
                    "keep_alive": 0,
                    "stream": False,
                },
                HttpTimeout(
                    connect=self.connect_timeout,
                    read=self.status_timeout,
                ),
            )
        except TextModelRequestError as exc:
            elapsed = time.perf_counter() - started
            logger.warning(
                "Unable to release Ollama model resources: model=%s "
                "elapsed=%.2fs exception_type=%s",
                self._model_name,
                elapsed,
                type(exc).__name__,
            )
            return TextModelResourceReleaseStatus(
                attempted=True,
                released=False,
                message=f"Ollama 显存释放失败：{type(exc).__name__}",
                elapsed_seconds=elapsed,
            )
        elapsed = time.perf_counter() - started
        logger.info(
            "Ollama model resources released: model=%s elapsed=%.2fs",
            self._model_name,
            elapsed,
        )
        return TextModelResourceReleaseStatus(
            attempted=True,
            released=True,
            message=f"已释放 Ollama 模型 {self._model_name} 的显存占用",
            elapsed_seconds=elapsed,
        )

    def _chat(self, messages: list[dict[str, str]]) -> str:
        return self._chat_with_timeout(messages, self.generation_timeout)

    def _chat_for_review(self, messages: list[dict[str, str]]) -> str:
        return self._chat_with_timeout(messages, self.review_timeout)

    def _chat_for_repair(self, messages: list[dict[str, str]]) -> str:
        return self._chat_with_timeout(
            messages,
            min(self.review_timeout, self.generation_timeout),
            num_predict=min(self.num_predict, 1024),
            temperature=0.0,
        )

    def _chat_with_timeout(
        self,
        messages: list[dict[str, str]],
        read_timeout: float,
        *,
        num_predict: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.last_thinking_control = "api_think_false"
        try:
            response = self._send_chat(
                messages,
                include_think=False,
                num_predict=num_predict,
                temperature=temperature,
                read_timeout=read_timeout,
            )
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
                    num_predict=num_predict,
                    temperature=temperature,
                    read_timeout=read_timeout,
                )
            except TextModelHttpError as retry_exc:
                if self._is_model_not_found(retry_exc):
                    raise self._model_not_found_error(retry_exc) from retry_exc
                raise
        if str(response.get("done_reason", "")).lower() == "length":
            retry_num_predict = max(
                num_predict or self.num_predict,
                min((num_predict or self.num_predict) * 2, 16384),
            )
            retry_num_ctx = max(self.num_ctx, retry_num_predict * 2)
            retry_messages = add_truncation_retry_directive(messages)
            include_think: bool | None = False
            if self.last_thinking_control == "prompt_no_think":
                retry_messages = add_no_think_directive(retry_messages)
                include_think = None
            logger.warning(
                "Ollama output was truncated; retrying from clean context: "
                "model=%s num_predict=%d num_ctx=%d elapsed=%.2fs",
                self._model_name,
                retry_num_predict,
                retry_num_ctx,
                self.last_request_elapsed_seconds or 0,
            )
            response = self._send_chat(
                retry_messages,
                include_think=include_think,
                num_predict=retry_num_predict,
                num_ctx=retry_num_ctx,
                temperature=temperature,
                read_timeout=read_timeout,
            )
            if str(response.get("done_reason", "")).lower() == "length":
                raise TextModelOutputError(
                    "Ollama 输出达到长度上限；系统已自动扩大预算重试，但仍被截断。"
                    "请提高 OLLAMA_NUM_PREDICT/OLLAMA_NUM_CTX，或缩短故事说明后重试。"
                )
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
        num_predict: int | None = None,
        num_ctx: int | None = None,
        temperature: float = 0.2,
        read_timeout: float | None = None,
    ) -> dict[str, Any]:
        actual_num_predict = num_predict or self.num_predict
        actual_num_ctx = num_ctx or self.num_ctx
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_predict": actual_num_predict,
                "num_ctx": actual_num_ctx,
            },
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
                    read=read_timeout or self.generation_timeout,
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
