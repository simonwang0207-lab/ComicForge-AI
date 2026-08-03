import base64
import logging
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.image_base import ImageModelHttpError, ImageModelRequestError
from comicforge_ai.models.mock_image import MockImageModel
from comicforge_ai.models.openai_compatible_image import (
    OpenAICompatibleImageModel,
    build_images_endpoint,
)
from comicforge_ai.schemas import PanelImageRequest, PanelSpec


def _png_bytes(color: str = "#336699") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _panel_request() -> PanelImageRequest:
    return PanelImageRequest(
        panel=PanelSpec(
            sequence=1,
            scene="雨后的街道",
            visual_description="中景，女孩站在路灯下",
            characters=["小雨"],
            action="女孩低头寻找脚印",
            dialogue="你在哪里？",
            narration="雨停了。",
            image_prompt="水彩漫画，柔和光线",
        ),
        style="治愈水彩",
        prompt="治愈水彩，雨后街道，不要文字",
    )


def test_mock_image_provider_generates_local_png(tmp_path: Path) -> None:
    output = tmp_path / "panel_01.png"

    generated = MockImageModel(width=500, height=320).generate(
        _panel_request(), output
    )

    assert generated.provider_id == "mock-image"
    assert output.read_bytes().startswith(b"\x89PNG")
    assert generated.image.size == (500, 320)


def test_openai_image_provider_downloads_url_result(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "POST"
        assert url == "https://images.invalid/v1/images/generations"
        assert headers["Authorization"] == "Bearer placeholder-key"
        assert payload == {
            "model": "demo-image-model",
            "prompt": _panel_request().prompt,
            "size": "1024x1024",
            "n": 1,
        }
        assert timeout.connect == 10
        assert timeout.read == 300
        return {"data": [{"url": "https://cdn.invalid/panel.png"}]}

    def fake_download(url: str, timeout: HttpTimeout) -> bytes:
        calls.append(url)
        return _png_bytes()

    provider = OpenAICompatibleImageModel(
        base_url="https://images.invalid/v1",
        api_key="placeholder-key",
        model="demo-image-model",
        max_retries=0,
        transport=fake_transport,
        download_transport=fake_download,
    )
    output = tmp_path / "panel_01.png"

    generated = provider.generate(_panel_request(), output)

    assert calls == ["https://cdn.invalid/panel.png"]
    assert generated.provider_id == "openai-compatible-image"
    assert output.read_bytes().startswith(b"\x89PNG")


def test_openai_image_provider_decodes_b64_json(tmp_path: Path) -> None:
    encoded = base64.b64encode(_png_bytes("#884422")).decode("ascii")

    def fake_transport(*args: object, **kwargs: object) -> dict[str, object]:
        return {"data": [{"b64_json": encoded}]}

    def unexpected_download(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("b64_json must not trigger URL download")

    provider = OpenAICompatibleImageModel(
        base_url="https://images.invalid",
        api_key="placeholder-key",
        model="demo-image-model",
        max_retries=0,
        transport=fake_transport,
        download_transport=unexpected_download,
    )
    output = tmp_path / "panel_01.png"

    provider.generate(_panel_request(), output)

    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.size == (64, 64)


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (
            "https://images.invalid",
            "https://images.invalid/v1/images/generations",
        ),
        (
            "https://images.invalid/v1/",
            "https://images.invalid/v1/images/generations",
        ),
        (
            "https://images.invalid/v1/images/generations",
            "https://images.invalid/v1/images/generations",
        ),
    ],
)
def test_images_endpoint_avoids_duplicate_v1(base_url: str, expected: str) -> None:
    assert build_images_endpoint(base_url) == expected


def test_openai_image_provider_reports_missing_configuration() -> None:
    status = OpenAICompatibleImageModel(
        base_url="",
        api_key="",
        model="",
    ).check_availability()

    assert status.configured is False
    assert status.available is False
    assert status.missing_settings == (
        "OPENAI_IMAGE_BASE_URL",
        "OPENAI_IMAGE_API_KEY",
        "OPENAI_IMAGE_MODEL",
    )
    assert "未配置" in status.message


def test_api_key_is_redacted_from_exception_and_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "unit-test-secret-value"

    def failing_transport(*args: object, **kwargs: object) -> dict[str, object]:
        raise ImageModelHttpError(400, f"rejected Bearer {secret}")

    provider = OpenAICompatibleImageModel(
        base_url="https://images.invalid/v1",
        api_key=secret,
        model="demo-image-model",
        max_retries=0,
        transport=failing_transport,
    )

    with caplog.at_level(logging.WARNING), pytest.raises(
        ImageModelRequestError
    ) as error:
        provider.generate(_panel_request(), tmp_path / "panel.png")

    assert secret not in str(error.value)
    assert secret not in caplog.text
    assert "[REDACTED]" in str(error.value)


def test_image_provider_retries_a_failed_request(tmp_path: Path) -> None:
    attempts = 0
    encoded = base64.b64encode(_png_bytes()).decode("ascii")

    def flaky_transport(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ImageModelRequestError("temporary failure")
        return {"data": [{"b64_json": encoded}]}

    provider = OpenAICompatibleImageModel(
        base_url="https://images.invalid/v1",
        api_key="placeholder-key",
        model="demo-image-model",
        max_retries=1,
        transport=flaky_transport,
    )

    provider.generate(_panel_request(), tmp_path / "panel.png")

    assert attempts == 2


def test_invalid_base_url_is_reported_as_invalid_configuration() -> None:
    status = OpenAICompatibleImageModel(
        base_url="not-a-url",
        api_key="placeholder-key",
        model="demo-image-model",
    ).check_availability()

    assert status.configured is False
    assert status.available is False
    assert "配置无效" in status.message
