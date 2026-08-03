"""Application service orchestrating text, image, persistence, and layout."""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from comicforge_ai.layout import (
    compose_comic,
    custom_frame_for_sequence,
    custom_panel_render_size,
    prepare_panel_with_bubbles,
    validate_custom_layout,
)
from comicforge_ai.models import (
    ImageModelStatus,
    ImageProvider,
    ImageProviderRegistry,
    TextModelProvider,
    TextModelRegistry,
    TextModelStatus,
    build_default_image_registry,
    build_default_registry,
)
from comicforge_ai.models.base import TextModelError
from comicforge_ai.models.image_base import (
    ImageModelError,
    ImageSaveError,
    UnsupportedCapabilityError,
)
from comicforge_ai.prompts import build_panel_image_request
from comicforge_ai.schemas import (
    ComicLocalization,
    ComicPage,
    ComicProject,
    ComicTextItem,
    ContentLanguage,
    ImageGenerationRequest,
    LayoutMode,
    LetteringStyle,
    PanelImageRecord,
    PanelSpec,
    PanelTextLocalization,
    RevisionTurn,
    SubShot,
)


@dataclass(frozen=True, slots=True)
class ImageGenerationOptions:
    """Provider-neutral advanced image options collected by the UI or scripts."""

    model: str = ""
    negative_prompt: str = ""
    width: int | None = None
    height: int | None = None
    aspect_ratio: str = ""
    quality: str = "auto"
    seed: int | None = None
    output_format: str = "png"
    reference_images: tuple[Path, ...] = ()
    mask_image: Path | None = None
    strength: float | None = None
    strict_mode: bool = False
    fallback_chain: tuple[str, ...] = ()
    concurrency: int = 1
    bubble_theme: str = "classic"
    lettering_style: LetteringStyle = "immersive"
    show_narration: bool = True
    show_panel_numbers: bool = False
    auto_shorten_dialogue: bool = True


@dataclass(slots=True)
class ComicGenerationResult:
    """Full generation output including transparent provider provenance."""

    project: ComicProject
    comic_page: Image.Image
    requested_provider_id: str
    actual_provider_id: str
    actual_provider_name: str
    actual_model_name: str
    fallback_used: bool = False
    fallback_reason: str = ""
    requested_provider_seconds: float = 0
    actual_provider_seconds: float = 0
    thinking_control: str = ""
    requested_image_provider_id: str = "mock-image"
    actual_image_provider_names: tuple[str, ...] = ()
    actual_image_model_names: tuple[str, ...] = ()
    image_fallback_used: bool = False
    image_fallback_panels: tuple[int, ...] = ()
    image_error_summaries: dict[int, str] | None = None
    panel_image_seconds: dict[int, float] | None = None
    total_image_seconds: float = 0
    panel_image_paths: tuple[Path, ...] = ()
    comic_pdf_path: Path | None = None
    project_json_path: Path | None = None


@dataclass(slots=True)
class ScriptGenerationResult:
    """Reviewed script output produced without invoking an image Provider."""

    project: ComicProject
    requested_provider_id: str
    actual_provider_id: str
    actual_provider_name: str
    actual_model_name: str
    fallback_used: bool = False
    fallback_reason: str = ""
    requested_provider_seconds: float = 0
    actual_provider_seconds: float = 0
    thinking_control: str = ""


@dataclass(slots=True)
class ComicRelocalizationResult:
    """A new page rendered from existing raw panels without image generation."""

    project: ComicProject
    comic_page: Image.Image
    output_path: Path
    pdf_path: Path
    project_json_path: Path
    translation_provider_name: str
    translation_seconds: float
    used_cached_translation: bool


@dataclass(slots=True)
class _ImagePipelineResult:
    comic_page: Image.Image
    requested_provider_id: str
    actual_provider_names: tuple[str, ...]
    actual_model_names: tuple[str, ...]
    fallback_panels: tuple[int, ...]
    error_summaries: dict[int, str]
    panel_seconds: dict[int, float]
    total_seconds: float
    panel_paths: tuple[Path, ...]
    pdf_path: Path
    project_json_path: Path


@dataclass(slots=True)
class _PanelPipelineResult:
    panel: PanelSpec
    image: Image.Image
    path: Path
    record: PanelImageRecord
    fallback_used: bool
    error_summary: str
    elapsed: float


