"""Comic-page composition helpers."""

import math

from PIL import Image, ImageDraw, ImageFont, ImageOps

from comicforge_ai.bubble_renderer import BubbleRenderResult, render_panel_text
from comicforge_ai.schemas import (
    ContentLanguage,
    CustomPanelFrame,
    LayoutMode,
    LetteringStyle,
    PanelSpec,
)

CUSTOM_FRAME_LABELS = {
    "square": "方形半行（1:1，需成对）",
    "portrait": "竖幅半行（3:4，需成对）",
    "landscape": "横向通栏（16:9）",
    "wide": "超宽通栏（2:1）",
}


def prepare_real_panel_for_layout(
    image: Image.Image,
    panel: PanelSpec,
    size: tuple[int, int] = (720, 480),
    language: ContentLanguage = "zh-CN",
    bubble_theme: str = "classic",
    lettering_style: LetteringStyle = "immersive",
    show_narration: bool = True,
    show_panel_numbers: bool = False,
) -> Image.Image:
    """Backward-compatible wrapper around the structured bubble renderer."""
    return prepare_panel_with_bubbles(
        image,
        panel,
        size=size,
        language=language,
        bubble_theme=bubble_theme,
        lettering_style=lettering_style,
        show_narration=show_narration,
        show_panel_numbers=show_panel_numbers,
    ).image


def prepare_panel_with_bubbles(
    image: Image.Image,
    panel: PanelSpec,
    *,
    size: tuple[int, int] = (720, 480),
    language: ContentLanguage = "zh-CN",
    bubble_theme: str = "classic",
    lettering_style: LetteringStyle = "immersive",
    show_narration: bool = True,
    show_panel_numbers: bool = False,
) -> BubbleRenderResult:
    """Normalize one image and render structured comic lettering."""
    prepared = ImageOps.fit(
        image.convert("RGB"),
        size,
        method=Image.Resampling.LANCZOS,
    )
    return render_panel_text(
        prepared,
        panel,
        language=language,
        theme_name=bubble_theme,
        lettering_style=lettering_style,
        show_narration=show_narration,
        show_panel_numbers=show_panel_numbers,
    )


def compose_comic(
    panels: list[Image.Image],
    title: str,
    columns: int = 2,
    gap: int = 24,
    margin: int = 32,
    header_height: int = 100,
    layout_mode: LayoutMode = "grid",
    panel_specs: list[PanelSpec] | None = None,
    custom_layout: list[CustomPanelFrame] | None = None,
) -> Image.Image:
    """Arrange panel images into one comic page.

    Four input panels use the classic 2×2 layout. Other supported counts flow
    through the same two-column grid, leaving unused cells blank.
    """
    if not panels:
        raise ValueError("至少需要一张分镜图片")
    if layout_mode == "webtoon":
        return _compose_webtoon(panels, title, gap=gap, margin=margin)
    if layout_mode == "adaptive_page":
        return _compose_adaptive_pages(
            panels,
            title,
            panel_specs=panel_specs or [],
            gap=max(12, gap - 6),
            margin=margin,
        )
    if layout_mode == "custom_page":
        return _compose_custom_page(
            panels,
            title,
            custom_layout=custom_layout or [],
            gap=max(12, gap - 6),
            margin=margin,
        )

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


def validate_custom_layout(
    frames: list[CustomPanelFrame],
    panel_count: int,
) -> None:
    """Reject custom layouts that would create gaps or ambiguous panel mapping."""
    if not frames:
        raise ValueError("自定义画框为空，请先选择画框类型并点击“＋ 添加画框”")
    expected = list(range(1, panel_count + 1))
    if [frame.sequence for frame in frames] != expected:
        raise ValueError("自定义画框数量和分镜数量必须一致，且编号须从 1 连续递增")
    index = 0
    while index < len(frames):
        frame = frames[index]
        if frame.frame_type in {"landscape", "wide"}:
            index += 1
            continue
        if index + 1 >= len(frames):
            raise ValueError(
                f"第 {frame.sequence} 格是半行画框，还需要添加一个同类型画框组成完整一行"
            )
        partner = frames[index + 1]
        if partner.frame_type != frame.frame_type:
            raise ValueError(
                f"第 {frame.sequence}、{partner.sequence} 格必须使用相同的半行画框类型"
            )
        index += 2


def custom_panel_render_size(frame: CustomPanelFrame | None) -> tuple[int, int]:
    """Return the lettering canvas ratio for one custom frame."""
    if frame is None:
        return (720, 480)
    return {
        "square": (720, 720),
        "portrait": (540, 720),
        "landscape": (960, 540),
        "wide": (1080, 540),
    }[frame.frame_type]


def custom_frame_for_sequence(
    frames: list[CustomPanelFrame],
    sequence: int,
) -> CustomPanelFrame | None:
    """Find the frame associated with a storyboard panel."""
    return next((frame for frame in frames if frame.sequence == sequence), None)


