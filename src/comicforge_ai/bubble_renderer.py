"""Pillow-based comic lettering that remains independent of image providers."""

from __future__ import annotations

import math
import platform
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from comicforge_ai.schemas import (
    ComicTextItem,
    ContentLanguage,
    LetteringStyle,
    NormalizedPoint,
    PanelPosition,
    PanelSpec,
)

Color = str | tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class BubbleTheme:
    """Colors and dimensions shared by all lettering styles."""

    fill_color: Color = (255, 253, 247, 224)
    border_color: Color = "#202020"
    border_width: int = 3
    text_color: Color = "#151515"
    narration_fill: Color = (255, 242, 199, 218)
    sfx_fill: Color = "#F04A47"
    padding_x: int = 18
    padding_y: int = 12
    tail_length: int = 48
    min_font_size: int = 16
    max_font_size: int = 28


THEMES = {
    "classic": BubbleTheme(),
    "manga": BubbleTheme(
        fill_color=(255, 255, 255, 228),
        border_color="#111111",
        narration_fill=(255, 255, 255, 216),
        border_width=4,
    ),
    "modern": BubbleTheme(
        fill_color=(248, 251, 255, 220),
        border_color="#25324A",
        narration_fill=(231, 240, 255, 214),
        sfx_fill="#FF5A5F",
    ),
}


@dataclass(frozen=True, slots=True)
class BubblePlacement:
    type: str
    rect: tuple[int, int, int, int]
    tail_tip: tuple[int, int] | None = None
    presentation: str = "auto"
    background_drawn: bool = False


@dataclass(slots=True)
class BubbleRenderResult:
    image: Image.Image
    placements: list[BubblePlacement]
    warnings: list[str]


def render_panel_text(
    image: Image.Image,
    panel: PanelSpec,
    *,
    language: ContentLanguage = "zh-CN",
    theme_name: str = "classic",
    lettering_style: LetteringStyle = "immersive",
    show_narration: bool = True,
    show_panel_numbers: bool = False,
) -> BubbleRenderResult:
    """Render structured lettering with optional legacy-compatible styling.

    ``immersive`` uses translucent organic bubbles, outlined narration and
    expressive sound effects. ``classic`` preserves the original ellipse/card
    appearance. ``minimal`` removes all backgrounds except explicit captions.
    """
    theme = THEMES.get(theme_name, THEMES["classic"])
    canvas = image.convert("RGBA")
    source = image.convert("RGB")
    visual_edges = source.convert("L").filter(ImageFilter.FIND_EDGES)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    placements: list[BubblePlacement] = []
    warnings: list[str] = []
    occupied: list[tuple[int, int, int, int]] = []
    if show_panel_numbers:
        occupied.append((12, 12, 62, 62))
        _draw_panel_number(draw, panel.sequence, language)

    for index, item in enumerate(panel.text_items):
        if item.type == "narration" and not show_narration:
            continue
        clean = _clean_text(item)
        if not clean:
            continue
        presentation = _resolve_presentation(item, lettering_style)
        font, lines, text_size, shortened = _fit_text(
            clean,
            item.type,
            presentation,
            language,
            canvas.size,
            theme,
        )
        if shortened:
            warnings.append(
                f"第 {panel.sequence} 格第 {index + 1} 个文字项过长，"
                "已显示省略号；请缩短原文。"
            )
        rect = _choose_rect(
            item.preferred_position,
            text_size,
            canvas.size,
            occupied,
            theme,
            visual_edges,
        )
        occupied.append(rect)
        placement = _draw_item(
            overlay,
            draw,
            source,
            item,
            presentation,
            lettering_style,
            rect,
            lines,
            font,
            canvas.size,
            theme,
        )
        placements.append(placement)

    return BubbleRenderResult(
        image=Image.alpha_composite(canvas, overlay).convert("RGB"),
        placements=placements,
        warnings=warnings,
    )


