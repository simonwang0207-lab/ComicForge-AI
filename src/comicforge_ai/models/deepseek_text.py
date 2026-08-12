"""Official DeepSeek Chat Completions provider."""

from __future__ import annotations

from typing import Any

from comicforge_ai.models.base import TextModelStatus
from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.openai_compatible_text import OpenAICompatibleTextModel


class DeepSeekTextModel(OpenAICompatibleTextModel):
    """Use DeepSeek's official OpenAI-compatible API as a named provider."""

    model_id = "deepseek"
    display_name = "DeepSeek API"
    provider_type = "remote_http"

    def _configuration_status(self) -> TextModelStatus:
        missing = tuple(
            name
            for name, value in (
                ("DEEPSEEK_BASE_URL", self.base_url),
                ("DEEPSEEK_API_KEY", self.api_key),
                ("DEEPSEEK_MODEL", self._model_name),
            )
            if not value
        )
        configured = not missing
        return TextModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=configured,
            available=False,
            message=(
                "配置已读取，尚未检测 DeepSeek 服务。"
                if configured
                else "未配置：" + "、".join(missing)
            ),
        )

    def _chat_response(
        self,
        request_messages: list[dict[str, str]],
        max_tokens: int,
        read_timeout: float | None = None,
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Disable thinking for faster, more deterministic project JSON."""
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": request_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
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
