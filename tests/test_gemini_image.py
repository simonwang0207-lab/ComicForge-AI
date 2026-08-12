from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from comicforge_ai.models import ImageProviderRegistry, MockImageModel, MockTextModel
from comicforge_ai.models.gemini_image import GeminiImageProvider
from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.schemas import ImageGenerationRequest
from comicforge_ai.service import ComicGenerator, ImageGenerationOptions


def _png_bytes(color: str = "navy") -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), color).save(stream, format="PNG")
    return stream.getvalue()


def test_gemini_generates_and_saves_inline_image(tmp_path: Path) -> None:
    payloads: list[dict[str, object]] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "POST"
        assert url.endswith("/v1beta/interactions")
        assert headers["x-goog-api-key"] == "placeholder"
        assert payload is not None
        payloads.append(payload)
        return {
            "id": "interaction-123",
            "model": "gemini-3.1-flash-image",
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "image",
                            "mime_type": "image/png",
                            "data": base64.b64encode(_png_bytes()).decode("ascii"),
                        }
                    ],
                }
            ],
            "usage": {"total_tokens": 1120},
        }

    provider = GeminiImageProvider(
        api_key="placeholder",
        transport=fake_transport,
        sleeper=lambda _: None,
    )
    output_path = tmp_path / "panel.png"
    result = provider.generate(
        ImageGenerationRequest(
            prompt="A dynamic comic scene",
            negative_prompt="letters, speech bubbles",
            aspect_ratio="16:9",
        ),
        output_path,
    )

    assert output_path.exists()
    assert result.provider_id == "gemini"
    assert result.request_id == "interaction-123"
    assert result.actual_parameters == {
        "aspect_ratio": "16:9",
        "image_size": "1K",
        "output_format": "png",
        "reference_count": 0,
        "retry_count": 0,
        "api_mode": "interactions",
    }
    assert result.raw_metadata == {
        "id": "interaction-123",
        "model": "gemini-3.1-flash-image",
        "status": "completed",
        "usage": {"total_tokens": 1120},
    }
    request_input = payloads[0]["input"]
    assert isinstance(request_input, list)
    assert "Avoid these visual elements" in str(request_input[0])


def test_gemini_edit_sends_reference_image_without_persisting_base64(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "character.png"
    reference.write_bytes(_png_bytes("red"))
    captured: dict[str, object] = {}

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert payload is not None
        captured.update(payload)
        return {
            "id": "interaction-edit",
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "image",
                            "data": base64.b64encode(_png_bytes("green")).decode(
                                "ascii"
                            ),
                        }
                    ],
                }
            ],
        }

    provider = GeminiImageProvider(
        api_key="placeholder",
        transport=fake_transport,
    )
    result = provider.edit(
        ImageGenerationRequest(
            prompt="Keep the identity, change only pose and setting",
            aspect_ratio="3:2",
            reference_images=[reference],
        ),
        tmp_path / "edited.png",
    )

    inputs = captured["input"]
    assert isinstance(inputs, list)
    assert inputs[1]["type"] == "image"
    assert inputs[1]["mime_type"] == "image/png"
    assert result.operation == "edit"
    assert result.actual_parameters is not None
    assert result.actual_parameters["reference_count"] == 1
    assert "steps" not in (result.raw_metadata or {})


def test_gemini_missing_key_is_not_configured() -> None:
    provider = GeminiImageProvider(api_key="")

    status = provider.validate_config()

    assert status.configured is False
    assert status.missing_settings == ("GEMINI_API_KEY",)


def test_gemini_generate_content_gateway_sends_reference_and_saves_inline_image(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "character.jpg"
    Image.new("RGB", (24, 32), "red").save(reference, format="JPEG")
    captured: dict[str, object] = {}

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "POST"
        assert url.startswith(
            "https://proxy.example/v1beta/models/%5B30%E9%A2%9D%E5%BA%A6%5D"
        )
        assert url.endswith(":generateContent?key=placeholder")
        assert "x-goog-api-key" not in headers
        assert payload is not None
        captured.update(payload)
        return {
            "responseId": "proxy-request-123",
            "modelVersion": "gemini-proxy-image",
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "thought": True,
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(
                                        _png_bytes("orange")
                                    ).decode("ascii"),
                                },
                            },
                            {"text": "Generated the requested image."},
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(
                                        _png_bytes("green")
                                    ).decode("ascii"),
                                }
                            },
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"totalTokenCount": 321},
        }

    provider = GeminiImageProvider(
        api_key="placeholder",
        model="[30额度]gemini-3.1-flash-image-preview",
        base_url="https://proxy.example/v1",
        api_mode="generate-content",
        max_retries=0,
        transport=fake_transport,
    )
    output_path = tmp_path / "generated.png"
    result = provider.edit(
        ImageGenerationRequest(
            prompt="Preserve the reference identity; change pose and scene only.",
            aspect_ratio="16:9",
            reference_images=[reference],
        ),
        output_path,
    )

    assert output_path.exists()
    assert result.request_id == "proxy-request-123"
    assert result.actual_parameters == {
        "aspect_ratio": "16:9",
        "image_size": "1K",
        "output_format": "png",
        "reference_count": 1,
        "retry_count": 0,
        "api_mode": "generate-content",
        "generate_content_config_mode": "image-config",
    }
    assert result.raw_metadata == {
        "responseId": "proxy-request-123",
        "modelVersion": "gemini-proxy-image",
        "usageMetadata": {"totalTokenCount": 321},
    }
    assert result.image.getpixel((0, 0)) == (0, 128, 0)
    contents = captured["contents"]
    assert isinstance(contents, list)
    parts = contents[0]["parts"]
    assert parts[0]["text"].startswith("Preserve the reference identity")
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    config = captured["generationConfig"]
    assert config["responseModalities"] == ["TEXT", "IMAGE"]
    assert config["imageConfig"] == {
        "aspectRatio": "16:9",
        "imageSize": "1K",
    }
    assert "responseFormat" not in config
    assert "candidates" not in (result.raw_metadata or {})


