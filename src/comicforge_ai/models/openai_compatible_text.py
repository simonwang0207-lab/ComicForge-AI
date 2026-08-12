"""Provider for OpenAI-compatible Chat Completions endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

from comicforge_ai.models.base import (
    RemoteTextModelProvider,
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


class OpenAICompatibleTextModel(RemoteTextModelProvider):
    """Use any configured OpenAI-compatible Chat Completions service."""

    model_id = "openai-compatible"
    display_name = "OpenAI-compatible API"
    provider_type = "remote_http"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        connect_timeout: float = 10,
        generation_timeout: float = 300,
        review_timeout: float = 90,
        status_timeout: float = 10,
        timeout: float | None = None,
        max_retries: int = 1,
        language_repair_attempts: int = 2,
        max_tokens: int = 4096,
        max_retry_tokens: int = 16384,
        disable_thinking: bool | None = None,
        reasoning_effort: str = "",
        transport: HttpTransport = request_json,
    ) -> None:
        super().__init__(
            max_retries=max_retries,
            language_repair_attempts=language_repair_attempts,
        )
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key.strip()
        self._model_name = model.strip()
        if timeout is not None:
            generation_timeout = timeout
        self.connect_timeout = max(0.1, connect_timeout)
        self.generation_timeout = max(0.1, generation_timeout)
        self.review_timeout = max(0.1, review_timeout)
        self.status_timeout = max(0.1, status_timeout)
        self.max_tokens = max(256, int(max_tokens))
        self.max_retry_tokens = max(self.max_tokens, int(max_retry_tokens))
        self.disable_thinking = (
            "qwen3" in self._model_name.lower()
            if disable_thinking is None
            else disable_thinking
        )
        configured_effort = reasoning_effort.strip().lower()
        if configured_effort not in {"", "none", "low", "medium", "high"}:
            configured_effort = ""
        if (
            not configured_effort
            and self.disable_thinking
            and self._looks_like_ollama_compatibility()
        ):
            configured_effort = "none"
        self.reasoning_effort = configured_effort
        self.transport = transport

    @property
    def model_name(self) -> str:
        return self._model_name or "未配置"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _configuration_status(self) -> TextModelStatus:
        missing: list[str] = []
        if not self.base_url:
            missing.append("OPENAI_COMPATIBLE_BASE_URL")
        if not self.api_key:
            missing.append("OPENAI_COMPATIBLE_API_KEY")
        if not self._model_name:
            missing.append("OPENAI_COMPATIBLE_MODEL")
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
            response = self.transport(
                "GET",
                self._endpoint("models"),
                self._headers,
                None,
                HttpTimeout(
                    connect=self.connect_timeout,
                    read=self.status_timeout,
                ),
            )
            data = response.get("data")
            if isinstance(data, list):
                names = {
                    item.get("id")
                    for item in data
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
                available = not names or self._model_name in names
                message = (
                    "API 服务和模型均可用。"
                    if available
                    else f"API 已连接，但未找到模型 {self._model_name}。"
                )
            else:
                available = True
                message = "API 服务可连接；模型列表格式非标准，将在生成时验证模型。"
        except TextModelRequestError as exc:
            available = False
            message = f"OpenAI-compatible API 不可用：{exc}"
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
        """Unload a model only when this compatibility URL is local Ollama."""
        if not self._looks_like_ollama_compatibility():
            return TextModelResourceReleaseStatus(
                attempted=False,
                released=False,
                message="该 OpenAI-compatible 服务不是本机 Ollama，无需释放显存",
            )
        if not self._model_name:
            return TextModelResourceReleaseStatus(
                attempted=False,
                released=False,
                message="OpenAI-compatible 模型未配置，无需释放显存",
            )
        parsed = urlparse(self.base_url)
        ollama_root = f"{parsed.scheme}://{parsed.netloc}"
        started = time.perf_counter()
        try:
            self.transport(
                "POST",
                f"{ollama_root}/api/generate",
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
                "Unable to release OpenAI-compatible Ollama resources: "
                "model=%s elapsed=%.2fs exception_type=%s",
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
            "OpenAI-compatible Ollama resources released: model=%s elapsed=%.2fs",
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
            max_tokens=min(self.max_tokens, 1024),
            temperature=0.0,
        )

    def _chat_with_timeout(
        self,
        messages: list[dict[str, str]],
        read_timeout: float,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        request_messages = (
            add_no_think_directive(messages)
            if self.disable_thinking
            else [message.copy() for message in messages]
        )
        request_max_tokens = max_tokens or self.max_tokens
        response = self._chat_response(
            request_messages,
            request_max_tokens,
            read_timeout,
            temperature=temperature,
        )
        if self._response_was_truncated(response):
            retry_max_tokens = min(
                max(request_max_tokens * 2, 2048),
                self.max_retry_tokens,
            )
            retry_messages = add_truncation_retry_directive(messages)
            if self.disable_thinking:
                retry_messages = add_no_think_directive(retry_messages)
            logger.warning(
                "OpenAI-compatible output was truncated; retrying from clean "
                "context: model=%s max_tokens=%d",
                self._model_name,
                retry_max_tokens,
            )
            response = self._chat_response(
                retry_messages,
                retry_max_tokens,
                read_timeout,
                temperature=temperature,
            )
            if self._response_was_truncated(response):
                raise TextModelOutputError(
                    "OpenAI-compatible 输出连续两次达到长度上限。请提高 "
                    "OPENAI_COMPATIBLE_MAX_TOKENS，减少分镜数量，或缩短故事原文。"
                )
        return self._response_content(response)

    def _chat_response(
        self,
        request_messages: list[dict[str, str]],
        max_tokens: int,
        read_timeout: float | None = None,
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": request_messages,
            # Structured project JSON benefits from deterministic output.
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return self.transport(
            "POST",
            self._endpoint("chat/completions"),
            self._headers,
            payload,
            HttpTimeout(
                connect=self.connect_timeout,
                read=read_timeout or self.generation_timeout,
            ),
        )

    @staticmethod
    def _response_was_truncated(response: dict[str, Any]) -> bool:
        choices: Any = response.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        return isinstance(first, dict) and first.get("finish_reason") == "length"

    @staticmethod
    def _response_content(response: dict[str, Any]) -> str:
        choices: Any = response.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise TextModelRequestError(
                "Chat Completions 响应中缺少 choices[0].message.content"
            )
        return content

    def _endpoint(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _looks_like_ollama_compatibility(self) -> bool:
        parsed = urlparse(self.base_url)
        return parsed.port == 11434 and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
