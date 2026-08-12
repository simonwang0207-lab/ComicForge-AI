"""Unified text-model interfaces and errors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from comicforge_ai.prompts import (
    build_comic_generation_messages,
    build_comic_translation_messages,
    build_comic_translation_repair_messages,
    build_json_repair_messages,
    build_review_repair_messages,
    build_story_guidance_repair_messages,
    build_story_guidance_revision_messages,
    build_story_review_messages,
    build_visible_text_language_repair_messages,
)
from comicforge_ai.schemas import ComicProject, ContentLanguage, LayoutMode

logger = logging.getLogger(__name__)


def _safe_identifier_summary(value: object) -> object:
    if isinstance(value, bool):
        return "<bool>"
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdecimal() and len(stripped) <= 8:
            return stripped
        return f"<str length={len(value)}>"
    return f"<{type(value).__name__}>"


def _safe_json_structure_summary(raw_output: str) -> str:
    """Describe response shape for terminal diagnostics without logging content."""
    from comicforge_ai.models.parsing import extract_json_object

    try:
        payload = extract_json_object(raw_output)
    except TextModelOutputError as exc:
        return f"json_error={exc}"

    top_keys = sorted(str(key)[:40] for key in payload)[:20]
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return f"top_keys={top_keys}; panels_type={type(panels).__name__}"

    panel_summaries: list[str] = []
    sequence_names = (
        "sequence", "index", "panel_index", "panel_number", "panel_no",
        "panel_id", "panel", "number", "序号", "格号", "分格序号",
        "分镜序号",
    )
    for index, panel in enumerate(panels[:12]):
        if not isinstance(panel, dict):
            panel_summaries.append(f"{index}:type={type(panel).__name__}")
            continue
        keys = sorted(str(key)[:40] for key in panel)[:20]
        sequence_fields = {
            name: _safe_identifier_summary(panel[name])
            for name in sequence_names
            if name in panel
        }
        texts = next(
            (
                panel[name]
                for name in ("texts", "text_items", "items", "文字", "修复文字")
                if name in panel
            ),
            None,
        )
        texts_shape = (
            f"list[{len(texts)}]"
            if isinstance(texts, list)
            else type(texts).__name__
        )
        panel_summaries.append(
            f"{index}:keys={keys},sequence_fields={sequence_fields},"
            f"texts={texts_shape}"
        )
    return (
        f"top_keys={top_keys}; panel_count={len(panels)}; "
        f"panels=[{' | '.join(panel_summaries)}]"
    )


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


class VisibleTextLanguageError(TextModelOutputError):
    """A structurally valid draft contains lettering in the wrong language."""

    def __init__(
        self,
        message: str,
        *,
        project: ComicProject,
        panel_sequences: tuple[int, ...],
        text_indexes: tuple[tuple[int, int], ...],
    ) -> None:
        self.project = project
        self.panel_sequences = panel_sequences
        self.text_indexes = text_indexes
        super().__init__(message)


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


@dataclass(frozen=True, slots=True)
class TextModelResourceReleaseStatus:
    """Best-effort result from releasing a local text model's resources."""

    attempted: bool
    released: bool
    message: str
    elapsed_seconds: float = 0


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

    def configuration_status(self) -> TextModelStatus:
        """Return configuration state without requiring a network request.

        Providers that can separate local configuration from connectivity should
        override this method. Offline providers may safely reuse their normal
        availability result.
        """
        return self.check_availability()

    @abstractmethod
    def generate_project(
        self,
        theme: str,
        style: str,
        panel_count: int,
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "grid",
        allow_multi_shot_panels: bool = False,
        source_story: str = "",
    ) -> ComicProject:
        """Generate a validated project or raise ``TextModelError``."""

    def generate_reviewed_project(
        self,
        theme: str,
        style: str,
        panel_count: int,
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "grid",
        allow_multi_shot_panels: bool = False,
        source_story: str = "",
    ) -> ComicProject:
        """Generate and review a script before any image Provider is called."""
        project = self.generate_project(
            theme,
            style,
            panel_count,
            language,
            layout_mode,
            allow_multi_shot_panels,
            source_story,
        )
        project.script_reviewed = True
        return project

    def review_project(self, project: ComicProject) -> ComicProject:
        """Review an existing draft; offline/default Providers accept it as-is."""
        reviewed = project.model_copy(deep=True)
        reviewed.script_reviewed = True
        return reviewed

    def revise_project_with_guidance(
        self,
        project: ComicProject,
        user_guidance: str,
    ) -> ComicProject:
        """Rebuild a complete script from authoritative user story details."""
        raise TextModelOutputError(
            f"{self.display_name} 暂不支持根据用户故事说明重做分镜"
        )

    def translate_project(
        self,
        project: ComicProject,
        target_language: ContentLanguage,
    ) -> ComicProject:
        """Translate visible lettering without generating or modifying images."""
        raise TextModelOutputError(f"{self.display_name} 暂不支持漫画文字翻译")

    def release_resources(self) -> TextModelResourceReleaseStatus:
        """Release optional local accelerator resources before image generation.

        Most Providers are remote or do not keep local weights resident, so the
        default implementation deliberately does nothing.
        """
        return TextModelResourceReleaseStatus(
            attempted=False,
            released=False,
            message=f"{self.display_name} 无需释放本机模型资源",
        )


