import math
from itertools import combinations

import pytest
from PIL import Image, ImageChops

from comicforge_ai.bubble_renderer import render_panel_text
from comicforge_ai.schemas import ComicTextItem, NormalizedPoint, PanelSpec


def _panel(items: list[ComicTextItem]) -> PanelSpec:
    return PanelSpec(
        sequence=1,
        scene="测试场景",
        visual_description="两名角色分列左右",
        characters=["甲", "乙"],
        action="角色正在交谈",
        dialogue="",
        narration="",
        image_prompt="test",
        text_items=items,
    )


def _area(rect: tuple[int, int, int, int]) -> int:
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def _intersection(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> int:
    return max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0,
        min(first[3], second[3]) - max(first[1], second[1]),
    )


def test_all_text_types_have_distinct_safe_placements() -> None:
    items = [
        ComicTextItem(
            type="speech",
            speaker="甲",
            text="我们现在出发！",
            preferred_position="top_left",
            speaker_anchor=NormalizedPoint(x=0.25, y=0.72),
        ),
        ComicTextItem(
            type="thought",
            speaker="乙",
            text="但愿计划顺利……",
            preferred_position="top_right",
            speaker_anchor=NormalizedPoint(x=0.75, y=0.7),
        ),
        ComicTextItem(
            type="narration",
            text="夜幕悄然降临。",
            preferred_position="middle_left",
        ),
        ComicTextItem(
            type="sfx",
            text="轰！",
            preferred_position="bottom_right",
        ),
    ]
    source = Image.new("RGB", (720, 480), "#BFD6E8")

    result = render_panel_text(source, _panel(items))

    assert [item.type for item in result.placements] == [
        "speech",
        "thought",
        "narration",
        "sfx",
    ]
    assert result.placements[0].tail_tip is not None
    assert result.placements[1].tail_tip is not None
    assert result.placements[2].tail_tip is None
    assert ImageChops.difference(source, result.image).getbbox() is not None
    for placement in result.placements:
        left, top, right, bottom = placement.rect
        assert 0 <= left < right <= 720
        assert 0 <= top < bottom <= 480
        assert right - left < 720 * 0.6
    for first, second in combinations(result.placements, 2):
        assert _intersection(first.rect, second.rect) < min(
            _area(first.rect),
            _area(second.rect),
        )


def test_long_text_wraps_scales_and_emits_visible_warning() -> None:
    long_text = "这是一段非常长的漫画对白" * 20
    item = ComicTextItem(
        type="speech",
        text=long_text,
        preferred_position="top_center",
        speaker_anchor=NormalizedPoint(x=0.5, y=0.75),
    )

    result = render_panel_text(Image.new("RGB", (720, 480), "white"), _panel([item]))

    assert result.warnings
    assert "请缩短原文" in result.warnings[0]
    assert result.placements[0].rect[3] <= 480


def test_speech_tail_is_short_and_missing_speaker_has_no_tail() -> None:
    anchored = ComicTextItem(
        type="speech",
        text="短尾巴才像漫画。",
        preferred_position="top_left",
        speaker_anchor=NormalizedPoint(x=0.95, y=0.9),
    )
    unanchored = ComicTextItem(
        type="speech",
        text="不知道说话者时不乱画指示线。",
        preferred_position="top_right",
    )

    result = render_panel_text(
        Image.new("RGB", (720, 480), "white"),
        _panel([anchored, unanchored]),
    )

    first, second = result.placements
    assert first.tail_tip is not None
    left, top, right, bottom = first.rect
    tip_x, tip_y = first.tail_tip
    distance = math.hypot(
        max(left - tip_x, 0, tip_x - right),
        max(top - tip_y, 0, tip_y - bottom),
    )
    assert distance <= 55
    assert second.tail_tip is None


def test_panel_number_is_hidden_by_default_and_can_be_enabled() -> None:
    source = Image.new("RGB", (720, 480), "#9AC7E8")
    panel = _panel(
        [
            ComicTextItem(
                type="speech",
                text="编号默认不属于成品漫画。",
                preferred_position="bottom_right",
            )
        ]
    )

    clean = render_panel_text(source, panel)
    debug = render_panel_text(source, panel, show_panel_numbers=True)

    assert clean.image.getpixel((20, 20)) == source.getpixel((20, 20))
    assert debug.image.getpixel((20, 20)) != source.getpixel((20, 20))


def test_immersive_narration_and_sfx_are_not_ppt_cards() -> None:
    items = [
        ComicTextItem(
            type="narration",
            text="风暴逼近。",
            preferred_position="top_left",
        ),
        ComicTextItem(
            type="sfx",
            text="轰！",
            preferred_position="bottom_right",
        ),
    ]

    result = render_panel_text(Image.new("RGB", (720, 480), "#777777"), _panel(items))

    narration, sfx = result.placements
    assert narration.presentation == "text_only"
    assert narration.background_drawn is False
    assert sfx.presentation == "burst"
    assert sfx.background_drawn is False


def test_lettering_prefers_low_detail_region_over_busy_requested_region() -> None:
    source = Image.new("RGB", (720, 480), "#DDEAF2")
    pixels = source.load()
    for y in range(240):
        for x in range(360):
            pixels[x, y] = (20, 20, 20) if (x + y) % 4 < 2 else (240, 240, 240)
    item = ComicTextItem(
        type="speech",
        text="文字应该避开复杂区域。",
        preferred_position="top_left",
    )

    result = render_panel_text(source, _panel([item]))

    left, _, right, _ = result.placements[0].rect
    assert (left + right) / 2 > 360


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("zh-CN", "提防看似平静的礼物！"),
        ("en", "Beware of gifts that look too peaceful!"),
        ("ja-JP", "静かすぎる贈り物に気をつけて！"),
    ],
)
def test_multilingual_text_renders_without_font_failure(
    language: str,
    text: str,
) -> None:
    item = ComicTextItem(
        type="speech",
        text=text,
        preferred_position="top_left",
        speaker_anchor=NormalizedPoint(x=0.75, y=0.7),
    )
    source = Image.new("RGB", (720, 480), "#EEEEEE")

    result = render_panel_text(source, _panel([item]), language=language)  # type: ignore[arg-type]

    assert ImageChops.difference(source, result.image).getbbox() is not None
    assert result.placements
