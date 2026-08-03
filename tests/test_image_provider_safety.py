import base64

import httpx
import pytest

from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.image_base import (
    AuthenticationError,
    ImageDecodeError,
    ImageDownloadError,
    InsufficientBalanceError,
    InvalidGeneratedImageError,
    ProviderResponseError,
    ProviderTimeoutError,
    RateLimitError,
)
from comicforge_ai.models.image_provider_utils import (
    RetryPolicy,
    decode_image_bytes,
    image_bytes_from_entry,
    request_json,
    with_retry,
)
from comicforge_ai.models.recraft_image import RecraftImageProvider


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthenticationError),
        (402, InsufficientBalanceError),
        (429, RateLimitError),
        (500, ProviderResponseError),
    ],
)
def test_http_status_is_classified(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    error_type: type[Exception],
) -> None:
    request = httpx.Request("POST", "https://images.invalid")
    response = httpx.Response(
        status,
        request=request,
        json={"error": {"message": "safe detail"}},
    )
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: response)

    with pytest.raises(error_type):
        request_json(
            "POST",
            "https://images.invalid",
            {},
            {},
            HttpTimeout(1, 2),
        )


def test_http_timeout_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ReadTimeout(
            "read timed out",
            request=httpx.Request("POST", "https://images.invalid"),
        )

    monkeypatch.setattr(httpx, "request", timeout)

    with pytest.raises(ProviderTimeoutError, match="超时"):
        request_json(
            "POST",
            "https://images.invalid",
            {},
            {},
            HttpTimeout(1, 2),
        )


def test_non_image_and_corrupt_base64_are_rejected() -> None:
    with pytest.raises(ImageDownloadError, match="非图片"):
        image_bytes_from_entry(
            {"url": "https://cdn.invalid/file"},
            downloader=lambda *args: (_ for _ in ()).throw(
                ImageDownloadError("图片下载返回了非图片 Content-Type：text/html")
            ),
            timeout=HttpTimeout(1, 2),
            max_bytes=1024,
        )
    with pytest.raises(ImageDecodeError):
        image_bytes_from_entry(
            {"b64_json": "not-valid-base64!"},
            downloader=lambda *args: b"",
            timeout=HttpTimeout(1, 2),
            max_bytes=1024,
        )
    with pytest.raises(InvalidGeneratedImageError):
        decode_image_bytes(base64.b64decode(base64.b64encode(b"not an image")))


def test_provider_redacts_key_from_diagnostics() -> None:
    provider = RecraftImageProvider(
        api_key="super-secret-test-key",
        model="model",
    )
    safe = provider.redact_secrets(
        "Bearer super-secret-test-key and super-secret-test-key"
    )

    assert "super-secret-test-key" not in safe
    assert safe.count("[REDACTED]") >= 1


@pytest.mark.parametrize(
    "error",
    [
        RateLimitError("rate limited"),
        ProviderResponseError("server error", status_code=500),
        ProviderTimeoutError("timed out"),
    ],
)
def test_transient_errors_use_exponential_retry(error: Exception) -> None:
    attempts = 0
    delays: list[float] = []

    def operation() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise error
        return {"ok": True}

    result, retries = with_retry(
        operation,
        RetryPolicy(max_retries=2, base_delay=0.25),
        sleeper=delays.append,
    )

    assert result == {"ok": True}
    assert retries == 2
    assert delays == [0.25, 0.5]


@pytest.mark.parametrize(
    "error",
    [AuthenticationError("bad key"), InsufficientBalanceError("no balance")],
)
def test_permanent_errors_are_not_retried(error: Exception) -> None:
    attempts = 0

    def operation() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(type(error)):
        with_retry(operation, RetryPolicy(max_retries=3), sleeper=lambda _: None)

    assert attempts == 1
