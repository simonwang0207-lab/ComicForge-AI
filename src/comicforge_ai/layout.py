"""Comic-page composition helpers."""

import math

from PIL import Image, ImageDraw, ImageFont


def compose_comic(
    panels: list[Image.Image],
    title: str,
    columns: int = 2,
    gap: int = 24,
    margin: int = 32,
    header_height: int = 100,
) -> Image.Image:
    """Arrange panel images into one comic page.

    Four input panels use the classic 2×2 layout. Other supported counts flow
    through the same two-column grid, leaving unused cells blank.
    """
    if not panels:
        raise ValueError("至少需要一张分镜图片")

    columns = max(1, min(columns, len(panels)))
    rows = math.ceil(len(panels) / columns)
    panel_width = max(panel.width for panel in panels)
    panel_height = max(panel.height for panel in panels)
    page_width = margin * 2 + columns * panel_width + (columns - 1) * gap
    page_height = (
        header_height + margin + rows * panel_height + (rows - 1) * gap + margin
    )

    page = Image.new("RGB", (page_width, page_height), "#FAF7F0")
    draw = ImageDraw.Draw(page)
    title_font = _load_title_font(42)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_box[2] - title_box[0]
    draw.text(
        ((page_width - title_width) / 2, 28),
        title,
        font=title_font,
        fill="#1F2937",
    )
    draw.line(
        (margin, header_height - 8, page_width - margin, header_height - 8),
        fill="#1F2937",
        width=3,
    )

    for index, panel in enumerate(panels):
        row, column = divmod(index, columns)
        x = margin + column * (panel_width + gap)
        y = header_height + margin + row * (panel_height + gap)
        page.paste(panel.convert("RGB"), (x, y))
    return page


def _load_title_font(size: int) -> ImageFont.FreeTypeFont:
    from comicforge_ai.models.mock_image import MockImageModel

    for path in MockImageModel._font_candidates(bold=True):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.truetype("DejaVuSans.ttf", size=size)

