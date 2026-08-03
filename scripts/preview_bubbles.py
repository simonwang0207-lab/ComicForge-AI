"""Generate an offline multilingual comic-bubble preview PNG."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PIL import Image, ImageDraw

from comicforge_ai.bubble_renderer import render_panel_text
from comicforge_ai.layout import compose_comic
from comicforge_ai.schemas import (
    ComicTextItem,
    ContentLanguage,
    NormalizedPoint,
    PanelSpec,
)

SAMPLES: dict[ContentLanguage, dict[str, str]] = {
    "zh-CN": {
        "speech": "快看，我们找到线索了！",
        "thought": "这条路真的安全吗？",
        "narration": "夜幕降临，行动开始。",
        "sfx": "轰！",
    },
    "en": {
        "speech": "Look, we found the clue!",
        "thought": "Is this path really safe?",
        "narration": "Night falls. The mission begins.",
        "sfx": "BOOM!",
    },
    "ja-JP": {
        "speech": "見て、手がかりを見つけた！",
        "thought": "この道は本当に安全かな？",
        "narration": "夜が訪れ、作戦が始まる。",
        "sfx": "ドン！",
    },
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/immersive_lettering_preview.png"),
    )
    return parser.parse_args()


def _background(index: int) -> Image.Image:
    colors = ("#CFE8FF", "#FFE0C7", "#DDF4D9", "#E8D9FF")
    image = Image.new("RGB", (600, 400), colors[index % len(colors)])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 285, 600, 400), fill="#A9C9A7")
    draw.ellipse((410, 185, 510, 285), fill="#FF9677", outline="#243047", width=4)
    draw.ellipse((425, 135, 495, 205), fill="#FFD8B8", outline="#243047", width=4)
    return image


def _panel(sequence: int, kind: str, text: str) -> PanelSpec:
    anchor = NormalizedPoint(x=0.77, y=0.62)
    return PanelSpec(
        sequence=sequence,
        scene="offline preview",
        visual_description="character on the right with clean space on the left",
        characters=["Demo"],
        action="preview",
        dialogue=text if kind in {"speech", "thought"} else "",
        narration=text if kind == "narration" else "",
        image_prompt="offline",
        character_positions={"Demo": "middle_right"},
        reserved_bubble_regions=["top_left"],
        text_items=[
            ComicTextItem(
                type=kind,  # type: ignore[arg-type]
                speaker="Demo" if kind in {"speech", "thought"} else None,
                text=text,
                preferred_position="top_left",
                speaker_position="middle_right",
                speaker_anchor=anchor if kind in {"speech", "thought"} else None,
            )
        ],
    )


def main() -> int:
    args = _arguments()
    panels: list[Image.Image] = []
    sequence = 1
    for language, samples in SAMPLES.items():
        for index, kind in enumerate(("speech", "thought", "narration", "sfx")):
            rendered = render_panel_text(
                _background(index),
                _panel(sequence, kind, samples[kind]),
                language=language,
            )
            panels.append(rendered.image)
            sequence += 1
    page = compose_comic(
        panels,
        "ComicForge Bubble Preview · 中文 / English / 日本語",
        columns=4,
        gap=18,
        margin=24,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    page.save(args.output, format="PNG")
    print(f"预览路径: {args.output.resolve()}")
    print(f"预览尺寸: {page.width}x{page.height}")
    print("内容: 三种语言 × speech/thought/narration/sfx，全程离线")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
