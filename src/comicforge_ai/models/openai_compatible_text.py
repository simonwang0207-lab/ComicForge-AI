"""Provider for OpenAI-compatible Chat Completions endpoints."""

from __future__ import annotations

from typing import Any

from comicforge_ai.models.base import (
    RemoteTextModelProvider,
    TextModelRequestError,
    TextModelStatus,
)
from comicforge_ai.models.http import HttpTimeout, HttpTransport, request_json


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
        status_timeout: float = 10,
        timeout: float | None = None,
        max_retries: int = 1,
        transport: HttpTransport = request_json,
    ) -> None:
        super().__init__(max_retries=max_retries)
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key.strip()
        self._model_name = model.strip()
        if timeout is not None:
            generation_timeout = timeout
        self.connect_timeout = max(0.1, connect_timeout)
        self.generation_timeout = max(0.1, generation_timeout)
        self.status_timeout = max(0.1, status_timeout)
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

    def _chat(self, messages: list[dict[str, str]]) -> str:
        response = self.transport(
            "POST",
            self._endpoint("chat/completions"),
            self._headers,
            {
                "model": self._model_name,
                "messages": messages,
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
            },
            HttpTimeout(
                connect=self.connect_timeout,
                read=self.generation_timeout,
            ),
        )
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
