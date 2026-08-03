import base64
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from comicforge_ai.models import (
    ImageProviderRegistry,
    MockImageModel,
    OpenAICompatibleImageModel,
)
from comicforge_ai.models.image_base import (
    ImageModelConnectionError,
    ImageModelError,
)
from comicforge_ai.models.recraft_image import RecraftImageProvider
from comicforge_ai.models.siliconflow_image import SiliconFlowImageProvider
from comicforge_ai.service import (
    ComicGenerator,
    ImageGenerationOptions,
    normalize_optional_seed,
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
    encoded = _encoded_png()

    def siliconflow_transport(*args: object, **kwargs: object) -> dict[str, object]:
        payload = args[3]
        seeds.append(payload["seed"])  # type: ignore[index]
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


def test_zero_and_empty_seed_mean_provider_random_selection() -> None:
    assert normalize_optional_seed(None) is None
    assert normalize_optional_seed(0) is None
    assert normalize_optional_seed(0.0) is None
    assert normalize_optional_seed(42) == 42


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
