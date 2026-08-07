import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from comicforge_ai.models.comfyui_image import ComfyUIImageProvider
from comicforge_ai.models.fal_image import FalImageProvider
from comicforge_ai.models.image_base import (
    ProviderTimeoutError,
    UnsupportedCapabilityError,
)
from comicforge_ai.models.mock_image import MockImageModel
from comicforge_ai.models.openai_compatible_image import OpenAIImageProvider
from comicforge_ai.models.recraft_image import RecraftImageProvider
from comicforge_ai.models.siliconflow_image import SiliconFlowImageProvider
from comicforge_ai.models.together_image import TogetherImageProvider
from comicforge_ai.schemas import ImageGenerationRequest, PanelSpec


def _png_bytes(color: str = "#406080") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (48, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _encoded() -> str:
    return base64.b64encode(_png_bytes()).decode("ascii")


def _request(**changes: object) -> ImageGenerationRequest:
    values: dict[str, object] = {
        "prompt": "a cat comic panel, no text",
        "width": 1024,
        "height": 1024,
        "output_format": "png",
    }
    values.update(changes)
    return ImageGenerationRequest(**values)


def test_recraft_and_comfyui_use_isolated_prompt_profiles() -> None:
    recraft = RecraftImageProvider(
        api_key="placeholder",
        model="recraftv4_1",
    )
    comfyui = ComfyUIImageProvider(
        base_url="http://127.0.0.1:8188",
        workflow={"6": {"inputs": {"text": "old"}}},
        prompt_node_id="6",
    )

    assert recraft.get_prompt_profile() == "rich_localized"
    assert comfyui.get_prompt_profile() == "sd_comfyui"
    assert recraft.get_prompt_profile() != comfyui.get_prompt_profile()


@pytest.mark.parametrize(
    ("provider_class", "expected_key"),
    [
        (RecraftImageProvider, "size"),
        (TogetherImageProvider, "width"),
    ],
)
def test_sync_p0_providers_normalize_base64(
    provider_class: type[RecraftImageProvider] | type[TogetherImageProvider],
    expected_key: str,
    tmp_path: Path,
) -> None:
    sent: dict[str, object] = {}

    def transport(*args: object) -> dict[str, object]:
        sent.update(args[3])  # type: ignore[arg-type]
        return {"id": "req-1", "data": [{"b64_json": _encoded()}]}

    provider = provider_class(
        api_key="placeholder",
        model="test-model",
        transport=transport,
        max_retries=0,
    )
    result = provider.generate(_request(), tmp_path / "panel.png")

    assert expected_key in sent
    assert result.request_id == "req-1"
    assert result.image.size == (48, 32)


def test_recraft_default_request_omits_seed(tmp_path: Path) -> None:
    sent: dict[str, object] = {}

    def transport(*args: object) -> dict[str, object]:
        sent.update(args[3])  # type: ignore[arg-type]
        return {"data": [{"b64_json": _encoded()}]}

    provider = RecraftImageProvider(
        api_key="placeholder",
        model="recraftv4_1",
        transport=transport,
        max_retries=0,
    )

    provider.generate(_request(seed=None), tmp_path / "panel.png")

    assert "seed" not in sent


def test_siliconflow_uses_native_fields_and_images_structure(
    tmp_path: Path,
) -> None:
    sent: dict[str, object] = {}

    def transport(*args: object) -> dict[str, object]:
        sent.update(args[3])  # type: ignore[arg-type]
        return {"images": [{"b64": _encoded()}], "seed": 71}

    provider = SiliconFlowImageProvider(
        api_key="placeholder",
        model="sf-model",
        transport=transport,
        max_retries=0,
    )
    result = provider.generate(
        _request(count=2, seed=71, negative_prompt="words"),
        tmp_path / "panel.png",
    )

    assert sent["image_size"] == "1024x1024"
    assert sent["batch_size"] == 2
    assert sent["negative_prompt"] == "words"
    assert result.seed == 71


def test_siliconflow_reference_image_uses_edit_operation(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    reference.write_bytes(_png_bytes())
    sent: dict[str, object] = {}

    def transport(*args: object) -> dict[str, object]:
        sent.update(args[3])  # type: ignore[arg-type]
        return {"images": [{"b64_json": _encoded()}]}

    provider = SiliconFlowImageProvider(
        api_key="placeholder",
        model="sf-model",
        transport=transport,
        max_retries=0,
    )
    result = provider.edit(
        _request(reference_images=[reference]),
        tmp_path / "edited.png",
    )

    assert str(sent["image"]).startswith("data:image/png;base64,")
    assert result.operation == "edit"


def test_fal_queue_submission_polling_and_result(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def transport(*args: object) -> dict[str, object]:
        method, url = str(args[0]), str(args[1])
        calls.append((method, url))
        if method == "POST":
            return {
                "request_id": "fal-1",
                "status_url": "https://queue.invalid/status/fal-1",
                "response_url": "https://queue.invalid/result/fal-1",
            }
        if "status" in url:
            return {"status": "COMPLETED"}
        return {"images": [{"b64_json": _encoded()}], "seed": 9}

    provider = FalImageProvider(
        api_key="placeholder",
        model="fal-ai/example",
        base_url="https://queue.invalid",
        transport=transport,
        max_retries=0,
        poll_interval=0,
    )
    result = provider.generate(_request(seed=9), tmp_path / "panel.png")

    assert [method for method, _ in calls] == ["POST", "GET", "GET"]
    assert result.request_id == "fal-1"
    assert result.actual_parameters["polls"] == 1


def test_fal_polling_has_a_hard_deadline(tmp_path: Path) -> None:
    moments = iter((0.0, 0.0, 2.0))

    def transport(*args: object) -> dict[str, object]:
        if args[0] == "POST":
            return {
                "request_id": "fal-timeout",
                "status_url": "https://queue.invalid/status",
                "response_url": "https://queue.invalid/result",
            }
        return {"status": "IN_PROGRESS"}

    provider = FalImageProvider(
        api_key="placeholder",
        model="fal-ai/example",
        base_url="https://queue.invalid",
        transport=transport,
        max_retries=0,
        max_poll_seconds=1,
        poll_interval=0,
        sleeper=lambda _: None,
        clock=lambda: next(moments),
    )

    with pytest.raises(ProviderTimeoutError, match="轮询超时"):
        provider.generate(_request(), tmp_path / "never.png")


def test_comfyui_prompt_history_polling_and_download(tmp_path: Path) -> None:
    workflow = {
        "6": {"inputs": {"text": "old"}},
        "5": {"inputs": {"width": 1, "height": 1}},
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 1, "negative": ["7", 0]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old negative"},
        },
    }
    submitted: dict[str, object] = {}

    def transport(*args: object) -> dict[str, object]:
        method, url = str(args[0]), str(args[1])
        if method == "POST":
            submitted.update(args[3])  # type: ignore[arg-type]
            return {"prompt_id": "prompt-1"}
        assert url.endswith("/history/prompt-1")
        return {
            "prompt-1": {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "out.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            }
        }

    def download(url: str, *args: object) -> bytes:
        assert "/view?" in url
        return _png_bytes()

    provider = ComfyUIImageProvider(
        base_url="http://127.0.0.1:8188",
        workflow=workflow,
        prompt_node_id="6",
        width_node_id="5",
        height_node_id="5",
        seed_node_id="3",
        transport=transport,
        download_transport=download,
        max_retries=0,
        poll_interval=0,
    )
    result = provider.generate(
        _request(seed=77, negative_prompt="collage, text"),
        tmp_path / "panel.png",
    )
    sent_workflow = submitted["prompt"]

    assert sent_workflow["6"]["inputs"]["text"] == _request().prompt
    assert sent_workflow["5"]["inputs"]["width"] == 1024
    assert sent_workflow["5"]["inputs"]["height"] == 1024
    assert sent_workflow["3"]["inputs"]["seed"] == 77
    assert sent_workflow["7"]["inputs"]["text"] == "collage, text"
    assert provider.get_capabilities().negative_prompt is True
    assert result.request_id == "prompt-1"


def test_comfyui_uploads_reference_and_replaces_ipadapter_load_image(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "character.png"
    reference.write_bytes(_png_bytes("#ee8844"))
    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 1, "negative": ["7", 0]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old negative"},
        },
        "13": {
            "class_type": "IPAdapterAdvanced",
            "inputs": {"image": ["14", 0]},
        },
        "14": {
            "class_type": "LoadImage",
            "inputs": {"image": "workflow-default.png"},
        },
    }
    submitted: dict[str, object] = {}
    uploaded: dict[str, object] = {}

    def upload_transport(*args: object) -> dict[str, object]:
        uploaded["url"] = args[0]
        uploaded["data"] = args[2]
        uploaded["files"] = args[3]
        return {"name": "uploaded-reference.png", "subfolder": "comicforge"}

    def transport(*args: object) -> dict[str, object]:
        if str(args[0]) == "POST":
            submitted.update(args[3])  # type: ignore[arg-type]
            return {"prompt_id": "prompt-reference"}
        return {
            "prompt-reference": {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "out.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            }
        }

    provider = ComfyUIImageProvider(
        base_url="http://127.0.0.1:8188",
        workflow=workflow,
        prompt_node_id="6",
        width_node_id="5",
        height_node_id="5",
        seed_node_id="3",
        transport=transport,
        upload_transport=upload_transport,
        download_transport=lambda *args: _png_bytes(),
        max_retries=0,
        poll_interval=0,
    )
    result = provider.edit(
        _request(reference_images=[reference], seed=77),
        tmp_path / "panel.png",
    )

    sent_workflow = submitted["prompt"]
    files = uploaded["files"]
    assert provider.reference_image_node_id == "14"
    assert provider.get_capabilities().image_to_image is True
    assert uploaded["url"] == "http://127.0.0.1:8188/upload/image"
    assert files[0][0] == "image"
    assert files[0][1][1] == reference.read_bytes()
    assert sent_workflow["14"]["inputs"]["image"] == (
        "comicforge/uploaded-reference.png"
    )
    assert result.operation == "edit"
    assert result.actual_parameters["reference_count"] == 1


def test_comfyui_bypasses_ipadapter_when_no_reference_is_selected() -> None:
    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {"model": ["13", 0]},
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "animagine-xl-4.0-opt.safetensors"},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "12": {
            "class_type": "IPAdapterUnifiedLoader",
            "inputs": {"model": ["4", 0]},
        },
        "13": {
            "class_type": "IPAdapterAdvanced",
            "inputs": {"model": ["12", 0], "image": ["14", 0]},
        },
        "14": {
            "class_type": "LoadImage",
            "inputs": {"image": "cat-example.png"},
        },
    }
    provider = ComfyUIImageProvider(
        base_url="http://127.0.0.1:8188",
        workflow=workflow,
        prompt_node_id="6",
    )

    sent_workflow = provider._build_workflow(
        _request(width=None, height=None),
    )

    assert sent_workflow["3"]["inputs"]["model"] == ["4", 0]
    assert sent_workflow["14"]["inputs"]["image"] == "cat-example.png"


def test_comfyui_detects_animagine_checkpoint_and_uses_sdxl_sizes() -> None:
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "animagine-xl-4.0-opt.safetensors"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
    }

    provider = ComfyUIImageProvider(
        base_url="http://127.0.0.1:8188",
        workflow=workflow,
        prompt_node_id="6",
        width_node_id="5",
        height_node_id="5",
    )

    assert provider.checkpoint_name == "animagine-xl-4.0-opt.safetensors"
    assert provider.get_prompt_profile() == "animagine_xl"
    assert provider.preferred_generation_size(1.0) == (1024, 1024)
    assert provider.preferred_generation_size(1.5) == (1216, 832)
    assert provider.preferred_generation_size(2.5) == (1536, 640)


