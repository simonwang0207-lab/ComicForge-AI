"""Generate offline visual QA samples for every supported comic layout mode."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from comicforge_ai.schemas import CustomPanelFrame
from comicforge_ai.service import ComicGenerator, ImageGenerationOptions


def main() -> None:
    output_dir = Path("outputs/layout_preview")
    output_dir.mkdir(parents=True, exist_ok=True)
    generator = ComicGenerator(
        output_dir=output_dir,
        image_fallback_to_mock=False,
    )
    for mode in ("grid", "webtoon", "adaptive_page"):
        result = generator.generate_auto_with_status(
            "古城夜间救援",
            "复古漫画",
            4,
            text_provider_id="mock",
            image_provider_id="mock-image",
            layout_mode=mode,  # type: ignore[arg-type]
            allow_multi_shot_panels=True,
            image_options=ImageGenerationOptions(),
        )
        preview_path = output_dir / f"{mode}.png"
        result.comic_page.save(preview_path, format="PNG")
        print(f"{mode}: {preview_path.resolve()} {result.comic_page.size}")

    script = generator.generate_script_with_status(
        "古城夜间救援",
        "复古漫画",
        6,
        "mock",
    )
    script.project.layout_mode = "custom_page"
    script.project.custom_layout = [
        *[
            CustomPanelFrame(sequence=index, frame_type="square")
            for index in range(1, 5)
        ],
        CustomPanelFrame(sequence=5, frame_type="wide"),
        CustomPanelFrame(sequence=6, frame_type="wide"),
    ]
    custom = generator.render_confirmed_project(
        script.project,
        "mock-image",
        ImageGenerationOptions(),
    )
    custom_path = output_dir / "custom_page.png"
    custom.comic_page.save(custom_path, format="PNG")
    print(f"custom_page: {custom_path.resolve()} {custom.comic_page.size}")


if __name__ == "__main__":
    main()
