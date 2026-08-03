from PIL import Image

from comicforge_ai.layout import _adaptive_template, compose_comic


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