def _resolve_presentation(item: ComicTextItem, style: LetteringStyle) -> str:
    if item.presentation != "auto":
        return item.presentation
    if item.type == "sfx":
        return "burst"
    if style == "minimal":
        return "text_only"
    if item.type in {"speech", "thought"}:
        return "bubble"
    if item.type == "narration" and style == "classic":
        return "caption"
    return "text_only"


def _draw_panel_number(
    draw: ImageDraw.ImageDraw,
    sequence: int,
    language: ContentLanguage,
) -> None:
    font = load_comic_font(language, 24, bold=True)
    draw.ellipse((12, 12, 62, 62), fill="#202938", outline="#FFFFFF", width=2)
    text = str(sequence)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (37 - (box[2] - box[0]) / 2, 20),
        text,
        font=font,
        fill="#FFFFFF",
    )


def _clean_text(item: ComicTextItem) -> str:
    clean = " ".join(item.text.splitlines()).strip()
    if item.type in {"speech", "thought"}:
        clean = clean.strip("“”『』「」\"'")
    return clean


def _fit_text(
    text: str,
    item_type: str,
    presentation: str,
    language: ContentLanguage,
    panel_size: tuple[int, int],
    theme: BubbleTheme,
) -> tuple[ImageFont.FreeTypeFont, list[str], tuple[int, int], bool]:
    if item_type == "sfx" or presentation == "burst":
        max_width = min(340, int(panel_size[0] * 0.48))
        max_height = min(190, int(panel_size[1] * 0.38))
        start_font_size = max(42, theme.max_font_size + 18)
        minimum = max(24, theme.min_font_size)
    elif item_type == "narration":
        max_width = min(300, int(panel_size[0] * 0.42))
        max_height = min(118, int(panel_size[1] * 0.24))
        start_font_size = min(24, theme.max_font_size)
        minimum = theme.min_font_size
    else:
        max_width = min(300, int(panel_size[0] * 0.43))
        max_height = min(170, int(panel_size[1] * 0.35))
        start_font_size = theme.max_font_size
        minimum = theme.min_font_size
    padding_x = 8 if presentation == "text_only" else theme.padding_x
    padding_y = 6 if presentation == "text_only" else theme.padding_y
    shortened = False
    for size in range(start_font_size, minimum - 1, -2):
        font = load_comic_font(
            language,
            size,
            bold=item_type in {"narration", "sfx"},
        )
        lines = wrap_text(text, font, max_width - padding_x * 2, language)
        line_height = _line_height(font)
        width = max(_text_width(line, font) for line in lines) + padding_x * 2
        height = len(lines) * line_height + padding_y * 2
        if width <= max_width and height <= max_height:
            return font, lines, (width, height), shortened

    font = load_comic_font(
        language,
        minimum,
        bold=item_type in {"narration", "sfx"},
    )
    lines = wrap_text(text, font, max_width - padding_x * 2, language)
    line_height = _line_height(font)
    max_lines = max(1, (max_height - padding_y * 2) // line_height)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1], font, max_width - padding_x * 2)
        shortened = True
    width = max(_text_width(line, font) for line in lines) + padding_x * 2
    height = len(lines) * line_height + padding_y * 2
    return font, lines, (min(width, max_width), min(height, max_height)), shortened


def wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    language: ContentLanguage,
) -> list[str]:
    """Wrap English by words and CJK by characters with punctuation safeguards."""
    if language == "en":
        units = text.split()
        separator = " "
    else:
        units = list(text.replace(" ", ""))
        separator = ""
    lines: list[str] = []
    current = ""
    closing = set("，。！？、；：,.!?)]}》』」）】")
    for unit in units:
        candidate = unit if not current else current + separator + unit
        if current and _text_width(candidate, font) > max_width:
            if unit in closing:
                current += unit
            else:
                lines.append(current)
                current = unit
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _choose_rect(
    preferred: PanelPosition,
    text_size: tuple[int, int],
    panel_size: tuple[int, int],
    occupied: list[tuple[int, int, int, int]],
    theme: BubbleTheme,
    visual_edges: Image.Image,
) -> tuple[int, int, int, int]:
    candidates: list[PanelPosition] = [
        preferred,
        "top_left",
        "top_right",
        "middle_left",
        "middle_right",
        "bottom_left",
        "bottom_right",
        "top_center",
    ]
    unique = list(dict.fromkeys(candidates))
    rects = [_rect_for_position(item, text_size, panel_size, theme) for item in unique]

    def score(candidate: tuple[int, int, int, int]) -> float:
        overlap = sum(_intersection_area(candidate, other) for other in occupied)
        crop = visual_edges.crop(candidate)
        complexity = ImageStat.Stat(crop).mean[0] if crop.width and crop.height else 255
        preferred_penalty = rects.index(candidate) * 28
        return overlap * 100 + complexity * 8 + preferred_penalty

    return min(rects, key=score)