def test_gemini_generate_content_can_use_response_format_compatibility() -> None:
    provider = GeminiImageProvider(
        api_key="placeholder",
        api_mode="generate-content",
        generate_content_config_mode="response-format",
    )

    payload = provider._request_payload(
        model=provider.model,
        prompt="A wide comic panel",
        reference_blocks=[],
        aspect_ratio="16:9",
        output_format="png",
    )

    config = payload["generationConfig"]
    assert config["responseFormat"]["image"] == {
        "aspectRatio": "16:9",
        "imageSize": "1K",
    }
    assert "imageConfig" not in config


def test_gemini_generate_content_health_check_uses_free_model_list() -> None:
    model = "[30额度]gemini-3.1-flash-image-preview"

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "GET"
        assert url == "https://proxy.example/v1/models"
        assert headers["Authorization"] == "Bearer placeholder"
        assert payload is None
        return {"data": [{"id": model}]}

    provider = GeminiImageProvider(
        api_key="placeholder",
        model=model,
        base_url="https://proxy.example/v1beta",
        api_mode="generate-content",
        transport=fake_transport,
    )

    status = provider.health_check()

    assert status.available is True
    assert "generate-content" in status.message


def test_gemini_generate_content_rejects_unknown_api_mode() -> None:
    provider = GeminiImageProvider(
        api_key="placeholder",
        api_mode="unknown",
    )

    status = provider.validate_config()

    assert status.configured is False
    assert "GEMINI_API_MODE" in status.message


def test_gemini_generate_content_rejects_unknown_config_mode() -> None:
    provider = GeminiImageProvider(
        api_key="placeholder",
        api_mode="generate-content",
        generate_content_config_mode="unknown",
    )

    status = provider.validate_config()

    assert status.configured is False
    assert "GEMINI_GENERATE_CONTENT_CONFIG_MODE" in status.message


def test_gemini_generate_content_redacts_query_key_from_diagnostics() -> None:
    provider = GeminiImageProvider(
        api_key="bo-sensitive-placeholder",
        model="[30额度]gemini-3.1-flash-image-preview",
        base_url="https://proxy.example",
        api_mode="generate-content",
    )

    safe_endpoint = provider.redact_secrets(provider.endpoint)

    assert "bo-sensitive-placeholder" not in safe_endpoint
    assert "[REDACTED]" in safe_endpoint


def test_gemini_service_maps_ordered_references_to_each_panel(
    tmp_path: Path,
) -> None:
    inline_counts: list[int] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "POST"
        assert payload is not None
        contents = payload["contents"]
        parts = contents[0]["parts"]
        inline_counts.append(
            sum(1 for part in parts if "inline_data" in part)
        )
        return {
            "responseId": f"request-{len(inline_counts)}",
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(
                                        _png_bytes("green")
                                    ).decode("ascii"),
                                }
                            }
                        ]
                    }
                }
            ],
        }

    provider = GeminiImageProvider(
        api_key="placeholder",
        model="[30额度]gemini-3.1-flash-image-preview",
        base_url="https://proxy.example/v1",
        api_mode="generate-content",
        max_retries=0,
        transport=fake_transport,
    )
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("双角色参考", "漫画", 3)
    first_name = project.characters[0].name
    second_name = project.characters[1].name
    project.panels[0].characters = [first_name]
    project.panels[1].characters = [second_name]
    project.panels[2].characters = [first_name, second_name]

    first_reference = tmp_path / "first.png"
    second_reference = tmp_path / "second.png"
    Image.new("RGB", (32, 32), "red").save(first_reference)
    Image.new("RGB", (32, 32), "blue").save(second_reference)

    result = generator.render_confirmed_project(
        project,
        "gemini",
        ImageGenerationOptions(
            reference_images=(first_reference, second_reference),
            concurrency=1,
        ),
    )

    assert inline_counts == [1, 1, 2]
    assert [record.reference_character_names for record in result.project.panel_images] == [
        [first_name],
        [second_name],
        [first_name, second_name],
    ]
    assert [record.actual_parameters["reference_count"] for record in result.project.panel_images] == [
        1,
        1,
        2,
    ]