def test_comfyui_replaces_workflow_seed_when_request_is_automatic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = {
        "6": {"inputs": {"text": "old"}},
        "3": {"inputs": {"seed": 282832678669185}},
    }
    submitted: dict[str, object] = {}

    monkeypatch.setattr(
        "comicforge_ai.models.comfyui_image.secrets.randbelow",
        lambda upper: 700,
    )

    def transport(*args: object) -> dict[str, object]:
        method = str(args[0])
        if method == "POST":
            submitted.update(args[3])  # type: ignore[arg-type]
            return {"prompt_id": "prompt-auto-seed"}
        return {
            "prompt-auto-seed": {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "out.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            }
        }

    provider = ComfyUIImageProvider(
        base_url="http://127.0.0.1:8188",
        workflow=workflow,
        prompt_node_id="6",
        seed_node_id="3",
        transport=transport,
        download_transport=lambda *args: _png_bytes(),
        max_retries=0,
        poll_interval=0,
    )

    result = provider.generate(
        _request(seed=None, width=None, height=None),
        tmp_path / "panel.png",
    )
    sent_workflow = submitted["prompt"]

    assert sent_workflow["3"]["inputs"]["seed"] == 701
    assert result.seed == 701
    assert result.actual_parameters["seed"] == 701


def test_openai_edit_uses_multiple_references_and_mask(tmp_path: Path) -> None:
    image1 = tmp_path / "one.png"
    image2 = tmp_path / "two.png"
    mask = tmp_path / "mask.png"
    for path in (image1, image2, mask):
        path.write_bytes(_png_bytes())
    captured: dict[str, object] = {}

    def multipart(*args: object) -> dict[str, object]:
        captured["url"] = args[0]
        captured["files"] = args[3]
        return {"id": "edit-1", "data": [{"b64_json": _encoded()}]}

    provider = OpenAIImageProvider(
        base_url="https://api.openai.invalid/v1",
        api_key="placeholder",
        model="image-model",
        multipart_transport=multipart,
        max_retries=0,
    )
    result = provider.edit(
        _request(reference_images=[image1, image2], mask_image=mask),
        tmp_path / "edited.png",
    )

    assert str(captured["url"]).endswith("/v1/images/edits")
    assert [item[0] for item in captured["files"]] == [
        "image[]",
        "image[]",
        "mask",
    ]
    assert result.operation == "edit"


def test_unsupported_parameters_are_not_silently_ignored() -> None:
    panel = PanelSpec(
        sequence=1,
        scene="scene",
        visual_description="visual",
        characters=[],
        action="action",
        image_prompt="prompt",
    )
    request = _request(negative_prompt="not supported", panel=panel)

    with pytest.raises(UnsupportedCapabilityError, match="Negative prompt"):
        MockImageModel().generate(request)
