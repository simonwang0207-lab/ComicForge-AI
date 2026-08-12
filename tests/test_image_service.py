import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from comicforge_ai.layout import panel_target_aspect_ratio
from comicforge_ai.models import (
    ImageProviderRegistry,
    MockImageModel,
    MockTextModel,
    OpenAICompatibleImageModel,
)
from comicforge_ai.models.comfyui_image import ComfyUIImageProvider
from comicforge_ai.models.image_base import (
    ImageGenerationResult,
    ImageModelConnectionError,
    ImageModelError,
    ImageProviderCapabilities,
)
from comicforge_ai.models.recraft_image import RecraftImageProvider
from comicforge_ai.models.siliconflow_image import SiliconFlowImageProvider
from comicforge_ai.schemas import ImageGenerationRequest
from comicforge_ai.service import (
    ComicGenerator,
    ImageGenerationOptions,
    normalize_optional_seed,
    resolve_system_image_seed,
)


def _encoded_png() -> str:
    buffer = BytesIO()
    Image.new("RGB", (96, 96), "#55AACC").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _image_registry_with_transport(
    transport: object,
    *,
    api_key: str = "project-json-secret",
) -> ImageProviderRegistry:
    return ImageProviderRegistry(
        [
            MockImageModel(),
            OpenAICompatibleImageModel(
                base_url="https://images.invalid/v1",
                api_key=api_key,
                model="demo-image-model",
                max_retries=0,
                transport=transport,  # type: ignore[arg-type]
            ),
        ]
    )


class AutoReferenceImageProvider(MockImageModel):
    model_id = "auto-reference-image"
    auto_reference_from_first_panel = True

    def __init__(self) -> None:
        super().__init__()
        self.reference_counts: list[int] = []
        self.reference_names: list[tuple[str, ...]] = []

    def get_capabilities(self) -> ImageProviderCapabilities:
        return ImageProviderCapabilities(text_to_image=True, image_to_image=True)

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path,
    ) -> ImageGenerationResult:
        self.reference_counts.append(len(request.reference_images))
        self.reference_names.append(
            tuple(path.name for path in request.reference_images)
        )
        return super().generate(request, output_path)

    def edit(
        self,
        request: ImageGenerationRequest,
        output_path: Path,
    ) -> ImageGenerationResult:
        self.reference_counts.append(len(request.reference_images))
        self.reference_names.append(
            tuple(path.name for path in request.reference_images)
        )
        clean_request = request.model_copy(update={"reference_images": []})
        result = super().generate(clean_request, output_path)
        result.operation = "edit"
        return result


class PortraitRestrictedImageProvider(AutoReferenceImageProvider):
    model_id = "portrait-restricted-image"
    restrict_reference_to_portrait_panels = True


class MultiReferenceImageProvider(AutoReferenceImageProvider):
    model_id = "multi-reference-image"

    def get_capabilities(self) -> ImageProviderCapabilities:
        return ImageProviderCapabilities(
            text_to_image=True,
            image_to_image=True,
            multi_reference=True,
        )


class FailingLocalAcceleratorProvider(MockImageModel):
    model_id = "failing-local-accelerator"
    uses_local_accelerator = True

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path,
    ) -> ImageGenerationResult:
        self.calls += 1
        raise ImageModelError("local generation deadline exceeded")


