"""Application service orchestrating providers, placeholder images, and layout."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from comicforge_ai.layout import compose_comic
from comicforge_ai.models import (
    MockImageModel,
    TextModelProvider,
    TextModelRegistry,
    TextModelStatus,
    build_default_registry,
)
from comicforge_ai.models.base import TextModelError
from comicforge_ai.schemas import ComicProject


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


def _environment_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ComicGenerator:
    """Run the full comic workflow against a selected text provider."""

    def __init__(
        self,
        text_model: TextModelProvider | None = None,
        image_model: MockImageModel | None = None,
        output_dir: str | Path | None = None,
        registry: TextModelRegistry | None = None,
        fallback_to_mock: bool | None = None,
    ) -> None:
        self.registry = registry or build_default_registry()
        self.text_model = text_model or self.registry.get("mock")
        self.image_model = image_model or MockImageModel()
        self.fallback_to_mock = (
            _environment_flag("TEXT_MODEL_FALLBACK_TO_MOCK", True)
            if fallback_to_mock is None
            else fallback_to_mock
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
        comic_page = self._render_and_save(project)
        return project, comic_page

    def generate_with_status(
        self,
        theme: str,
        style: str,
        panel_count: int,
        provider_id: str = "mock",
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
                theme, style, int(panel_count)
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
            project = actual_provider.generate_project(theme, style, int(panel_count))
            actual_provider_seconds = time.perf_counter() - fallback_started

        comic_page = self._render_and_save(project)
        return ComicGenerationResult(
            project=project,
            comic_page=comic_page,
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
        )

    def check_provider(self, provider_id: str) -> TextModelStatus:
        """Return a friendly provider status without involving the UI layer."""
        try:
            return self.registry.get(provider_id).check_availability()
        except KeyError as exc:
            raise TextModelError(str(exc)) from exc

    def _render_and_save(self, project: ComicProject) -> Image.Image:
        panel_images = [
            self.image_model.generate_panel(panel, project.style)
            for panel in project.panels
        ]
        comic_page = compose_comic(panel_images, project.title)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        safe_theme = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", project.theme).strip("_")
        safe_theme = safe_theme[:30] or "comic"
        output_path = self.output_dir / f"{timestamp}_{safe_theme}.png"
        comic_page.save(output_path, format="PNG")
        project.output_path = output_path
        return comic_page