def custom_frame_prompt(frame: CustomPanelFrame | None) -> str:
    """Describe the target crop so image prompts can reserve a safe composition."""
    if frame is None:
        return ""
    return {
        "square": "目标画框为 1:1 方形半行画框，主体居中，四周保留安全裁切空间",
        "portrait": "目标画框为 3:4 竖幅半行画框，采用纵向构图，主体上下层次清楚",
        "landscape": "目标画框为 16:9 横向通栏，采用宽景构图，关键主体不要贴近左右边缘",
        "wide": "目标画框为 2:1 超宽通栏，采用电影式横向构图，关键主体集中在中央安全区",
    }[frame.frame_type]


def panel_target_aspect_ratio(
    layout_mode: LayoutMode,
    panel_specs: list[PanelSpec],
    sequence: int,
    custom_layout: list[CustomPanelFrame] | None = None,
) -> float:
    """Return the final page-cell ratio assigned to one storyboard panel."""
    if layout_mode == "custom_page":
        frame = custom_frame_for_sequence(custom_layout or [], sequence)
        if frame is not None:
            return {
                "square": 1.0,
                "portrait": 3 / 4,
                "landscape": 16 / 9,
                "wide": 2.0,
            }[frame.frame_type]
    if layout_mode != "adaptive_page":
        return 3 / 2
    panel_index = next(
        (
            index
            for index, panel in enumerate(panel_specs)
            if panel.sequence == sequence
        ),
        max(0, sequence - 1),
    )
    page_index, index_on_page = divmod(panel_index, 6)
    chunk = panel_specs[page_index * 6 : page_index * 6 + 6]
    if not chunk or index_on_page >= len(chunk):
        return 3 / 2
    template = _adaptive_template(
        len(chunk),
        [panel.importance for panel in chunk],
    )
    _, _, normalized_width, normalized_height = template[index_on_page]
    page_width = 1536
    page_height = 1120
    margin = 32
    header = 110 if page_index == 0 else 42
    content_width = page_width - margin * 2
    content_height = page_height - (header + 16) - margin
    return (normalized_width * content_width) / (
        normalized_height * content_height
    )


def _custom_rows(
    frames: list[CustomPanelFrame],
) -> list[list[CustomPanelFrame]]:
    rows: list[list[CustomPanelFrame]] = []
    index = 0
    while index < len(frames):
        frame = frames[index]
        if frame.frame_type in {"square", "portrait"}:
            rows.append([frame, frames[index + 1]])
            index += 2
        else:
            rows.append([frame])
            index += 1
    return rows


