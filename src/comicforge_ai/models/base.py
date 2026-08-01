"""Unified text-model interfaces and errors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from comicforge_ai.prompts import (
    build_comic_generation_messages,
    build_json_repair_messages,
)
from comicforge_ai.schemas import ComicProject


class TextModelError(RuntimeError):
    """Base class for user-presentable text-model failures."""


class TextModelConfigurationError(TextModelError):
    """Raised when required provider settings are missing."""


class TextModelRequestError(TextModelError):
    """Base request failure retaining safe diagnostics for UI and logs."""

    def __init__(
        self,
        message: str,
        *,
        elapsed_seconds: float | None = None,
        original_exception: BaseException | None = None,
    ) -> None:
        self.message = message
        self.elapsed_seconds = elapsed_seconds
        self.original_exception = original_exception
        diagnostics: list[str] = []
        if elapsed_seconds is not None:
            diagnostics.append(f"耗时 {elapsed_seconds:.2f} 秒")
        if original_exception is not None:
            diagnostics.append(
                "原始异常："
                f"{type(original_exception).__name__}: {original_exception}"
            )
        suffix = f"（{'；'.join(diagnostics)}）" if diagnostics else ""
        super().__init__(message + suffix)


class TextModelConnectionError(TextModelRequestError):
    """Raised when the model service cannot be reached or connected in time."""


class TextModelGenerationTimeoutError(TextModelRequestError):
    """Raised when a connected model exceeds the configured generation timeout."""


class TextModelHttpError(TextModelRequestError):
    """Raised for a non-success HTTP response."""

    def __init__(
        self,
        status_code: int,
        detail: str = "",
        *,
        elapsed_seconds: float | None = None,
        original_exception: BaseException | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        message = f"HTTP 请求失败（状态码 {status_code}）"
        if detail:
            message += f"：{detail}"
        super().__init__(
            message,
            elapsed_seconds=elapsed_seconds,
            original_exception=original_exception,
        )


class TextModelNotFoundError(TextModelRequestError):
    """Raised when the configured model does not exist on the service."""


class TextModelOutputError(TextModelError):
    """Raised when a model response cannot become a valid project."""


@dataclass(frozen=True, slots=True)
class TextModelStatus:
    """Availability result suitable for service and UI layers."""

    model_id: str
    display_name: str
    provider_type: str
    model_name: str
    configured: bool
    available: bool
    message: str


class TextModelProvider(ABC):
    """Common contract implemented by Mock and every real text provider."""

    model_id: str
    display_name: str
    provider_type: str

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the configured model name without exposing credentials."""

    @abstractmethod
    def check_availability(self) -> TextModelStatus:
        """Check configuration and connectivity without generating a project."""

    @abstractmethod
    def generate_project(
        self,
        theme: str,
        style: str,
        panel_count: int,
    ) -> ComicProject:
        """Generate a validated project or raise ``TextModelError``."""


class RemoteTextModelProvider(TextModelProvider, ABC):
    """Shared JSON generation and limited repair loop for HTTP providers."""

    def __init__(self, *, max_retries: int = 1) -> None:
        self.max_retries = max(0, max_retries)

    def generate_project(
        self,
        theme: str,
        style: str,
        panel_count: int,
    ) -> ComicProject:
        from comicforge_ai.models.parsing import parse_comic_project

        clean_theme = theme.strip()
        clean_style = style.strip()
        if not clean_theme:
            raise TextModelOutputError("请输入漫画主题")
        if not clean_style:
            raise TextModelOutputError("请输入漫画风格")
        if panel_count < 1:
            raise TextModelOutputError("漫画格数必须是正整数")

        status = self._configuration_status()
        if not status.configured:
            raise TextModelConfigurationError(status.message)

        messages = build_comic_generation_messages(
            clean_theme, clean_style, panel_count
        )
        last_error: TextModelOutputError | None = None
        for attempt in range(self.max_retries + 1):
            raw_output = self._chat(messages)
            try:
                return parse_comic_project(
                    raw_output,
                    theme=clean_theme,
                    style=clean_style,
                    panel_count=panel_count,
                )
            except TextModelOutputError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                messages = build_json_repair_messages(
                    raw_output,
                    str(exc),
                    clean_theme,
                    clean_style,
                    panel_count,
                )
        raise TextModelOutputError(
            f"{self.display_name} 返回内容无法解析：{last_error}"
        ) from last_error

    @abstractmethod
    def _configuration_status(self) -> TextModelStatus:
        """Return a status based only on local configuration."""

    @abstractmethod
    def _chat(self, messages: list[dict[str, str]]) -> str:
        """Return assistant message text from a provider HTTP request."""
