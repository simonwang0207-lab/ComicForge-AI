import httpx
import pytest

from comicforge_ai.models.base import (
    TextModelConnectionError,
    TextModelGenerationTimeoutError,
    TextModelHttpError,
)
from comicforge_ai.models.http import HttpTimeout, request_json


def test_connection_failure_keeps_original_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.ConnectError(
        "connection refused",
        request=httpx.Request("GET", "http://ollama.invalid/api/tags"),
    )

    def fail_request(*args: object, **kwargs: object) -> httpx.Response:
        raise original

    monkeypatch.setattr(httpx, "request", fail_request)

    with pytest.raises(TextModelConnectionError, match="无法连接模型服务") as error:
        request_json(
            "GET",
            "http://ollama.invalid/api/tags",
            {},
            None,
            HttpTimeout(connect=3, read=8),
        )

    assert error.value.original_exception is original
    assert error.value.elapsed_seconds is not None
    assert "原始异常" in str(error.value)


def test_generation_read_timeout_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    original = httpx.ReadTimeout(
        "generation is still running",
        request=httpx.Request("POST", "http://ollama.invalid/api/chat"),
    )

    def fail_request(*args: object, **kwargs: object) -> httpx.Response:
        raise original

    monkeypatch.setattr(httpx, "request", fail_request)

    with pytest.raises(TextModelGenerationTimeoutError, match="生成超时.*300 秒"):
        request_json(
            "POST",
            "http://ollama.invalid/api/chat",
            {},
            {"model": "qwen3:4b"},
            HttpTimeout(connect=5, read=300),
        )


def test_http_error_keeps_status_and_safe_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "http://ollama.invalid/api/chat")
    response = httpx.Response(
        500,
        json={"error": "runner crashed"},
        request=request,
    )

    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: response)

    with pytest.raises(TextModelHttpError, match="状态码 500.*runner crashed") as error:
        request_json(
            "POST",
            "http://ollama.invalid/api/chat",
            {},
            {"model": "qwen3:4b"},
            HttpTimeout(),
        )

    assert error.value.status_code == 500
    assert isinstance(error.value.original_exception, httpx.HTTPStatusError)