def _compose_custom_page(
    panels: list[Image.Image],
    title: str,
    *,
    custom_layout: list[CustomPanelFrame],
    gap: int,
    margin: int,
) -> Image.Image:
    """Compose an explicitly selected, gap-free row-based comic page."""
    validate_custom_layout(custom_layout, len(panels))
    page_width = 1536
    header_height = 110
    content_width = page_width - margin * 2
    half_width = (content_width - gap) // 2
    rows = _custom_rows(custom_layout)
    row_heights = [
        (
            half_width
            if row[0].frame_type == "square"
            else round(half_width * 4 / 3)
        )
        if len(row) == 2
        else (
            round(content_width * 9 / 16)
            if row[0].frame_type == "landscape"
            else round(content_width / 2)
        )
        for row in rows
    ]
    page_height = (
        header_height
        + margin
        + sum(row_heights)
        + gap * (len(rows) - 1)
        + margin
    )
    page = Image.new("RGB", (page_width, page_height), "#FAF7F0")
    draw = ImageDraw.Draw(page)
    _draw_title(draw, title, page_width, margin, header_height)
    by_sequence = dict(zip(range(1, len(panels) + 1), panels, strict=True))
    top = header_height + margin
    for row, row_height in zip(rows, row_heights, strict=True):
        for column, frame in enumerate(row):
            width = half_width if len(row) == 2 else content_width
            left = margin + column * (half_width + gap)
            fitted = ImageOps.fit(
                by_sequence[frame.sequence].convert("RGB"),
                (width, row_height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            framed = ImageOps.expand(fitted, border=3, fill="#171717")
            page.paste(framed, (left, top))
        top += row_height + gap
    return page


def _compose_webtoon(
    panels: list[Image.Image],
    title: str,
    *,
    gap: int,
    margin: int,
) -> Image.Image:
    """Compose a vertically scrolling webtoon with generous reading rhythm."""
    content_width = max(panel.width for panel in panels)
    header_height = 120
    vertical_gap = max(56, gap * 3)
    page_width = content_width + margin * 2
    page_height = (
        header_height
        + margin
        + sum(panel.height for panel in panels)
        + vertical_gap * (len(panels) - 1)
        + margin
    )
    page = Image.new("RGB", (page_width, page_height), "#FFFFFF")
    draw = ImageDraw.Draw(page)
    _draw_title(draw, title, page_width, margin, header_height)
    y = header_height + margin
    for panel in panels:
        x = (page_width - panel.width) // 2
        framed = ImageOps.expand(panel.convert("RGB"), border=2, fill="#202020")
        page.paste(framed, (x - 2, y - 2))
        y += panel.height + vertical_gap
    return page


def _compose_adaptive_pages(
    panels: list[Image.Image],
    title: str,
    *,
    panel_specs: list[PanelSpec],
    gap: int,
    margin: int,
) -> Image.Image:
    """Compose traditional pages; keep four-panel pages balanced and filled."""
    page_width = 1536
    page_height = 1120
    chunks = [panels[index : index + 6] for index in range(0, len(panels), 6)]
    spec_chunks = [
        panel_specs[index : index + 6]
        for index in range(0, len(panel_specs), 6)
    ]
    page_images: list[Image.Image] = []
    for page_index, chunk in enumerate(chunks):
        page = Image.new("RGB", (page_width, page_height), "#FAF7F0")
        draw = ImageDraw.Draw(page)
        header = 110 if page_index == 0 else 42
        if page_index == 0:
            _draw_title(draw, title, page_width, margin, header)
        else:
            page_label = f"— {page_index + 1} —"
            font = _load_title_font(20)
            width = draw.textbbox((0, 0), page_label, font=font)[2]
            draw.text(((page_width - width) / 2, 8), page_label, font=font, fill="#6B6257")
        content_top = header + 16
        content_width = page_width - margin * 2
        content_height = page_height - content_top - margin
        importances = (
            [item.importance for item in spec_chunks[page_index]]
            if page_index < len(spec_chunks)
            else []
        )
        template = _adaptive_template(len(chunk), importances)
        for panel, normalized in zip(chunk, template, strict=True):
            x, y, width, height = normalized
            left = margin + int(x * content_width)
            top = content_top + int(y * content_height)
            box_width = max(80, int(width * content_width) - gap)
            box_height = max(80, int(height * content_height) - gap)
            fitted = _fit_panel_to_cell(
                panel,
                (box_width, box_height),
            )
            framed = ImageOps.expand(fitted, border=3, fill="#171717")
            page.paste(framed, (left, top))
        page_images.append(page)
    if len(page_images) == 1:
        return page_images[0]
    separator = 40
    book = Image.new(
        "RGB",
        (page_width, len(page_images) * page_height + (len(page_images) - 1) * separator),
        "#D8D2C8",
    )
    y = 0
    for page in page_images:
        book.paste(page, (0, y))
        y += page_height + separator
    return book


def _adaptive_template(
    count: int,
    importances: list[int] | None = None,
) -> list[tuple[float, float, float, float]]:
    importance = importances or [3] * count
    two_split = (
        0.64
        if count >= 2 and importance[0] >= importance[1]
        else 0.36
    )
    templates: dict[int, list[tuple[float, float, float, float]]] = {
        1: [(0, 0, 1, 1)],
        2: [(0, 0, two_split, 1), (two_split, 0, 1 - two_split, 1)],
        3: [(0, 0, 1, 0.56), (0, 0.56, 0.48, 0.44), (0.48, 0.56, 0.52, 0.44)],
        4: [
            (0, 0, 0.50, 0.50),
            (0.50, 0, 0.50, 0.50),
            (0, 0.50, 0.50, 0.50),
            (0.50, 0.50, 0.50, 0.50),
        ],
        5: [
            (0, 0, 1, 0.42),
            (0, 0.42, 0.50, 0.29),
            (0.50, 0.42, 0.50, 0.29),
            (0, 0.71, 0.40, 0.29),
            (0.40, 0.71, 0.60, 0.29),
        ],
        6: [
            (0, 0, 0.66, 0.38),
            (0.66, 0, 0.34, 0.38),
            (0, 0.38, 0.34, 0.31),
            (0.34, 0.38, 0.66, 0.31),
            (0, 0.69, 0.50, 0.31),
            (0.50, 0.69, 0.50, 0.31),
        ],
    }
    return templates[count]


def _fit_panel_to_cell(
    panel: Image.Image,
    size: tuple[int, int],
) -> Image.Image:
    """Fill the assigned comic frame without synthetic letterbox sidebars.

    Comic frames consistently use a cover crop: Provider requests already target
    the intended frame ratio, and any small residual mismatch is safer to trim
    than to turn into conspicuous blurred bands in the finished page.
    """
    source = panel.convert("RGB")
    return ImageOps.fit(
        source,
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _draw_title(
    draw: ImageDraw.ImageDraw,
    title: str,
    page_width: int,
    margin: int,
    header_height: int,
) -> None:
    title_font = _load_title_font(42)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_box[2] - title_box[0]
    draw.text(
        ((page_width - title_width) / 2, 24),
        title,
        font=title_font,
        fill="#1F2937",
    )
    draw.line(
        (margin, header_height - 10, page_width - margin, header_height - 10),
        fill="#1F2937",
        width=3,
    )


def _load_title_font(size: int) -> ImageFont.FreeTypeFont:
    from comicforge_ai.models.mock_image import MockImageModel

    for path in MockImageModel._font_candidates(bold=True):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.truetype("DejaVuSans.ttf", size=size)
