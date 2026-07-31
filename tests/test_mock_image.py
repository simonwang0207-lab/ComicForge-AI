from comicforge_ai.models import MockImageModel
from comicforge_ai.schemas import PanelSpec


def test_mock_image_model_returns_expected_image() -> None:
    model = MockImageModel(width=500, height=320)
    panel = PanelSpec(
        number=1,
        scene="主角发现了一张神秘地图。",
        caption="开场",
        dialogue="出发吧！",
    )

    image = model.generate_panel(panel, "清新治愈")

    assert image.mode == "RGB"
    assert image.size == (500, 320)

