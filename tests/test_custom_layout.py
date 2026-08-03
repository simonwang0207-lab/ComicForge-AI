import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from comicforge_ai.layout import compose_comic, validate_custom_layout
from comicforge_ai.models import ImageProviderRegistry, MockImageModel, MockTextModel
from comicforge_ai.models.recraft_image import RecraftImageProvider
from comicforge_ai.schemas import CustomPanelFrame, ImageGenerationRequest
from comicforge_ai.service import ComicGenerator, ImageGenerationOptions
from comicforge_ai.ui import (
    edit_custom_layout_for_ui,
    layout_mode_updates,
    sync_custom_layout_for_ui,
    workflow_mode_updates,
)


def _reference_layout() -> list[CustomPanelFrame]:
    return [
        *[
            CustomPanelFrame(sequence=index, frame_type="square")
            for index in range(1, 5)
        ],
        CustomPanelFrame(sequence=5, frame_type="wide"),
        CustomPanelFrame(sequence=6, frame_type="wide"),
    ]


class RecordingMockImageProvider(MockImageModel):
    model_id = "recording-custom-layout"
    display_name = "Recording Custom Layout"

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[ImageGenerationRequest] = []

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ):
        self.requests.append(request.model_copy(deep=True))
        return super().generate(request, output_path)


def _encoded_png() -> str:
    buffer = BytesIO()
    Image.new("RGB", (128, 128), "#55AACC").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_custom_layout_rejects_an_unpaired_half_width_frame() -> None:
    frames = [CustomPanelFrame(sequence=1, frame_type="square")]

    with pytest.raises(ValueError, match="还需要添加一个同类型画框"):
        validate_custom_layout(frames, 1)


def test_four_square_frames_and_two_wide_frames_fill_a_tall_page() -> None:
    colors = ("red", "blue", "green", "gold", "purple", "orange")
    panels = [Image.new("RGB", (900, 600), color) for color in colors]

    page = compose_comic(
        panels,
        "自定义画幅",
        layout_mode="custom_page",
        custom_layout=_reference_layout(),
    )

    assert page.height > page.width
    assert page.getpixel((50, 150)) == (255, 0, 0)
    assert page.getpixel((800, 150)) == (0, 0, 255)
    assert page.getpixel((50, page.height - 50)) == (255, 165, 0)


def test_custom_layout_ui_can_delete_any_selected_frame() -> None:
    state = [
        {"sequence": index, "frame_type": "wide"}
        for index in range(1, 11)
    ]

    state, rows, preview, status, selected = edit_custom_layout_for_ui(
        "delete",
        "square",
        state,
        selected_index=0,
        target_panel_count=10,
    )

    assert len(state) == len(rows) == 9
    assert all(item["frame_type"] == "wide" for item in state)
    assert [item["sequence"] for item in state] == list(range(1, 10))
    assert preview is not None
    assert "9/10" in status
    assert selected == 0


def test_custom_layout_ui_add_requires_a_complete_half_width_pair() -> None:
    state, _, preview, status, _ = edit_custom_layout_for_ui(
        "insert", "square", [], target_panel_count=2
    )
    assert preview is None
    assert "1/2" in status

    state, rows, preview, status, _ = edit_custom_layout_for_ui(
        "insert", "square", state, target_panel_count=2
    )
    assert len(rows) == 2
    assert preview is not None
    assert "布局完整" in status


def test_custom_layout_initializes_and_resizes_from_storyboard_count() -> None:
    state, rows, preview, status, selected = sync_custom_layout_for_ui(
        "custom_page",
        4,
        [],
    )

    assert len(state) == len(rows) == 4
    assert preview is not None
    assert "分镜数量为 4" in status
    assert selected is None

    state, rows, preview, status, _ = sync_custom_layout_for_ui(
        "custom_page",
        5,
        state,
    )

    assert len(state) == len(rows) == 5
    assert state[0]["frame_type"] == "wide"
    assert preview is not None
    assert "分镜数量为 5" in status


