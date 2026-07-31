"""Application service orchestrating mock text, image, and layout models."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from PIL import Image

from comicforge_ai.layout import compose_comic
from comicforge_ai.models import MockImageModel, MockTextModel
from comicforge_ai.schemas import ComicProject


class ComicGenerator:
    """Run the complete local mock comic workflow."""

    def __init__(
        self,
        text_model: MockTextModel | None = None,
        image_model: MockImageModel | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        self.text_model = text_model or MockTextModel()
        self.image_model = image_model or MockImageModel()
        configured_dir = output_dir or os.getenv("COMICFORGE_OUTPUT_DIR", "outputs")
        self.output_dir = Path(configured_dir)

    def generate(
        self,
        theme: str,
        style: str,
        panel_count: int = 4,
    ) -> tuple[ComicProject, Image.Image]:
        """Generate a structured project, all panel images, and one PNG page."""
        project = self.text_model.generate_project(theme, style, int(panel_count))
        panel_images = [
            self.image_model.generate_panel(panel, project.style)
            for panel in project.panels
        ]
        comic_page = compose_comic(panel_images, project.title)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_theme = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", project.theme).strip("_")
        safe_theme = safe_theme[:30] or "comic"
        output_path = self.output_dir / f"{timestamp}_{safe_theme}.png"
        comic_page.save(output_path, format="PNG")
        project.output_path = output_path
        return project, comic_page