def _environment_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _environment_integer(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def normalize_optional_seed(value: float | None) -> int | None:
    """Treat zero/empty UI values as automatic Provider-side seed selection."""
    if value is None or int(value) == 0:
        return None
    return int(value)


def enhance_multi_shot_compositions(project: ComicProject) -> ComicProject:
    """Add one purposeful inset when a script contains a clear visual cue.

    Some text models acknowledge the multi-shot option but still return every
    panel as ``single``. This conservative pass only intervenes when a panel
    already describes a reveal, reaction, detail, or simultaneous action.
    """
    if not project.allow_multi_shot_panels or len(project.panels) < 2:
        return project
    if any(panel.composition != "single" and panel.subshots for panel in project.panels):
        return project

    narrative_cues = (
        "转折",
        "高潮",
        "揭示",
        "发现",
        "警告",
        "真相",
        "反应",
        "reveal",
        "climax",
        "twist",
        "reaction",
    )
    visual_cues = (
        "同时",
        "与此同时",
        "特写",
        "细节",
        "远处",
        "近处",
        "注意到",
        "看见",
        "忽视",
        "打开",
        "关键",
        "reaction",
        "close-up",
        "detail",
        "meanwhile",
    )
    ranked: list[tuple[int, int, PanelSpec]] = []
    for index, panel in enumerate(project.panels):
        role = panel.narrative_role.lower()
        visual_text = (
            f"{panel.scene} {panel.visual_description} "
            f"{panel.action} {panel.image_prompt}"
        ).lower()
        score = 0
        if any(cue in role for cue in narrative_cues):
            score += 3
        if any(cue in visual_text for cue in visual_cues):
            score += 2
        if len(panel.characters) >= 2:
            score += 1
        if panel.importance >= 4:
            score += 2
        interior = 1 if 0 < index < len(project.panels) - 1 else 0
        ranked.append((score, interior, panel))

    score, _, candidate = max(ranked, key=lambda item: (item[0], item[1]))
    if score < 3:
        return project

    focus = candidate.action.strip() or candidate.visual_description.strip()
    candidate.composition = "inset"
    candidate.subshots = [
        SubShot(
            shot_type="reaction_or_detail_close_up",
            visual_description=f"以局部特写补充本格关键反应或线索：{focus[:120]}",
            focus="不重复主画面的关键表情、动作结果或道具细节",
            position="top_right",
        )
    ]
    note = f"第 {candidate.sequence} 格包含关键反应或细节，采用主画面加插入特写。"
    if note not in project.review_notes:
        project.review_notes.append(note)
    return project


def _dialogue_parts(value: str) -> tuple[str | None, str]:
    clean = value.strip().strip("“”\"'")
    for separator in ("：", ":"):
        if separator in clean:
            speaker, text = clean.split(separator, maxsplit=1)
            if speaker.strip() and text.strip():
                return speaker.strip(), text.strip().strip("“”\"'")
    return None, clean


def _shorten_panel_text(panel: PanelSpec, language: ContentLanguage) -> None:
    for item in panel.text_items:
        if item.type not in {"speech", "thought", "narration"}:
            continue
        if language == "en":
            words = item.text.split()
            limit = 16 if item.type == "narration" else 12
            if len(words) <= limit:
                continue
            item.text = " ".join(words[: limit - 1]) + "…"
        else:
            compact = item.text.replace("\n", "").strip()
            limit = 30 if item.type == "narration" else 24
            if len(compact) <= limit:
                continue
            item.text = compact[: limit - 1] + "…"
        panel.render_warnings.append("漫画文字过长，已按启用的自动缩短设置进行精简。")


class ComicGenerator:
    """Run the full comic workflow against a selected text provider."""

    def __init__(
        self,
        text_model: TextModelProvider | None = None,
        image_model: ImageProvider | None = None,
        output_dir: str | Path | None = None,
        registry: TextModelRegistry | None = None,
        image_registry: ImageProviderRegistry | None = None,
        fallback_to_mock: bool | None = None,
        image_fallback_to_mock: bool | None = None,
        image_fallback_chain: tuple[str, ...] | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.image_registry = image_registry or build_default_image_registry()
        self.text_model = text_model or self.registry.get("mock")
        self.image_model: ImageProvider = image_model or self.image_registry.get(
            "mock-image"
        )
        self.fallback_to_mock = (
            _environment_flag("TEXT_MODEL_FALLBACK_TO_MOCK", True)
            if fallback_to_mock is None
            else fallback_to_mock
        )
        self.image_fallback_to_mock = (
            _environment_flag("IMAGE_MODEL_FALLBACK_TO_MOCK", True)
            if image_fallback_to_mock is None
            else image_fallback_to_mock
        )
        configured_chain = os.getenv("IMAGE_PROVIDER_FALLBACK_CHAIN", "")
        self.image_fallback_chain = (
            tuple(item.strip() for item in configured_chain.split(",") if item.strip())
            if image_fallback_chain is None
            else image_fallback_chain
        )
        configured_dir = output_dir or os.getenv("COMICFORGE_OUTPUT_DIR", "outputs")
        self.output_dir = Path(configured_dir)

    def generate(
        self,
        theme: str,
        style: str,
        panel_count: int = 4,
    ) -> tuple[ComicProject, Image.Image]:
        """Backward-compatible day-one entry point using ``self.text_model``."""
        project = self.text_model.generate_project(theme, style, int(panel_count))
        rendered = self._render_and_save(project, self.image_model)
        return project, rendered.comic_page

    def generate_with_status(
        self,
        theme: str,
        style: str,
        panel_count: int,
        provider_id: str = "mock",
        image_provider_id: str = "mock-image",
        image_options: ImageGenerationOptions | None = None,
        language: ContentLanguage = "zh-CN",
    ) -> ComicGenerationResult:
        """Generate with a selected provider and an explicit optional Mock fallback."""
        try:
            requested_provider = self.registry.get(provider_id)
        except KeyError as exc:
            raise TextModelError(str(exc)) from exc

        actual_provider = requested_provider
        fallback_used = False
        fallback_reason = ""
        requested_started = time.perf_counter()
        try:
            project = requested_provider.generate_project(
                theme, style, int(panel_count), language
            )
            requested_provider_seconds = time.perf_counter() - requested_started
            actual_provider_seconds = requested_provider_seconds
        except Exception as exc:
            requested_provider_seconds = time.perf_counter() - requested_started
            if provider_id == "mock" or not self.fallback_to_mock:
                if isinstance(exc, TextModelError):
                    raise
                raise TextModelError(f"文本模型生成失败：{exc}") from exc
            fallback_used = True
            fallback_reason = str(exc) or type(exc).__name__
            actual_provider = self.registry.get("mock")
            fallback_started = time.perf_counter()
            project = actual_provider.generate_project(
                theme,
                style,
                int(panel_count),
                language,
            )
            actual_provider_seconds = time.perf_counter() - fallback_started

        try:
            image_provider = (
                self.image_model
                if image_provider_id == self.image_model.model_id
                else self.image_registry.get(image_provider_id)
            )
        except KeyError as exc:
            raise ImageModelError(str(exc)) from exc
        rendered = self._render_and_save(project, image_provider, image_options)
        return ComicGenerationResult(
            project=project,
            comic_page=rendered.comic_page,
            requested_provider_id=provider_id,
            actual_provider_id=actual_provider.model_id,
            actual_provider_name=actual_provider.display_name,
            actual_model_name=actual_provider.model_name,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            requested_provider_seconds=requested_provider_seconds,
            actual_provider_seconds=actual_provider_seconds,
            thinking_control=str(
                getattr(requested_provider, "last_thinking_control", "")
            ),
            requested_image_provider_id=rendered.requested_provider_id,
            actual_image_provider_names=rendered.actual_provider_names,
            actual_image_model_names=rendered.actual_model_names,
            image_fallback_used=bool(rendered.fallback_panels),
            image_fallback_panels=rendered.fallback_panels,
            image_error_summaries=rendered.error_summaries,
            panel_image_seconds=rendered.panel_seconds,
            total_image_seconds=rendered.total_seconds,
            panel_image_paths=rendered.panel_paths,
            comic_pdf_path=rendered.pdf_path,
            project_json_path=rendered.project_json_path,
        )

    def generate_script_with_status(
        self,
        theme: str,
        style: str,
        panel_count: int,
        provider_id: str = "mock",
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "grid",
        allow_multi_shot_panels: bool = False,
        source_story: str = "",
    ) -> ScriptGenerationResult:
        """Generate, review, and revise a script without spending image credits."""
        try:
            requested_provider = self.registry.get(provider_id)
        except KeyError as exc:
            raise TextModelError(str(exc)) from exc
        actual_provider = requested_provider
        fallback_used = False
        fallback_reason = ""
        started = time.perf_counter()
        try:
            project = requested_provider.generate_reviewed_project(
                theme,
                style,
                int(panel_count),
                language,
                layout_mode,
                allow_multi_shot_panels,
                source_story,
            )
            requested_seconds = time.perf_counter() - started
            actual_seconds = requested_seconds
        except Exception as exc:
            requested_seconds = time.perf_counter() - started
            if provider_id == "mock" or not self.fallback_to_mock:
                if isinstance(exc, TextModelError):
                    raise
                raise TextModelError(f"剧本生成或审查失败：{exc}") from exc
            fallback_used = True
            fallback_reason = str(exc) or type(exc).__name__
            actual_provider = self.registry.get("mock")
            fallback_started = time.perf_counter()
            project = actual_provider.generate_reviewed_project(
                theme,
                style,
                int(panel_count),
                language,
                layout_mode,
                allow_multi_shot_panels,
                source_story,
            )
            actual_seconds = time.perf_counter() - fallback_started
        project.content_language = language
        project.layout_mode = layout_mode
        project.allow_multi_shot_panels = allow_multi_shot_panels
        enhance_multi_shot_compositions(project)
        return ScriptGenerationResult(
            project=project,
            requested_provider_id=provider_id,
            actual_provider_id=actual_provider.model_id,
            actual_provider_name=actual_provider.display_name,
            actual_model_name=actual_provider.model_name,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            requested_provider_seconds=requested_seconds,
            actual_provider_seconds=actual_seconds,
            thinking_control=str(
                getattr(requested_provider, "last_thinking_control", "")
            ),
        )

    def redesign_script_with_guidance(
        self,
        project: ComicProject,
        user_guidance: str,
        provider_id: str = "mock",
    ) -> ScriptGenerationResult:
        """Rebuild a reviewed script from user facts without invoking images."""
        clean_guidance = user_guidance.strip()
        if not clean_guidance:
            raise TextModelError("请先描述正确的故事细节或必须遵守的情节")
        try:
            requested_provider = self.registry.get(provider_id)
        except KeyError as exc:
            raise TextModelError(str(exc)) from exc

        actual_provider = requested_provider
        fallback_used = False
        fallback_reason = ""
        started = time.perf_counter()
        round_number = len(project.revision_history) + 1
        cumulative_guidance = (
            f"{project.user_story_guidance}\n\n"
            f"第 {round_number} 轮追加修正：\n{clean_guidance}"
            if project.user_story_guidance
            else clean_guidance
        )
        try:
            revised = requested_provider.revise_project_with_guidance(
                project.model_copy(deep=True),
                clean_guidance,
            )
            requested_seconds = time.perf_counter() - started
            actual_seconds = requested_seconds
        except Exception as exc:
            requested_seconds = time.perf_counter() - started
            if provider_id == "mock" or not self.fallback_to_mock:
                if isinstance(exc, TextModelError):
                    raise
                raise TextModelError(f"根据用户说明重做分镜失败：{exc}") from exc
            fallback_used = True
            fallback_reason = str(exc) or type(exc).__name__
            actual_provider = self.registry.get("mock")
            fallback_started = time.perf_counter()
            revised = actual_provider.revise_project_with_guidance(
                project.model_copy(deep=True),
                clean_guidance,
            )
            actual_seconds = time.perf_counter() - fallback_started

        revised.theme = project.theme
        revised.style = project.style
        revised.panel_count = project.panel_count
        revised.content_language = project.content_language
        revised.layout_mode = project.layout_mode
        revised.custom_layout = [
            frame.model_copy(deep=True) for frame in project.custom_layout
        ]
        revised.allow_multi_shot_panels = project.allow_multi_shot_panels
        enhance_multi_shot_compositions(revised)
        revised.user_story_guidance = cumulative_guidance
        revised.revision_history = [
            *project.revision_history,
            RevisionTurn(
                round=round_number,
                instruction=clean_guidance,
                result_summary="；".join(revised.review_notes[-2:]),
            ),
        ]
        revised.script_reviewed = True
        return ScriptGenerationResult(
            project=revised,
            requested_provider_id=provider_id,
            actual_provider_id=actual_provider.model_id,
            actual_provider_name=actual_provider.display_name,
            actual_model_name=actual_provider.model_name,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            requested_provider_seconds=requested_seconds,
            actual_provider_seconds=actual_seconds,
            thinking_control=str(
                getattr(requested_provider, "last_thinking_control", "")
            ),
        )

    def render_confirmed_project(
        self,
        project: ComicProject,
        image_provider_id: str = "mock-image",
        image_options: ImageGenerationOptions | None = None,
    ) -> ComicGenerationResult:
        """Invoke image Providers only after the caller confirms the script."""
        try:
            image_provider = self.image_registry.get(image_provider_id)
        except KeyError as exc:
            raise ImageModelError(str(exc)) from exc
        if project.layout_mode == "custom_page":
            validate_custom_layout(project.custom_layout, project.panel_count)
        rendered = self._render_and_save(project, image_provider, image_options)
        return ComicGenerationResult(
            project=project,
            comic_page=rendered.comic_page,
            requested_provider_id="confirmed-script",
            actual_provider_id="confirmed-script",
            actual_provider_name="已确认并审查的剧本",
            actual_model_name="script-state",
            requested_image_provider_id=rendered.requested_provider_id,
            actual_image_provider_names=rendered.actual_provider_names,
            actual_image_model_names=rendered.actual_model_names,
            image_fallback_used=bool(rendered.fallback_panels),
            image_fallback_panels=rendered.fallback_panels,
            image_error_summaries=rendered.error_summaries,
            panel_image_seconds=rendered.panel_seconds,
            total_image_seconds=rendered.total_seconds,
            panel_image_paths=rendered.panel_paths,
            comic_pdf_path=rendered.pdf_path,
            project_json_path=rendered.project_json_path,
        )

    def relocalize_rendered_project(
        self,
        project: ComicProject,
        rows: list[list[object]],
        final_title: str,
        target_language: ContentLanguage,
        text_provider_id: str,
        *,
        translate_with_model: bool,
        layout_mode: LayoutMode,
        image_options: ImageGenerationOptions | None = None,
    ) -> ComicRelocalizationResult:
        """Translate/edit lettering and recompose saved raw panels for free."""
        options = image_options or ImageGenerationOptions()
        working = project.model_copy(deep=True)
        self._capture_localization(working)
        used_cached = False
        translation_seconds = 0.0
        provider_name = "无需翻译"

        if target_language == working.content_language:
            working = self.apply_storyboard_edits(working, rows)
            working.title = final_title.strip() or working.title
        elif target_language in working.localizations:
            current = self.apply_storyboard_edits(working, rows)
            current.title = final_title.strip() or current.title
            self._capture_localization(current)
            working = self._apply_localization(current, target_language)
            used_cached = True
            provider_name = "项目内缓存译文"
        elif translate_with_model:
            current = self.apply_storyboard_edits(working, rows)
            current.title = final_title.strip() or current.title
            self._capture_localization(current)
            try:
                provider = self.registry.get(text_provider_id)
            except KeyError as exc:
                raise TextModelError(str(exc)) from exc
            started = time.perf_counter()
            working = provider.translate_project(current, target_language)
            translation_seconds = time.perf_counter() - started
            provider_name = f"{provider.display_name} · {provider.model_name}"
        else:
            original_visible = (
                working.title,
                [item.text for panel in working.panels for item in panel.text_items],
            )
            working = self.apply_storyboard_edits(working, rows)
            if not final_title.strip():
                raise ValueError("请填写目标语言的漫画标题")
            working.title = final_title.strip()
            edited_visible = (
                working.title,
                [item.text for panel in working.panels for item in panel.text_items],
            )
            if (
                target_language != working.content_language
                and edited_visible == original_visible
            ):
                raise ValueError(
                    "手动译文模式不会自动翻译。请先在标题和分镜表格中填写目标语言文字，"
                    "或改选“使用当前文本模型翻译”。"
                )
            working.content_language = target_language

        working.layout_mode = layout_mode
        working.bubble_theme = options.bubble_theme
        working.lettering_style = options.lettering_style
        working.show_panel_numbers = options.show_panel_numbers
        self._capture_localization(working)
        (
            comic_page,
            output_path,
            pdf_path,
            project_json_path,
        ) = self._rerender_saved_panels(
            working,
            options,
        )
        return ComicRelocalizationResult(
            project=working,
            comic_page=comic_page,
            output_path=output_path,
            pdf_path=pdf_path,
            project_json_path=project_json_path,
            translation_provider_name=provider_name,
            translation_seconds=translation_seconds,
            used_cached_translation=used_cached,
        )

    def generate_auto_with_status(
        self,
        theme: str,
        style: str,
        panel_count: int,
        *,
        text_provider_id: str,
        image_provider_id: str,
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "adaptive_page",
        allow_multi_shot_panels: bool = True,
        source_story: str = "",
        image_options: ImageGenerationOptions | None = None,
    ) -> ComicGenerationResult:
        """Generate reviewed text and images in one explicitly selected auto flow."""
        script = self.generate_script_with_status(
            theme,
            style,
            panel_count,
            text_provider_id,
            language,
            layout_mode,
            allow_multi_shot_panels,
            source_story,
        )
        result = self.render_confirmed_project(
            script.project,
            image_provider_id,
            image_options,
        )
        result.requested_provider_id = script.requested_provider_id
        result.actual_provider_id = script.actual_provider_id
        result.actual_provider_name = script.actual_provider_name
        result.actual_model_name = script.actual_model_name
        result.fallback_used = script.fallback_used
        result.fallback_reason = script.fallback_reason
        result.requested_provider_seconds = script.requested_provider_seconds
        result.actual_provider_seconds = script.actual_provider_seconds
        result.thinking_control = script.thinking_control
        return result

    @staticmethod
    def apply_storyboard_edits(
        project: ComicProject,
        rows: list[list[object]],
    ) -> ComicProject:
        """Apply user-confirmed visual/dialogue/narration edits by sequence."""
        updated = project.model_copy(deep=True)
        by_sequence = {panel.sequence: panel for panel in updated.panels}
        for row in rows:
            if len(row) < 4:
                continue
            try:
                sequence = int(row[0])
            except (TypeError, ValueError):
                continue
            panel = by_sequence.get(sequence)
            if panel is None:
                continue
            panel.visual_description = str(row[1] or "").strip()
            panel.dialogue = str(row[2] or "").strip()
            panel.narration = str(row[3] or "").strip()
            retained = [
                item
                for item in panel.text_items
                if item.type not in {"speech", "narration"}
            ]
            if panel.dialogue:
                speaker, text = _dialogue_parts(panel.dialogue)
                template = next(
                    (item for item in panel.text_items if item.type == "speech"),
                    None,
                )
                retained.append(
                    ComicTextItem(
                        type="speech",
                        speaker=speaker or (template.speaker if template else None),
                        text=text,
                        preferred_position=template.preferred_position
                        if template
                        else "top_left",
                        speaker_position=template.speaker_position if template else None,
                        speaker_anchor=template.speaker_anchor if template else None,
                    )
                )
            if panel.narration:
                retained.append(
                    ComicTextItem(
                        type="narration",
                        text=panel.narration,
                        preferred_position="top_right",
                    )
                )
            panel.text_items = retained
        return updated

    @staticmethod
    def load_project(project_path: str | Path) -> ComicProject:
        """Load a current or legacy project JSON through compatibility validators."""
        path = Path(project_path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ImageModelError(f"项目文件读取失败：{path.name}") from exc
        try:
            project = ComicProject.model_validate_json(raw)
        except ValueError as exc:
            raise ImageModelError(f"项目 JSON 无法解析：{exc}") from exc
        if project.output_path is not None and not project.output_path.is_absolute():
            project.output_path = (path.resolve().parent / project.output_path).resolve()
        return project

    @staticmethod
    def _capture_localization(project: ComicProject) -> None:
        project.localizations[project.content_language] = ComicLocalization(
            title=project.title,
            panels=[
                PanelTextLocalization(
                    sequence=panel.sequence,
                    text_items=[item.text for item in panel.text_items],
                )
                for panel in project.panels
            ],
        )

    @staticmethod
    def _apply_localization(
        project: ComicProject,
        language: ContentLanguage,
    ) -> ComicProject:
        localized = project.localizations[language]
        if [item.sequence for item in localized.panels] != [
            panel.sequence for panel in project.panels
        ]:
            raise ImageModelError("缓存译文的分格顺序与当前项目不一致")
        updated = project.model_copy(deep=True)
        updated.title = localized.title
        updated.content_language = language
        for panel, translated in zip(
            updated.panels,
            localized.panels,
            strict=True,
        ):
            if len(panel.text_items) != len(translated.text_items):
                raise ImageModelError(
                    f"第 {panel.sequence} 格缓存译文数量与当前文字项不一致"
                )
            for item, text in zip(
                panel.text_items,
                translated.text_items,
                strict=True,
            ):
                item.text = text
            _sync_panel_legacy_text(panel)
        return updated

    def _rerender_saved_panels(
        self,
        project: ComicProject,
        options: ImageGenerationOptions,
    ) -> tuple[Image.Image, Path, Path, Path]:
        if project.output_path is None or not project.panel_images:
            raise ImageModelError(
                "当前项目状态没有已生成的原始分格；请先生成漫画图片后再切换语言"
            )
        run_dir = Path(project.output_path).expanduser().resolve().parent
        raw_images: list[Image.Image] = []
        records = {record.sequence: record for record in project.panel_images}
        for panel in project.panels:
            record = records.get(panel.sequence)
            if record is None:
                raise ImageModelError(f"缺少第 {panel.sequence} 格原图记录")
            raw_path = (run_dir / record.local_path).resolve()
            try:
                raw_path.relative_to(run_dir)
            except ValueError as exc:
                raise ImageModelError("项目图片路径超出项目输出目录") from exc
            try:
                with Image.open(raw_path) as source:
                    source.load()
                    raw = source.convert("RGB")
            except (OSError, ValueError) as exc:
                raise ImageModelError(
                    f"无法读取第 {panel.sequence} 格原图：{raw_path.name}"
                ) from exc
            if options.auto_shorten_dialogue:
                _shorten_panel_text(panel, project.content_language)
            rendered = prepare_panel_with_bubbles(
                raw,
                panel,
                size=custom_panel_render_size(
                    custom_frame_for_sequence(
                        project.custom_layout,
                        panel.sequence,
                    )
                    if project.layout_mode == "custom_page"
                    else None
                ),
                language=project.content_language,
                bubble_theme=options.bubble_theme,
                lettering_style=options.lettering_style,
                show_narration=options.show_narration,
                show_panel_numbers=options.show_panel_numbers,
            )
            panel.render_warnings = list(
                dict.fromkeys([*panel.render_warnings, *rendered.warnings])
            )
            raw_images.append(rendered.image)
        comic_page = compose_comic(
            raw_images,
            project.title,
            layout_mode=project.layout_mode,
            panel_specs=project.panels,
            custom_layout=project.custom_layout,
        )
        tag = project.content_language.replace("-", "_")
        output_path = run_dir / f"comic_{tag}.png"
        project_json_path = run_dir / f"project_{tag}.json"
        try:
            comic_page.save(output_path, format="PNG")
        except OSError as exc:
            raise ImageSaveError("切换语言后的漫画 PNG 保存失败") from exc
        pdf_path = self._save_comic_pdf(comic_page, output_path.with_suffix(".pdf"))
        project.output_path = output_path
        self._save_project_json(project, project_json_path)
        return comic_page, output_path, pdf_path, project_json_path

    def check_provider(self, provider_id: str) -> TextModelStatus:
        """Return a friendly provider status without involving the UI layer."""
        try:
            return self.registry.get(provider_id).check_availability()
        except KeyError as exc:
            raise TextModelError(str(exc)) from exc

    def check_image_provider(self, provider_id: str) -> ImageModelStatus:
        """Return a friendly image-provider status without UI logic."""
        try:
            return self.image_registry.get(provider_id).check_availability()
        except KeyError as exc:
            raise ImageModelError(str(exc)) from exc

    def _render_and_save(
        self,
        project: ComicProject,
        requested_provider: ImageProvider,
        options: ImageGenerationOptions | None = None,
    ) -> _ImagePipelineResult:
        options = options or ImageGenerationOptions(
            concurrency=max(1, _environment_integer("IMAGE_PANEL_CONCURRENCY", 1))
        )
        project.bubble_theme = options.bubble_theme or project.bubble_theme
        project.lettering_style = options.lettering_style
        project.show_panel_numbers = options.show_panel_numbers
        run_dir = self._create_run_directory(project.theme)
        provider_chain = self._resolve_image_provider_chain(
            requested_provider,
            options,
        )
        pipeline_started = time.perf_counter()
        completed: dict[int, _PanelPipelineResult] = {}
        failures: dict[int, str] = {}
        concurrency = max(1, min(int(options.concurrency), len(project.panels), 8))
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    self._generate_panel_with_chain,
                    project,
                    panel,
                    run_dir,
                    provider_chain,
                    options,
                ): panel.sequence
                for panel in project.panels
            }
            for future in as_completed(futures):
                sequence = futures[future]
                try:
                    completed[sequence] = future.result()
                except ImageModelError as exc:
                    failures[sequence] = self._safe_image_error(
                        exc,
                        requested_provider,
                    )
        if failures:
            detail = "；".join(
                f"第 {sequence} 格：{message}"
                for sequence, message in sorted(failures.items())
            )
            raise ImageModelError(f"图片生成未全部成功：{detail}")

        ordered = [completed[panel.sequence] for panel in project.panels]
        panel_images = [item.image for item in ordered]
        panel_paths = [item.path for item in ordered]
        panel_records = [item.record for item in ordered]
        fallback_panels = [
            item.panel.sequence for item in ordered if item.fallback_used
        ]
        error_summaries = {
            item.panel.sequence: item.error_summary
            for item in ordered
            if item.error_summary
        }
        panel_seconds = {
            item.panel.sequence: item.elapsed for item in ordered
        }

        if project.layout_mode == "adaptive_page":
            project.pages = [
                ComicPage(
                    number=index // 6 + 1,
                    panel_sequences=[
                        panel.sequence for panel in project.panels[index : index + 6]
                    ],
                )
                for index in range(0, len(project.panels), 6)
            ]
        else:
            project.pages = [
                ComicPage(
                    number=1,
                    panel_sequences=[panel.sequence for panel in project.panels],
                )
            ]
        comic_page = compose_comic(
            panel_images,
            project.title,
            layout_mode=project.layout_mode,
            panel_specs=project.panels,
            custom_layout=project.custom_layout,
        )
        output_path = run_dir / "comic.png"
        try:
            comic_page.save(output_path, format="PNG")
        except OSError as exc:
            raise ImageSaveError("最终漫画 PNG 保存失败") from exc
        pdf_path = self._save_comic_pdf(comic_page, run_dir / "comic.pdf")
        project.output_path = output_path
        project.requested_image_provider = requested_provider.model_id
        project.requested_image_model = requested_provider.model_name
        project.image_fallback_used = bool(fallback_panels)
        project.image_error_summary = "；".join(
            f"第 {sequence} 格：{message}"
            for sequence, message in error_summaries.items()
        )
        project.panel_images = panel_records
        self._capture_localization(project)
        project_json_path = run_dir / "project.json"
        self._save_project_json(project, project_json_path)

        return _ImagePipelineResult(
            comic_page=comic_page,
            requested_provider_id=requested_provider.model_id,
            actual_provider_names=tuple(
                dict.fromkeys(record.provider_name for record in panel_records)
            ),
            actual_model_names=tuple(
                dict.fromkeys(record.model_name for record in panel_records)
            ),
            fallback_panels=tuple(fallback_panels),
            error_summaries=error_summaries,
            panel_seconds=panel_seconds,
            total_seconds=time.perf_counter() - pipeline_started,
            panel_paths=tuple(panel_paths),
            pdf_path=pdf_path,
            project_json_path=project_json_path,
        )

    def _resolve_image_provider_chain(
        self,
        requested_provider: ImageProvider,
        options: ImageGenerationOptions,
    ) -> tuple[ImageProvider, ...]:
        ids = [requested_provider.model_id]
        strict = options.strict_mode or not self.image_fallback_to_mock
        if not strict:
            ids.extend(options.fallback_chain or self.image_fallback_chain)
            ids.append("mock-image")
        providers: list[ImageProvider] = []
        for provider_id in dict.fromkeys(ids):
            try:
                providers.append(
                    requested_provider
                    if provider_id == requested_provider.model_id
                    else self.image_registry.get(provider_id)
                )
            except KeyError as exc:
                raise ImageModelError(
                    f"图片回退链包含未注册 Provider：{provider_id}"
                ) from exc
        return tuple(providers)

    def _generate_panel_with_chain(
        self,
        project: ComicProject,
        panel: PanelSpec,
        run_dir: Path,
        provider_chain: tuple[ImageProvider, ...],
        options: ImageGenerationOptions,
    ) -> _PanelPipelineResult:
        base = build_panel_image_request(project, panel)
        requested_seed = normalize_optional_seed(options.seed)
        primary_provider = provider_chain[0]
        if requested_seed is not None and not primary_provider.get_capabilities().seed:
            raise UnsupportedCapabilityError(
                f"{primary_provider.display_name} 不支持参数：Seed"
            )
        request = ImageGenerationRequest(
            prompt=base.prompt,
            negative_prompt=options.negative_prompt,
            width=options.width,
            height=options.height,
            aspect_ratio=options.aspect_ratio,
            quality=options.quality,
            count=1,
            seed=None,
            style=project.style,
            output_format=options.output_format,
            reference_images=list(options.reference_images),
            mask_image=options.mask_image,
            strength=options.strength,
            model=options.model,
            panel=panel,
        )
        panel_path = run_dir / f"panel_{panel.sequence:02d}.png"
        started = time.perf_counter()
        errors: list[str] = []
        generated = None
        actual_provider = provider_chain[0]
        for index, provider in enumerate(provider_chain):
            actual_provider = provider
            panel_seed = (
                requested_seed + panel.sequence - 1
                if requested_seed is not None and provider.get_capabilities().seed
                else None
            )
            width, height, aspect_ratio = self._request_shape(
                project,
                panel,
                provider,
                options,
            )
            attempt_request = request.model_copy(
                update={
                    "seed": panel_seed,
                    "width": width,
                    "height": height,
                    "aspect_ratio": aspect_ratio,
                }
            )
            if provider.model_id == "mock-image" and index > 0:
                attempt_request = attempt_request.model_copy(
                    update={
                        "negative_prompt": "",
                        "reference_images": [],
                        "mask_image": None,
                        "count": 1,
                    }
                )
            try:
                operation = (
                    "edit"
                    if attempt_request.reference_images
                    or attempt_request.mask_image is not None
                    else "text_to_image"
                )
                generated = (
                    provider.edit(attempt_request, panel_path)
                    if operation == "edit"
                    else provider.generate(attempt_request, panel_path)
                )
                break
            except ImageModelError as exc:
                errors.append(
                    f"{provider.model_id}/{type(exc).__name__}："
                    f"{self._safe_image_error(exc, provider)}"
                )
        if generated is None:
            raise ImageModelError("；".join(errors))
        elapsed = time.perf_counter() - started
        path = generated.output_path
        if path is None:
            raise ImageSaveError("图片 Provider 未保存本地文件")
        if options.auto_shorten_dialogue:
            _shorten_panel_text(panel, project.content_language)
        bubble_result = prepare_panel_with_bubbles(
            generated.image,
            panel,
            size=custom_panel_render_size(
                custom_frame_for_sequence(project.custom_layout, panel.sequence)
                if project.layout_mode == "custom_page"
                else None
            ),
            language=project.content_language,
            bubble_theme=options.bubble_theme or project.bubble_theme,
            lettering_style=options.lettering_style or project.lettering_style,
            show_narration=options.show_narration,
            show_panel_numbers=options.show_panel_numbers,
        )
        composition_image = bubble_result.image
        panel.render_warnings = list(
            dict.fromkeys([*panel.render_warnings, *bubble_result.warnings])
        )
        fallback_used = actual_provider.model_id != provider_chain[0].model_id
        generated.fallback_used = fallback_used
        generated.errors = list(errors)
        return _PanelPipelineResult(
            panel=panel,
            image=composition_image,
            path=path,
            record=PanelImageRecord(
                sequence=panel.sequence,
                provider_id=actual_provider.model_id,
                provider_name=actual_provider.display_name,
                model_name=generated.model_name,
                panel_prompt=request.prompt,
                local_path=path.relative_to(run_dir).as_posix(),
                generation_seconds=elapsed,
                operation=generated.operation,
                request_id=generated.request_id,
                seed=generated.seed,
                actual_parameters=generated.actual_parameters or {},
                fallback_used=fallback_used,
                error_summary="；".join(errors),
            ),
            fallback_used=fallback_used,
            error_summary="；".join(errors),
            elapsed=elapsed,
        )

    @staticmethod
    def _request_shape(
        project: ComicProject,
        panel: PanelSpec,
        provider: ImageProvider,
        options: ImageGenerationOptions,
    ) -> tuple[int | None, int | None, str]:
        """Derive generation shape from the selected page/frame layout."""
        if options.width or options.height or options.aspect_ratio:
            return options.width, options.height, options.aspect_ratio
        frame = (
            custom_frame_for_sequence(project.custom_layout, panel.sequence)
            if project.layout_mode == "custom_page"
            else None
        )
        frame_type = frame.frame_type if frame is not None else "landscape"
        candidates = {
            "square": ("1:1",),
            "portrait": ("3:4", "2:3"),
            "landscape": ("3:2", "4:3"),
            "wide": ("2:1", "3:2", "4:3"),
        }[frame_type]
        definition = provider.model_definitions()[0]
        supported = set(definition.supported_sizes)
        for candidate in candidates:
            if candidate in supported:
                return None, None, candidate
        if provider.get_capabilities().arbitrary_size:
            width, height = {
                "square": (1024, 1024),
                "portrait": (768, 1024),
                "landscape": (960, 640),
                "wide": (1024, 512),
            }[frame_type]
            return width, height, ""
        return None, None, ""

    def _create_run_directory(self, theme: str) -> Path:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        safe_theme = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", theme).strip("_")
        safe_theme = safe_theme[:30] or "comic"
        run_dir = self.output_dir / f"{timestamp}_{safe_theme}"
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            raise ImageSaveError("漫画项目输出目录创建失败") from exc
        return run_dir

    @staticmethod
    def _safe_image_error(exc: Exception, provider: ImageProvider) -> str:
        message = provider.redact_secrets(str(exc) or type(exc).__name__)
        message = re.sub(
            r"Bearer\s+[A-Za-z0-9._~+/=-]+",
            "Bearer [REDACTED]",
            message,
            flags=re.IGNORECASE,
        )
        return message[:1000]

    @staticmethod
    def _save_comic_pdf(comic_page: Image.Image, output_path: Path) -> Path:
        """Export the composed comic as one lossless full-page PDF page."""
        width, height = comic_page.size
        try:
            document = canvas.Canvas(str(output_path), pagesize=(width, height))
            document.drawImage(
                ImageReader(comic_page.convert("RGB")),
                0,
                0,
                width=width,
                height=height,
                preserveAspectRatio=True,
                anchor="c",
            )
            document.showPage()
            document.save()
        except (OSError, ValueError) as exc:
            raise ImageSaveError("最终漫画 PDF 保存失败") from exc
        return output_path

    @staticmethod
    def _save_project_json(project: ComicProject, output_path: Path) -> None:
        payload = project.model_dump(mode="json")
        payload["output_path"] = (
            Path(project.output_path).name
            if project.output_path is not None
            else "comic.png"
        )
        try:
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ImageSaveError("project.json 保存失败") from exc


def _sync_panel_legacy_text(panel: PanelSpec) -> None:
    speeches = [
        f"{item.speaker}：{item.text}" if item.speaker else item.text
        for item in panel.text_items
        if item.type in {"speech", "thought"}
    ]
    narrations = [
        item.text for item in panel.text_items if item.type == "narration"
    ]
    panel.dialogue = " ".join(speeches)
    panel.narration = " ".join(narrations)