def test_custom_layout_cannot_exceed_storyboard_count_and_can_replace_type() -> None:
    state, _, _, _, _ = sync_custom_layout_for_ui("custom_page", 4, [])

    unchanged, _, _, status, _ = edit_custom_layout_for_ui(
        "insert",
        "wide",
        state,
        selected_index=0,
        target_panel_count=4,
    )
    assert unchanged == state
    assert "不能添加第 5 个画框" in status

    replaced, _, _, status, selected = edit_custom_layout_for_ui(
        "replace",
        "wide",
        state,
        selected_index=0,
        target_panel_count=4,
    )
    assert replaced[0]["frame_type"] == "wide"
    assert "1/4" not in status
    assert selected == 0


def test_workflow_mode_hides_manual_actions_and_rejects_custom_auto_layout() -> None:
    manual, automatic, layout, custom, note = workflow_mode_updates(
        "auto",
        "custom_page",
    )

    assert manual["visible"] is False
    assert automatic["visible"] is True
    assert layout["value"] == "adaptive_page"
    assert all(value != "custom_page" for _, value in layout["choices"])
    assert custom["visible"] is False
    assert "一键生成" in note


def test_custom_designer_only_appears_for_manual_custom_layout() -> None:
    custom, custom_note = layout_mode_updates("custom_page", "manual")
    normal, normal_note = layout_mode_updates("adaptive_page", "manual")

    assert custom["visible"] is True
    assert "需要 4 个画框" in custom_note
    assert normal["visible"] is False
    assert "每页最多 6 格" in normal_note


def test_custom_layout_service_uses_per_frame_generation_ratios(
    tmp_path: Path,
) -> None:
    provider = RecordingMockImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("自定义画幅", "复古漫画", 6)
    project.layout_mode = "custom_page"
    project.custom_layout = _reference_layout()

    result = generator.render_confirmed_project(
        project,
        provider.model_id,
        ImageGenerationOptions(),
    )

    assert [(item.width, item.height) for item in provider.requests] == [
        (1024, 1024),
        (1024, 1024),
        (1024, 1024),
        (1024, 1024),
        (1024, 512),
        (1024, 512),
    ]
    assert "目标画框为 1:1 方形半行画框" in provider.requests[0].prompt
    assert "目标画框为 2:1 超宽通栏" in provider.requests[4].prompt
    assert result.comic_page.height > result.comic_page.width
    assert result.project.custom_layout == _reference_layout()
    assert result.project_json_path is not None
    saved = result.project_json_path.read_text(encoding="utf-8")
    assert '"frame_type": "wide"' in saved


def test_invalid_custom_layout_fails_before_spending_image_calls(
    tmp_path: Path,
) -> None:
    provider = RecordingMockImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("无效画幅", "复古漫画", 1)
    project.layout_mode = "custom_page"
    project.custom_layout = [CustomPanelFrame(sequence=1, frame_type="square")]

    with pytest.raises(ValueError, match="还需要添加一个同类型画框"):
        generator.render_confirmed_project(
            project,
            provider.model_id,
            ImageGenerationOptions(),
        )

    assert provider.requests == []


def test_recraft_custom_layout_uses_only_supported_ratios(
    tmp_path: Path,
) -> None:
    payloads: list[dict[str, object]] = []

    def transport(*args: object, **kwargs: object) -> dict[str, object]:
        payloads.append(dict(args[3]))  # type: ignore[arg-type]
        return {"data": [{"b64_json": _encoded_png()}]}

    recraft = RecraftImageProvider(
        api_key="placeholder",
        model="recraft-test",
        max_retries=0,
        transport=transport,
    )
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), recraft]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("Recraft 自定义画幅", "漫画", 3)
    project.layout_mode = "custom_page"
    project.custom_layout = [
        CustomPanelFrame(sequence=1, frame_type="square"),
        CustomPanelFrame(sequence=2, frame_type="square"),
        CustomPanelFrame(sequence=3, frame_type="wide"),
    ]

    generator.render_confirmed_project(
        project,
        "recraft",
        ImageGenerationOptions(),
    )

    assert [payload["size"] for payload in payloads] == ["1:1", "1:1", "3:2"]
