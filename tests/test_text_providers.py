import json

from provider_fixtures import comic_payload

from comicforge_ai.models.base import (
    TextModelHttpError,
    TextModelNotFoundError,
    TextModelRequestError,
)
from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.ollama_text import OllamaTextModel
from comicforge_ai.models.openai_compatible_text import OpenAICompatibleTextModel


def test_ollama_not_running_returns_unavailable_status() -> None:
    def offline_transport(*args: object, **kwargs: object) -> dict[str, object]:
        raise TextModelRequestError("无法连接模型服务或请求超时")

    provider = OllamaTextModel(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b",
        transport=offline_transport,
    )

    status = provider.check_availability()

    assert status.configured is True
    assert status.available is False
    assert "Ollama 不可用" in status.message


def test_openai_compatible_without_config_is_not_configured() -> None:
    provider = OpenAICompatibleTextModel(
        base_url="",
        api_key="",
        model="",
    )

    status = provider.check_availability()

    assert status.configured is False
    assert status.available is False
    assert "未配置" in status.message
    assert "API_KEY" in status.message


def test_ollama_provider_uses_mock_http_response() -> None:
    calls: list[tuple[str, str]] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        calls.append((method, url))
        if method == "GET":
            return {"models": [{"name": "qwen3:4b"}]}
        assert payload is not None
        assert payload["model"] == "qwen3:4b"
        assert payload["think"] is False
        assert timeout.connect == 10
        assert timeout.read == 300
        return {
            "message": {
                "content": json.dumps(comic_payload(3), ensure_ascii=False)
            }
        }

    provider = OllamaTextModel(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b",
        max_retries=0,
        transport=fake_transport,
    )

    assert provider.check_availability().available is True
    project = provider.generate_project("寻找走失的小狗", "治愈水彩", 3)

    assert project.panel_count == 3
    assert calls == [
        ("GET", "http://127.0.0.1:11434/api/tags"),
        ("POST", "http://127.0.0.1:11434/api/chat"),
    ]


def test_openai_compatible_provider_uses_mock_http_response() -> None:
    seen_authorization: list[str] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        seen_authorization.append(headers["Authorization"])
        if method == "GET":
            assert url == "https://example.invalid/v1/models"
            return {"data": [{"id": "demo-model"}]}
        assert url == "https://example.invalid/v1/chat/completions"
        assert payload is not None
        assert payload["model"] == "demo-model"
        return {
            "choices": [
                {
                    "message": {
                        "content": "```json\n"
                        + json.dumps(comic_payload(2), ensure_ascii=False)
                        + "\n```"
                    }
                }
            ]
        }

    provider = OpenAICompatibleTextModel(
        base_url="https://example.invalid/v1",
        api_key="placeholder",
        model="demo-model",
        max_retries=0,
        transport=fake_transport,
    )

    assert provider.check_availability().available is True
    project = provider.generate_project("寻找走失的小狗", "治愈水彩", 2)

    assert len(project.panels) == 2
    assert seen_authorization == ["Bearer placeholder"] * 2


def test_remote_provider_repairs_invalid_json_once() -> None:
    responses = iter(
        [
            {"message": {"content": "not json"}},
            {
                "message": {
                    "content": json.dumps(comic_payload(1), ensure_ascii=False)
                }
            },
        ]
    )

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        return next(responses)

    provider = OllamaTextModel(
        base_url="http://ollama.invalid",
        model="demo",
        max_retries=1,
        transport=fake_transport,
    )

    assert provider.generate_project("寻找走失的小狗", "治愈水彩", 1).panel_count == 1


def test_ollama_retries_with_no_think_when_api_field_is_unsupported() -> None:
    payloads: list[dict[str, object]] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert payload is not None
        payloads.append(payload)
        if len(payloads) == 1:
            raise TextModelHttpError(
                400,
                'unknown field "think"',
                elapsed_seconds=0.2,
                original_exception=ValueError("old Ollama API"),
            )
        return {
            "message": {
                "content": json.dumps(comic_payload(1), ensure_ascii=False)
            }
        }

    provider = OllamaTextModel(
        base_url="http://ollama.invalid",
        model="qwen3:4b",
        max_retries=0,
        transport=fake_transport,
    )

    project = provider.generate_project("关闭思考测试", "清新漫画", 1)

    assert project.panel_count == 1
    assert payloads[0]["think"] is False
    assert "think" not in payloads[1]
    second_messages = payloads[1]["messages"]
    assert isinstance(second_messages, list)
    assert any(
        isinstance(message, dict)
        and message.get("role") == "user"
        and str(message.get("content", "")).startswith("/no_think\n")
        for message in second_messages
    )
    assert provider.last_thinking_control == "prompt_no_think"


def test_ollama_model_not_found_has_distinct_error() -> None:
    original = RuntimeError("HTTP 404 from Ollama")

    def fake_transport(*args: object, **kwargs: object) -> dict[str, object]:
        raise TextModelHttpError(
            404,
            "model 'missing:latest' not found",
            elapsed_seconds=0.1,
            original_exception=original,
        )

    provider = OllamaTextModel(
        base_url="http://ollama.invalid",
        model="missing:latest",
        max_retries=0,
        transport=fake_transport,
    )

    try:
        provider.generate_project("测试", "漫画", 1)
    except TextModelNotFoundError as exc:
        assert "模型不存在" in str(exc)
        assert "missing:latest" in str(exc)
        assert exc.original_exception is original
    else:
        raise AssertionError("Expected TextModelNotFoundError")
