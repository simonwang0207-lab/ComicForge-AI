from PIL import Image

from comicforge_ai.layout import compose_comic


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

