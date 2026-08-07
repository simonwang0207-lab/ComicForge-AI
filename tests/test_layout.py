import pytest
from PIL import Image

from comicforge_ai.layout import (
    _adaptive_template,
    _fit_panel_to_cell,
    compose_comic,
    panel_target_aspect_ratio,
)
from comicforge_ai.models import MockTextModel


def test_four_panels_are_composed_as_two_by_two() -> None:
    panels = [Image.new("RGB", (200, 120), "white") for _ in range(4)]

    page = compose_comic(
        panels,
        "测试漫画",
        columns=2,
        gap=10,
        margin=20,
        header_height=60,
    )

    assert page.size == (450, 350)
    assert page.mode == "RGB"


def test_webtoon_and_adaptive_page_have_distinct_reading_shapes() -> None:
    panels = [
        Image.new("RGB", (720, 480), color)
        for color in ("red", "blue", "green", "gold")
    ]

    webtoon = compose_comic(panels, "竖向条漫", layout_mode="webtoon")
    adaptive = compose_comic(panels, "自由漫画页", layout_mode="adaptive_page")

    assert webtoon.height > webtoon.width * 2
    assert adaptive.size == (1536, 1120)
    assert adaptive.getpixel((100, 200)) != adaptive.getpixel((1200, 200))


def test_four_panel_adaptive_page_uses_equal_filled_cells() -> None:
    panels = [
        Image.new("RGB", (720, 480), color)
        for color in ("#D02020", "#2040D0", "#20A040", "#D09020")
    ]

    page = compose_comic(panels, "等幅四格", layout_mode="adaptive_page")
    template = _adaptive_template(4, [5, 1, 4, 2])

    assert template == [
        (0, 0, 0.5, 0.5),
        (0.5, 0, 0.5, 0.5),
        (0, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
    ]
    assert page.getpixel((45, 145)) == (208, 32, 32)
    assert page.getpixel((45, 570)) == (208, 32, 32)
    assert page.getpixel((780, 145)) == (32, 64, 208)


def test_adaptive_page_exposes_each_real_panel_aspect_ratio() -> None:
    project = MockTextModel().generate_project("六格画幅", "清新治愈", 6)
    project.layout_mode = "adaptive_page"

    ratios = [
        panel_target_aspect_ratio(
            project.layout_mode,
            project.panels,
            panel.sequence,
            project.custom_layout,
        )
        for panel in project.panels
    ]

    assert ratios == pytest.approx(
        [2.658, 1.369, 1.678, 3.258, 2.468, 2.468],
        abs=0.001,
    )


def test_irregular_panel_cover_crop_does_not_create_blurred_sidebars() -> None:
    panel = Image.new("RGB", (300, 300), "#D02020")

    fitted = _fit_panel_to_cell(panel, (600, 200))

    assert fitted.size == (600, 200)
    assert fitted.getpixel((0, 100)) == (208, 32, 32)
    assert fitted.getpixel((599, 100)) == (208, 32, 32)