def test_one_failed_panel_falls_back_and_project_json_is_safe(
    tmp_path: Path,
) -> None:
    call_count = 0
    encoded = _encoded_png()

    def partly_failing_transport(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ImageModelConnectionError("测试中的图片连接失败")
        return {"data": [{"b64_json": encoded}]}

    secret = "project-json-secret"
    generator = ComicGenerator(
        image_registry=_image_registry_with_transport(
            partly_failing_transport,
            api_key=secret,
        ),
        output_dir=tmp_path,
        image_fallback_to_mock=True,
    )

    result = generator.generate_with_status(
        "逐格图片回退",
        "治愈水彩",
        3,
        provider_id="mock",
        image_provider_id="openai-compatible-image",
    )

    assert result.image_fallback_used is True
    assert result.image_fallback_panels == (2,)
    assert result.project.panel_images[0].provider_id == "openai-compatible-image"
    assert result.project.panel_images[1].provider_id == "mock-image"
    assert result.project.panel_images[1].fallback_used is True
    assert result.project.panel_images[2].provider_id == "openai-compatible-image"
    assert result.project.output_path is not None
    assert result.project.output_path.read_bytes().startswith(b"\x89PNG")
    assert result.comic_pdf_path is not None
    assert result.comic_pdf_path.read_bytes().startswith(b"%PDF")
    assert result.project_json_path is not None

    project_text = result.project_json_path.read_text(encoding="utf-8")
    project_data = json.loads(project_text)
    assert secret not in project_text
    assert project_data["requested_image_provider"] == "openai-compatible-image"
    assert project_data["image_fallback_used"] is True
    assert project_data["output_path"] == "comic.png"
    assert [item["local_path"] for item in project_data["panel_images"]] == [
        "panel_01.png",
        "panel_02.png",
        "panel_03.png",
    ]
    for item in project_data["panel_images"]:
        local_image = result.project_json_path.parent / item["local_path"]
        with Image.open(local_image) as image:
            image.verify()


def test_remote_failure_without_fallback_raises_clear_error(tmp_path: Path) -> None:
    def failing_transport(*args: object, **kwargs: object) -> dict[str, object]:
        raise ImageModelConnectionError("严格验收模式连接失败")

    generator = ComicGenerator(
        image_registry=_image_registry_with_transport(failing_transport),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    with pytest.raises(ImageModelError, match="第 1 格.*严格验收模式连接失败"):
        generator.generate_with_status(
            "严格图片验收",
            "科幻霓虹",
            2,
            provider_id="mock",
            image_provider_id="openai-compatible-image",
        )


def test_first_generated_panel_becomes_reference_for_later_panels(
    tmp_path: Path,
) -> None:
    provider = AutoReferenceImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.generate_with_status(
        "自动首格参考",
        "清新治愈",
        3,
        provider_id="mock",
        image_provider_id="auto-reference-image",
        image_options=ImageGenerationOptions(concurrency=3),
    )

    assert provider.reference_counts[0] == 0
    assert sorted(provider.reference_counts[1:]) == [1, 1]
    assert result.project.panel_images[0].reference_source == ""
    assert [item.reference_source for item in result.project.panel_images[1:]] == [
        "generated_panel",
        "generated_panel",
    ]
    assert [
        item.reference_panel_sequence for item in result.project.panel_images[1:]
    ] == [1, 1]


def test_user_reference_takes_priority_over_generated_panel_reference(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "user-reference.png"
    Image.new("RGB", (32, 32), "#AA8844").save(reference)
    provider = AutoReferenceImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.generate_with_status(
        "用户参考优先",
        "清新治愈",
        2,
        provider_id="mock",
        image_provider_id="auto-reference-image",
        image_options=ImageGenerationOptions(reference_images=(reference,)),
    )

    assert [item.reference_source for item in result.project.panel_images] == [
        "user_upload",
        "user_upload",
    ]
    assert all(
        item.reference_panel_sequence is None
        for item in result.project.panel_images
    )
    assert provider.reference_counts == [1, 1]


def test_user_reference_is_not_applied_to_panel_without_main_character(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "main-character.png"
    Image.new("RGB", (32, 32), "#8844AA").save(reference)
    provider = AutoReferenceImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("双角色", "漫画", 2)
    main_name = project.characters[0].name
    other_name = project.characters[1].name
    project.panels[0].characters = [main_name]
    project.panels[1].characters = [other_name]

    result = generator.render_confirmed_project(
        project,
        "auto-reference-image",
        ImageGenerationOptions(reference_images=(reference,)),
    )

    assert provider.reference_counts == [1, 0]
    assert result.project.panel_images[0].reference_source == "user_upload"
    assert result.project.panel_images[1].reference_source == ""


def test_comfyui_reference_applies_to_single_character_panels_at_any_shot_size(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "main-character.png"
    Image.new("RGB", (32, 32), "#8844AA").save(reference)
    provider = PortraitRestrictedImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("剧情镜头", "漫画", 3)
    main_name = project.characters[0].name
    other_name = project.characters[1].name
    project.panels[0].characters = [main_name]
    project.panels[0].image_prompt = "wide shot of the hero crossing a busy harbor"
    project.panels[1].characters = [main_name]
    project.panels[1].image_prompt = "close-up portrait of the worried hero"
    project.panels[2].characters = [main_name, other_name]
    project.panels[2].image_prompt = "close-up confrontation between two characters"

    result = generator.render_confirmed_project(
        project,
        "portrait-restricted-image",
        ImageGenerationOptions(reference_images=(reference,), concurrency=1),
    )

    assert provider.reference_counts == [1, 1, 0]
    assert [item.reference_source for item in result.project.panel_images] == [
        "user_upload",
        "user_upload",
        "",
    ]
    assert [item.reference_character_names for item in result.project.panel_images] == [
        [main_name],
        [main_name],
        [],
    ]


def test_uploaded_references_are_matched_by_story_bible_order(
    tmp_path: Path,
) -> None:
    provider = PortraitRestrictedImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("双角色参考", "漫画", 2)
    first_name = project.characters[0].name
    second_name = project.characters[1].name
    project.panels[0].characters = [first_name]
    project.panels[0].image_prompt = "medium shot portrait"
    project.panels[1].characters = [second_name]
    project.panels[1].image_prompt = "medium shot portrait"

    first_reference = tmp_path / "reference-01.png"
    second_reference = tmp_path / "reference-02.png"
    Image.new("RGB", (32, 32), "#2244AA").save(first_reference)
    Image.new("RGB", (32, 32), "#AA4422").save(second_reference)

    result = generator.render_confirmed_project(
        project,
        "portrait-restricted-image",
        ImageGenerationOptions(
            reference_images=(first_reference, second_reference),
            concurrency=1,
        ),
    )

    assert provider.reference_names == [
        (first_reference.name,),
        (second_reference.name,),
    ]
    assert [record.reference_character_names for record in result.project.panel_images] == [
        [first_name],
        [second_name],
    ]


def test_comfyui_does_not_turn_first_story_panel_into_identity_reference() -> None:
    assert ComfyUIImageProvider.auto_reference_from_first_panel is False


def test_non_character_reference_source_keeps_other_provider_reference_lists(
    tmp_path: Path,
) -> None:
    provider = MultiReferenceImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    references = (tmp_path / "style-a.png", tmp_path / "style-b.png")
    for index, reference in enumerate(references):
        Image.new("RGB", (32, 32), (40 + index * 20, 60, 80)).save(reference)

    generator.generate_with_status(
        "保持其他图片服务的多参考图行为",
        "漫画",
        1,
        provider_id="mock",
        image_provider_id="multi-reference-image",
        image_options=ImageGenerationOptions(
            reference_images=references,
            reference_source="style_reference",
        ),
    )

    assert provider.reference_counts == [2]
    assert provider.reference_names == [tuple(path.name for path in references)]


def test_multi_reference_provider_selects_uploaded_characters_per_panel(
    tmp_path: Path,
) -> None:
    provider = MultiReferenceImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("双角色同框", "漫画", 3)
    first_name = project.characters[0].name
    second_name = project.characters[1].name
    project.panels[0].characters = [first_name]
    project.panels[1].characters = [second_name]
    project.panels[2].characters = [first_name, second_name]

    first_reference = tmp_path / "reference-01.png"
    second_reference = tmp_path / "reference-02.png"
    Image.new("RGB", (32, 32), "#2244AA").save(first_reference)
    Image.new("RGB", (32, 32), "#AA4422").save(second_reference)

    result = generator.render_confirmed_project(
        project,
        "multi-reference-image",
        ImageGenerationOptions(
            reference_images=(first_reference, second_reference),
            concurrency=1,
        ),
    )

    assert provider.reference_names == [
        (first_reference.name,),
        (second_reference.name,),
        (first_reference.name, second_reference.name),
    ]
    assert [record.reference_character_names for record in result.project.panel_images] == [
        [first_name],
        [second_name],
        [first_name, second_name],
    ]


def test_comfyui_style_reference_rejects_more_images_than_characters(
    tmp_path: Path,
) -> None:
    provider = PortraitRestrictedImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    references = tuple(tmp_path / f"reference-{index}.png" for index in range(3))
    for reference in references:
        Image.new("RGB", (32, 32), "#446688").save(reference)

    with pytest.raises(ImageModelError, match="参考图数量超过项目角色数量"):
        generator.generate_with_status(
            "过多角色参考图",
            "漫画",
            1,
            provider_id="mock",
            image_provider_id="portrait-restricted-image",
            image_options=ImageGenerationOptions(reference_images=references),
        )


def test_local_accelerator_stops_submitting_panels_after_first_failure(
    tmp_path: Path,
) -> None:
    provider = FailingLocalAcceleratorProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    with pytest.raises(ImageModelError, match="第 1 格"):
        generator.generate_with_status(
            "本地队列失败即停止",
            "清新治愈",
            4,
            provider_id="mock",
            image_provider_id=provider.model_id,
            image_options=ImageGenerationOptions(concurrency=4),
        )

    assert provider.calls == 1


def test_single_panel_regeneration_preserves_other_raw_panels(
    tmp_path: Path,
) -> None:
    generator = ComicGenerator(output_dir=tmp_path)
    original = generator.generate_with_status(
        "单格重生成",
        "清新治愈",
        3,
        provider_id="mock",
        image_provider_id="mock-image",
    )
    assert original.project.output_path is not None
    run_dir = original.project.output_path.parent
    untouched_before = (run_dir / "panel_01.png").read_bytes()
    original_panel_two = (run_dir / "panel_02.png").read_bytes()
    original.project.panels[1].visual_description = "修改后的第二格画面"

    regenerated = generator.regenerate_panel(
        original.project,
        2,
        "mock-image",
    )

    assert (run_dir / "panel_01.png").read_bytes() == untouched_before
    assert (run_dir / "panel_02.png").read_bytes().startswith(b"\x89PNG")
    assert len(regenerated.project.panel_images) == 3
    assert regenerated.project.panel_images[1].sequence == 2
    assert "修改后的第二格画面" in regenerated.project.panel_images[1].panel_prompt
    assert len(regenerated.project.panel_image_versions) == 1
    archived = regenerated.project.panel_image_versions[0]
    assert archived.sequence == 2
    assert archived.version == 1
    assert (run_dir / archived.local_path).read_bytes() == original_panel_two
    assert regenerated.project_json_path is not None
    assert regenerated.project.output_path.name == "comic.png"
    assert regenerated.project_json_path.name == "project.json"
    assert regenerated.comic_pdf_path is not None

    restored = generator.restore_panel_version(
        regenerated.project,
        2,
        1,
    )

    assert (run_dir / "panel_02.png").read_bytes() == original_panel_two
    assert len(restored.project.panel_image_versions) == 2
    assert restored.project.panel_image_versions[-1].version == 2
    assert restored.project.panel_images[1].panel_prompt == (
        original.project.panel_images[1].panel_prompt
    )
    assert restored.project_json_path is not None
    assert restored.project.output_path.name == "comic.png"
    assert restored.project_json_path.name == "project.json"


def test_secondary_provider_chain_and_panel_seeds_are_persisted(
    tmp_path: Path,
) -> None:
    encoded = _encoded_png()

    def primary_failure(*args: object, **kwargs: object) -> dict[str, object]:
        raise ImageModelConnectionError("primary unavailable")

    secondary = SiliconFlowImageProvider(
        api_key="placeholder",
        model="secondary-model",
        max_retries=0,
        transport=lambda *args, **kwargs: {
            "request_id": "secondary-request",
            "images": [{"b64_json": encoded}],
        },
    )
    registry = _image_registry_with_transport(primary_failure)
    registry.register(secondary)
    generator = ComicGenerator(
        image_registry=registry,
        output_dir=tmp_path,
        image_fallback_to_mock=True,
    )

    result = generator.generate_with_status(
        "次级图片 Provider",
        "水彩",
        3,
        provider_id="mock",
        image_provider_id="openai-compatible-image",
        image_options=ImageGenerationOptions(
            fallback_chain=("siliconflow",),
            concurrency=2,
        ),
    )

    assert result.image_fallback_panels == (1, 2, 3)
    assert [item.provider_id for item in result.project.panel_images] == [
        "siliconflow",
        "siliconflow",
        "siliconflow",
    ]
    assert [item.seed for item in result.project.panel_images] == [None, None, None]
    assert all(item.request_id == "secondary-request" for item in result.project.panel_images)


def test_strict_mode_attempts_all_panels_and_never_uses_mock(
    tmp_path: Path,
) -> None:
    calls = 0

    def failure(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise ImageModelConnectionError("strict primary failure")

    generator = ComicGenerator(
        image_registry=_image_registry_with_transport(failure),
        output_dir=tmp_path,
        image_fallback_to_mock=True,
    )

    with pytest.raises(ImageModelError, match="strict primary failure"):
        generator.generate_with_status(
            "严格模式逐格检查",
            "水彩",
            3,
            provider_id="mock",
            image_provider_id="openai-compatible-image",
            image_options=ImageGenerationOptions(strict_mode=True, concurrency=2),
        )

    assert calls == 3


def test_recraft_four_panel_flow_does_not_send_automatic_seed(
    tmp_path: Path,
) -> None:
    payloads: list[dict[str, object]] = []
    encoded = _encoded_png()

    def recraft_transport(*args: object, **kwargs: object) -> dict[str, object]:
        payloads.append(dict(args[3]))  # type: ignore[arg-type]
        return {"data": [{"b64_json": encoded}]}

    registry = ImageProviderRegistry(
        [
            MockImageModel(),
            RecraftImageProvider(
                api_key="placeholder",
                model="recraftv4_1",
                max_retries=0,
                transport=recraft_transport,
            ),
        ]
    )
    generator = ComicGenerator(
        image_registry=registry,
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.generate_with_status(
        "Recraft 四格回归",
        "清新治愈",
        4,
        provider_id="mock",
        image_provider_id="recraft",
        image_options=ImageGenerationOptions(seed=0),
    )

    assert len(payloads) == 4
    assert all("seed" not in payload for payload in payloads)
    assert all(payload["size"] == "3:2" for payload in payloads)
    assert result.image_fallback_used is False
    assert [item.provider_id for item in result.project.panel_images] == [
        "recraft",
        "recraft",
        "recraft",
        "recraft",
    ]


def test_seed_capable_provider_receives_incremented_panel_seeds(
    tmp_path: Path,
) -> None:
    seeds: list[int] = []
    negative_prompts: list[str] = []
    encoded = _encoded_png()

    def siliconflow_transport(*args: object, **kwargs: object) -> dict[str, object]:
        payload = args[3]
        seeds.append(payload["seed"])  # type: ignore[index]
        negative_prompts.append(payload.get("negative_prompt", ""))  # type: ignore[union-attr]
        return {"images": [{"b64_json": encoded}], "seed": payload["seed"]}  # type: ignore[index]

    registry = ImageProviderRegistry(
        [
            MockImageModel(),
            SiliconFlowImageProvider(
                api_key="placeholder",
                model="seed-model",
                max_retries=0,
                transport=siliconflow_transport,
            ),
        ]
    )
    generator = ComicGenerator(
        image_registry=registry,
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.generate_with_status(
        "Seed 逐格递增",
        "水彩",
        4,
        provider_id="mock",
        image_provider_id="siliconflow",
        image_options=ImageGenerationOptions(seed=100),
    )

    assert seeds == [100, 101, 102, 103]
    assert [item.seed for item in result.project.panel_images] == seeds
    assert negative_prompts == ["", "", "", ""]


def test_fallback_rebuilds_prompt_for_recraft_profile(tmp_path: Path) -> None:
    comfy_payloads: list[dict[str, object]] = []
    recraft_payloads: list[dict[str, object]] = []
    encoded = _encoded_png()
    workflow = {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old negative"},
        },
        "3": {"class_type": "KSampler", "inputs": {"negative": ["7", 0]}},
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 512, "height": 512},
        },
    }

    def comfy_transport(*args: object, **kwargs: object) -> dict[str, object]:
        comfy_payloads.append(args[3])  # type: ignore[arg-type]
        raise ImageModelConnectionError("ComfyUI unavailable")

    def recraft_transport(*args: object, **kwargs: object) -> dict[str, object]:
        recraft_payloads.append(dict(args[3]))  # type: ignore[arg-type]
        return {"data": [{"b64_json": encoded}]}

    registry = ImageProviderRegistry(
        [
            MockImageModel(),
            ComfyUIImageProvider(
                base_url="http://127.0.0.1:8188",
                workflow=workflow,
                prompt_node_id="6",
                width_node_id="5",
                height_node_id="5",
                model="sd15-workflow",
                max_retries=0,
                transport=comfy_transport,
            ),
            RecraftImageProvider(
                api_key="placeholder",
                model="recraftv4_1",
                max_retries=0,
                transport=recraft_transport,
            ),
        ]
    )
    generator = ComicGenerator(
        image_registry=registry,
        output_dir=tmp_path,
        image_fallback_to_mock=True,
    )

    result = generator.generate_with_status(
        "猫咪第一次坐地铁",
        "清新治愈",
        1,
        provider_id="mock",
        image_provider_id="comfyui",
        image_options=ImageGenerationOptions(fallback_chain=("recraft",)),
    )

    comfy_workflow = comfy_payloads[0]["prompt"]
    assert "SINGLE-SCENE COMPOSITION" in comfy_workflow["6"]["inputs"]["text"]
    assert "multiple panels" in comfy_workflow["7"]["inputs"]["text"]
    assert "漫画视觉风格：清新治愈" in recraft_payloads[0]["prompt"]
    assert "SINGLE-SCENE COMPOSITION" not in recraft_payloads[0]["prompt"]
    assert "rounded young adventurer" not in recraft_payloads[0]["prompt"]
    assert "negative_prompt" not in recraft_payloads[0]
    assert result.project.panel_images[0].provider_id == "recraft"
    assert result.project.panel_images[0].panel_prompt == recraft_payloads[0]["prompt"]


def test_comfyui_adaptive_layout_uses_sd15_safe_panel_sizes() -> None:
    project = MockTextModel().generate_project("六格画幅", "清新治愈", 6)
    project.layout_mode = "adaptive_page"
    provider = ComfyUIImageProvider(
        base_url="http://127.0.0.1:8188",
        workflow={"6": {"inputs": {"text": "old"}}},
        prompt_node_id="6",
        width_node_id="5",
        height_node_id="5",
    )

    shapes = [
        ComicGenerator._request_shape(
            project,
            panel,
            provider,
            ImageGenerationOptions(),
        )
        for panel in project.panels
    ]

    assert shapes == [
        (768, 320, ""),
        (576, 448, ""),
        (640, 384, ""),
        (768, 256, ""),
        (768, 320, ""),
        (768, 320, ""),
    ]
    assert all(width % 64 == height % 64 == 0 for width, height, _ in shapes)


def test_recraft_adaptive_layout_uses_closest_supported_panel_ratios() -> None:
    project = MockTextModel().generate_project("六格画幅", "清新治愈", 6)
    project.layout_mode = "adaptive_page"
    provider = RecraftImageProvider(
        api_key="placeholder",
        model="recraftv4_1",
    )

    shapes = [
        ComicGenerator._request_shape(
            project,
            panel,
            provider,
            ImageGenerationOptions(),
        )
        for panel in project.panels
    ]

    assert shapes == [
        (None, None, "3:2"),
        (None, None, "4:3"),
        (None, None, "3:2"),
        (None, None, "3:2"),
        (None, None, "3:2"),
        (None, None, "3:2"),
    ]


def test_adaptive_lettering_canvas_matches_page_cell_for_remote_provider() -> None:
    project = MockTextModel().generate_project("六格画幅", "清新治愈", 6)
    project.layout_mode = "adaptive_page"
    provider = RecraftImageProvider(
        api_key="placeholder",
        model="recraftv4_1",
    )

    sizes = [
        ComicGenerator._panel_render_size(project, panel, provider)
        for panel in project.panels
    ]

    ratios = [width / height for width, height in sizes]
    expected = [
        panel_target_aspect_ratio(
            project.layout_mode,
            project.panels,
            panel.sequence,
            project.custom_layout,
        )
        for panel in project.panels
    ]
    assert ratios == pytest.approx(expected, rel=0.005)


def test_zero_and_empty_seed_mean_provider_random_selection() -> None:
    assert normalize_optional_seed(None) is None
    assert normalize_optional_seed(0) is None
    assert normalize_optional_seed(0.0) is None
    assert normalize_optional_seed(42) == 42


def test_system_assigns_internal_panel_seeds_for_seed_capable_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeds: list[int] = []
    encoded = _encoded_png()

    monkeypatch.setattr(
        "comicforge_ai.service.secrets.randbelow",
        lambda upper: 499,
    )

    def transport(*args: object, **kwargs: object) -> dict[str, object]:
        payload = args[3]
        seeds.append(payload["seed"])  # type: ignore[index]
        return {
            "images": [{"b64_json": encoded}],
            "seed": payload["seed"],  # type: ignore[index]
        }

    registry = ImageProviderRegistry(
        [
            MockImageModel(),
            SiliconFlowImageProvider(
                api_key="placeholder",
                model="seed-model",
                max_retries=0,
                transport=transport,
            ),
        ]
    )
    generator = ComicGenerator(
        image_registry=registry,
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.generate_with_status(
        "系统自动 Seed",
        "水彩",
        4,
        provider_id="mock",
        image_provider_id="siliconflow",
        image_options=ImageGenerationOptions(seed=None),
    )

    assert seeds == [500, 501, 502, 503]
    assert [item.seed for item in result.project.panel_images] == seeds


def test_system_does_not_create_seed_for_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_random(_: int) -> int:
        raise AssertionError("non-seed Provider must not request a system seed")

    monkeypatch.setattr(
        "comicforge_ai.service.secrets.randbelow",
        unexpected_random,
    )

    assert (
        resolve_system_image_seed(None, provider_supports_seed=False)
        is None
    )


def test_explicit_positive_seed_still_rejected_for_recraft(tmp_path: Path) -> None:
    calls = 0

    def unexpected_transport(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"data": [{"b64_json": _encoded_png()}]}

    registry = ImageProviderRegistry(
        [
            MockImageModel(),
            RecraftImageProvider(
                api_key="placeholder",
                model="recraftv4_1",
                max_retries=0,
                transport=unexpected_transport,
            ),
        ]
    )
    generator = ComicGenerator(
        image_registry=registry,
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    with pytest.raises(ImageModelError, match="Recraft Image 不支持参数：Seed"):
        generator.generate_with_status(
            "显式不兼容 Seed",
            "水彩",
            1,
            provider_id="mock",
            image_provider_id="recraft",
            image_options=ImageGenerationOptions(seed=7),
        )

    assert calls == 0