class RemoteTextModelProvider(TextModelProvider, ABC):
    """Shared JSON generation and limited repair loop for HTTP providers."""

    def __init__(
        self,
        *,
        max_retries: int = 1,
        language_repair_attempts: int = 2,
    ) -> None:
        self.max_retries = max(0, max_retries)
        self.language_repair_attempts = max(0, language_repair_attempts)

    def configuration_status(self) -> TextModelStatus:
        """Expose the existing local-only configuration check to registries."""
        return self._configuration_status()

    def generate_project(
        self,
        theme: str,
        style: str,
        panel_count: int,
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "grid",
        allow_multi_shot_panels: bool = False,
        source_story: str = "",
    ) -> ComicProject:
        from comicforge_ai.models.parsing import (
            apply_visible_text_language_repair,
            parse_comic_project,
        )

        clean_theme = theme.strip()
        clean_style = style.strip()
        if not clean_theme:
            raise TextModelOutputError("请输入漫画主题")
        if not clean_style:
            raise TextModelOutputError("请输入漫画风格")
        if panel_count < 1:
            raise TextModelOutputError("漫画格数必须是正整数")
        clean_source_story = source_story.strip()
        if len(clean_source_story) > 20000:
            raise TextModelOutputError("故事或剧本原文不能超过 20000 个字符")

        status = self._configuration_status()
        if not status.configured:
            raise TextModelConfigurationError(status.message)

        messages = build_comic_generation_messages(
            clean_theme,
            clean_style,
            panel_count,
            language,
            layout_mode,
            allow_multi_shot_panels,
            clean_source_story,
        )
        last_error: TextModelOutputError | None = None
        for attempt in range(self.max_retries + 1):
            raw_output = self._chat(messages)
            try:
                project = parse_comic_project(
                    raw_output,
                    theme=clean_theme,
                    style=clean_style,
                    panel_count=panel_count,
                    language=language,
                    layout_mode=layout_mode,
                    allow_multi_shot_panels=allow_multi_shot_panels,
                    source_story=clean_source_story,
                )
                project.user_story_guidance = clean_source_story
                return project
            except VisibleTextLanguageError as exc:
                last_error = exc
                if self.language_repair_attempts == 0:
                    break
                repair_project = exc.project
                repair_indexes = exc.text_indexes
                repair_error: TextModelOutputError = exc
                for repair_attempt in range(1, self.language_repair_attempts + 1):
                    repair_output = self._chat_for_repair(
                        build_visible_text_language_repair_messages(
                            repair_project,
                            repair_indexes,
                        )
                    )
                    try:
                        project = apply_visible_text_language_repair(
                            repair_output,
                            repair_project,
                        )
                        project.user_story_guidance = clean_source_story
                        return project
                    except VisibleTextLanguageError as repair_exc:
                        # Keep any successfully localized items and request only
                        # the still-invalid indexes on the bounded next attempt.
                        logger.warning(
                            "Visible-text repair still has wrong-language items: "
                            "provider=%s model=%s attempt=%d/%d remaining=%s "
                            "response_structure=%s",
                            self.model_id,
                            self.model_name,
                            repair_attempt,
                            self.language_repair_attempts,
                            repair_exc.text_indexes,
                            _safe_json_structure_summary(repair_output),
                        )
                        repair_project = repair_exc.project
                        repair_indexes = repair_exc.text_indexes
                        repair_error = repair_exc
                    except TextModelOutputError as repair_exc:
                        logger.warning(
                            "Visible-text repair output rejected: provider=%s "
                            "model=%s attempt=%d/%d error=%s "
                            "response_structure=%s",
                            self.model_id,
                            self.model_name,
                            repair_attempt,
                            self.language_repair_attempts,
                            repair_exc,
                            _safe_json_structure_summary(repair_output),
                        )
                        repair_error = repair_exc
                last_error = TextModelOutputError(
                    "可见漫画文字专项修复已执行 "
                    f"{self.language_repair_attempts} 次但仍未通过校验："
                    f"{repair_error}"
                )
                break
            except TextModelOutputError as exc:
                logger.warning(
                    "Text project output rejected: provider=%s model=%s "
                    "attempt=%d/%d error=%s response_structure=%s",
                    self.model_id,
                    self.model_name,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                    _safe_json_structure_summary(raw_output),
                )
                last_error = exc
                if attempt >= self.max_retries:
                    break
                messages = build_json_repair_messages(
                    raw_output,
                    str(exc),
                    clean_theme,
                    clean_style,
                    panel_count,
                    language,
                    layout_mode,
                    allow_multi_shot_panels,
                    clean_source_story,
                )
        logger.error(
            "Text generation failed validation: provider=%s model=%s error=%s",
            self.model_id,
            self.model_name,
            last_error,
        )
        raise TextModelOutputError(
            f"{self.display_name} 返回内容无法解析：{last_error}"
        ) from last_error

    def translate_project(
        self,
        project: ComicProject,
        target_language: ContentLanguage,
    ) -> ComicProject:
        """Translate a small lettering-only JSON with one safe repair retry."""
        from comicforge_ai.models.parsing import parse_comic_translation

        if target_language == project.content_language:
            return project.model_copy(deep=True)
        messages = build_comic_translation_messages(project, target_language)
        last_error: TextModelOutputError | None = None
        for attempt in range(self.max_retries + 1):
            raw_output = self._chat(messages)
            try:
                return parse_comic_translation(
                    raw_output,
                    project,
                    target_language,
                )
            except TextModelOutputError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                messages = build_comic_translation_repair_messages(
                    project,
                    target_language,
                    str(exc),
                )
        raise TextModelOutputError(
            f"{self.display_name} 漫画文字翻译无法解析：{last_error}"
        ) from last_error

    def generate_reviewed_project(
        self,
        theme: str,
        style: str,
        panel_count: int,
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "grid",
        allow_multi_shot_panels: bool = False,
        source_story: str = "",
    ) -> ComicProject:
        """Generate a draft, then review/revise it through the same Provider."""
        draft = self.generate_project(
            theme,
            style,
            panel_count,
            language,
            layout_mode,
            allow_multi_shot_panels,
            source_story,
        )
        return self.review_project(draft)

    def review_project(self, project: ComicProject) -> ComicProject:
        """Review and revise a draft generated by any text Provider."""
        from comicforge_ai.models.parsing import parse_reviewed_project

        draft = project.model_copy(deep=True)
        messages = build_story_review_messages(draft)
        last_error: TextModelOutputError | None = None
        for attempt in range(self.max_retries + 1):
            raw_output = self._chat_for_review(messages)
            try:
                reviewed = parse_reviewed_project(raw_output, draft)
                reviewed.script_reviewed = True
                return reviewed
            except TextModelOutputError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                messages = build_review_repair_messages(
                    draft,
                    raw_output,
                    str(exc),
                )
        raise TextModelOutputError(
            f"{self.display_name} 修订稿无法解析：{last_error}"
        ) from last_error

    def revise_project_with_guidance(
        self,
        project: ComicProject,
        user_guidance: str,
    ) -> ComicProject:
        """Regenerate the whole storyboard from user-provided story facts."""
        from comicforge_ai.models.parsing import parse_reviewed_project

        clean_guidance = user_guidance.strip()
        if not clean_guidance:
            raise TextModelOutputError("请先描述正确的故事细节或必须遵守的情节")

        status = self._configuration_status()
        if not status.configured:
            raise TextModelConfigurationError(status.message)

        messages = build_story_guidance_revision_messages(project, clean_guidance)
        last_error: TextModelOutputError | None = None
        for attempt in range(self.max_retries + 1):
            raw_output = self._chat(messages)
            try:
                revised = parse_reviewed_project(raw_output, project)
                revised.user_story_guidance = clean_guidance
                revised.script_reviewed = True
                return revised
            except TextModelOutputError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                messages = build_story_guidance_repair_messages(
                    project,
                    clean_guidance,
                    raw_output,
                    str(exc),
                )
        raise TextModelOutputError(
            f"{self.display_name} 根据用户说明生成的修订稿无法解析：{last_error}"
        ) from last_error

    @abstractmethod
    def _configuration_status(self) -> TextModelStatus:
        """Return a status based only on local configuration."""

    @abstractmethod
    def _chat(self, messages: list[dict[str, str]]) -> str:
        """Return assistant message text from a provider HTTP request."""

    def _chat_for_review(self, messages: list[dict[str, str]]) -> str:
        """Run review generation; providers may apply a shorter read budget."""
        return self._chat(messages)

    def _chat_for_repair(self, messages: list[dict[str, str]]) -> str:
        """Run a small deterministic repair; providers may reduce its budget."""
        return self._chat(messages)