def _rect_for_position(
    position: PanelPosition,
    text_size: tuple[int, int],
    panel_size: tuple[int, int],
    theme: BubbleTheme,
) -> tuple[int, int, int, int]:
    width, height = text_size
    panel_width, panel_height = panel_size
    margin = max(14, theme.border_width * 4)
    centers = {
        "top_left": (margin + width / 2 + 32, margin + height / 2),
        "top_center": (panel_width / 2, margin + height / 2),
        "top_right": (panel_width - margin - width / 2, margin + height / 2),
        "middle_left": (margin + width / 2, panel_height / 2),
        "middle_right": (panel_width - margin - width / 2, panel_height / 2),
        "bottom_left": (margin + width / 2, panel_height - margin - height / 2),
        "bottom_right": (
            panel_width - margin - width / 2,
            panel_height - margin - height / 2,
        ),
    }
    center_x, center_y = centers[position]
    left = int(max(margin, min(center_x - width / 2, panel_width - margin - width)))
    top = int(max(margin, min(center_y - height / 2, panel_height - margin - height)))
    return left, top, left + width, top + height


def _draw_item(
    overlay: Image.Image,
    draw: ImageDraw.ImageDraw,
    source: Image.Image,
    item: ComicTextItem,
    presentation: str,
    lettering_style: LetteringStyle,
    rect: tuple[int, int, int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    panel_size: tuple[int, int],
    theme: BubbleTheme,
) -> BubblePlacement:
    if presentation == "burst":
        _draw_sfx(overlay, rect, lines, font, theme)
        return BubblePlacement(
            type=item.type,
            rect=rect,
            presentation=presentation,
        )
    if presentation == "text_only":
        fill, stroke = _contrasting_text_colors(source, rect)
        _draw_lines(
            draw,
            rect,
            lines,
            font,
            fill,
            theme,
            stroke_width=3,
            stroke_fill=stroke,
            compact=True,
        )
        return BubblePlacement(
            type=item.type,
            rect=rect,
            presentation=presentation,
        )

    tail_tip: tuple[int, int] | None = None
    if presentation == "caption":
        _draw_caption(draw, rect, theme)
    elif item.type == "thought":
        _draw_organic_bubble(draw, rect, theme, cloud=True)
        target = _tail_target(item, panel_size)
        if target is not None:
            base, tail_tip = _limited_tail(rect, target, theme.tail_length + 12)
            _draw_thought_tail(draw, base, tail_tip, rect, theme)
    else:
        target = _tail_target(item, panel_size)
        if target is not None:
            base, tail_tip = _limited_tail(rect, target, theme.tail_length)
        if lettering_style == "classic":
            draw.ellipse(
                rect,
                fill=theme.fill_color,
                outline=theme.border_color,
                width=theme.border_width,
            )
        else:
            _draw_organic_bubble(draw, rect, theme, cloud=False)
        if target is not None:
            _draw_speech_tail(draw, base, tail_tip, theme)

    _draw_lines(draw, rect, lines, font, theme.text_color, theme)
    return BubblePlacement(
        type=item.type,
        rect=rect,
        tail_tip=tail_tip,
        presentation=presentation,
        background_drawn=True,
    )


def _draw_organic_bubble(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    theme: BubbleTheme,
    *,
    cloud: bool,
) -> None:
    center_x = (rect[0] + rect[2]) / 2
    center_y = (rect[1] + rect[3]) / 2
    radius_x = max(4.0, (rect[2] - rect[0]) / 2)
    radius_y = max(4.0, (rect[3] - rect[1]) / 2)
    points: list[tuple[int, int]] = []
    for index in range(48):
        angle = math.tau * index / 48
        if cloud:
            wobble = 1 + 0.055 * math.sin(angle * 8) + 0.025 * math.sin(angle * 13)
        else:
            wobble = 1 + 0.018 * math.sin(angle * 5) + 0.014 * math.sin(angle * 9)
        points.append(
            (
                int(center_x + radius_x * wobble * math.cos(angle)),
                int(center_y + radius_y * wobble * math.sin(angle)),
            )
        )
    draw.polygon(points, fill=theme.fill_color)
    draw.line(
        [*points, points[0]],
        fill=theme.border_color,
        width=theme.border_width,
        joint="curve",
    )


def _draw_speech_tail(
    draw: ImageDraw.ImageDraw,
    base: tuple[int, int],
    tip: tuple[int, int],
    theme: BubbleTheme,
) -> None:
    points = [(base[0] - 7, base[1]), tip, (base[0] + 7, base[1])]
    draw.polygon(points, fill=theme.fill_color)
    draw.line(points[:2], fill=theme.border_color, width=theme.border_width)
    draw.line(points[1:], fill=theme.border_color, width=theme.border_width)


def _draw_thought_tail(
    draw: ImageDraw.ImageDraw,
    base: tuple[int, int],
    tip: tuple[int, int],
    rect: tuple[int, int, int, int],
    theme: BubbleTheme,
) -> None:
    for ratio, offset in ((0.08, 0.12), (0.055, 0.52), (0.032, 0.88)):
        radius = max(3, int((rect[2] - rect[0]) * ratio))
        x = int(base[0] + (tip[0] - base[0]) * offset)
        y = int(base[1] + (tip[1] - base[1]) * offset)
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=theme.fill_color,
            outline=theme.border_color,
            width=max(1, theme.border_width - 1),
        )


def _draw_caption(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    theme: BubbleTheme,
) -> None:
    cut = 9
    left, top, right, bottom = rect
    draw.polygon(
        [
            (left + cut, top),
            (right, top),
            (right, bottom - cut),
            (right - cut, bottom),
            (left, bottom),
            (left, top + cut),
        ],
        fill=theme.narration_fill,
        outline=theme.border_color,
    )


def _draw_sfx(
    overlay: Image.Image,
    rect: tuple[int, int, int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    theme: BubbleTheme,
) -> None:
    width = max(1, rect[2] - rect[0] + 36)
    height = max(1, rect[3] - rect[1] + 36)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    line_height = _line_height(font)
    y = max(8, (height - len(lines) * line_height) // 2)
    for line in lines:
        text_width = _text_width(line, font)
        x = (width - text_width) / 2
        layer_draw.text(
            (x, y),
            line,
            font=font,
            fill=theme.sfx_fill,
            stroke_width=6,
            stroke_fill="#FFFDF7",
        )
        layer_draw.text(
            (x, y),
            line,
            font=font,
            fill=theme.sfx_fill,
            stroke_width=2,
            stroke_fill="#171717",
        )
        y += line_height
    angle = -7 if (rect[0] + rect[2]) / 2 < overlay.width / 2 else 7
    rotated = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    x = int((rect[0] + rect[2] - rotated.width) / 2)
    y = int((rect[1] + rect[3] - rotated.height) / 2)
    overlay.alpha_composite(rotated, (x, y))


def _contrasting_text_colors(
    source: Image.Image,
    rect: tuple[int, int, int, int],
) -> tuple[str, str]:
    crop = source.convert("L").crop(rect)
    brightness = ImageStat.Stat(crop).mean[0] if crop.width and crop.height else 255
    if brightness < 120:
        return "#FFFDF7", "#161616"
    return "#161616", "#FFFDF7"


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    fill: Color,
    theme: BubbleTheme,
    *,
    stroke_width: int = 0,
    stroke_fill: Color | None = None,
    compact: bool = False,
) -> None:
    line_height = _line_height(font)
    padding_y = 6 if compact else theme.padding_y
    y = rect[1] + padding_y
    for line in lines:
        width = _text_width(line, font)
        x = rect[0] + (rect[2] - rect[0] - width) / 2
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        y += line_height


def _tail_target(
    item: ComicTextItem,
    panel_size: tuple[int, int],
) -> tuple[int, int] | None:
    if item.speaker_anchor is None and item.speaker_position is None:
        return None
    point = item.speaker_anchor or _point_for_position(item.speaker_position)
    return int(point.x * panel_size[0]), int(point.y * panel_size[1])


def _limited_tail(
    rect: tuple[int, int, int, int],
    target: tuple[int, int],
    max_length: int,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Point toward a speaker without drawing a line across the entire panel."""
    base = _tail_base(rect, target)
    delta_x = target[0] - base[0]
    delta_y = target[1] - base[1]
    distance = max(1.0, math.hypot(delta_x, delta_y))
    length = min(float(max_length), distance)
    tip = (
        int(base[0] + delta_x / distance * length),
        int(base[1] + delta_y / distance * length),
    )
    return base, tip


def _point_for_position(position: PanelPosition | None) -> NormalizedPoint:
    points = {
        "top_left": (0.25, 0.25),
        "top_center": (0.5, 0.25),
        "top_right": (0.75, 0.25),
        "middle_left": (0.25, 0.5),
        "middle_right": (0.75, 0.5),
        "bottom_left": (0.25, 0.75),
        "bottom_right": (0.75, 0.75),
    }
    x, y = points.get(position or "bottom_right", (0.75, 0.75))
    return NormalizedPoint(x=x, y=y)


def _tail_base(
    rect: tuple[int, int, int, int],
    tip: tuple[int, int],
) -> tuple[int, int]:
    center_x = (rect[0] + rect[2]) // 2
    if tip[1] >= rect[3]:
        return max(rect[0] + 16, min(tip[0], rect[2] - 16)), rect[3] - 2
    if tip[1] <= rect[1]:
        return max(rect[0] + 16, min(tip[0], rect[2] - 16)), rect[1] + 2
    return (
        (rect[0] + 2 if tip[0] < center_x else rect[2] - 2),
        max(rect[1] + 16, min(tip[1], rect[3] - 16)),
    )


def _intersection_area(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> int:
    width = max(0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * height


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    clean = text
    while clean and _text_width(clean + "…", font) > max_width:
        clean = clean[:-1]
    return clean + "…"


def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    box = font.getbbox(text or " ")
    return box[2] - box[0]


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    box = font.getbbox("示例Agあ")
    return box[3] - box[1] + 5


def load_comic_font(
    language: ContentLanguage,
    size: int,
    *,
    bold: bool,
) -> ImageFont.FreeTypeFont:
    """Load a language-aware CJK font with readable cross-platform fallbacks."""
    for path in _font_candidates(language, bold):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.truetype("DejaVuSans.ttf", size=size)


def _font_candidates(language: ContentLanguage, bold: bool) -> list[Path]:
    if platform.system() == "Windows":
        root = Path("C:/Windows/Fonts")
        if language == "ja-JP":
            return [
                root / ("YuGothB.ttc" if bold else "YuGothM.ttc"),
                root / ("meiryob.ttc" if bold else "meiryo.ttc"),
                root / ("msyhbd.ttc" if bold else "msyh.ttc"),
            ]
        if language == "en":
            return [
                root / ("arialbd.ttf" if bold else "arial.ttf"),
                root / ("msyhbd.ttc" if bold else "msyh.ttc"),
            ]
        return [
            root / ("msyhbd.ttc" if bold else "msyh.ttc"),
            root / ("simhei.ttf" if bold else "simsun.ttc"),
        ]
    return [
        Path(
            "/usr/share/fonts/opentype/noto/"
            + ("NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc")
        ),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
