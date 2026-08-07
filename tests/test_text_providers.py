import json

from provider_fixtures import comic_payload

from comicforge_ai.models.base import (
    TextModelHttpError,
    TextModelNotFoundError,
    TextModelOutputError,
    TextModelRequestError,
)
from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.mock_text import MockTextModel
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
        options = payload["options"]
        assert isinstance(options, dict)
        assert options["temperature"] == 0.2
        assert options["num_predict"] == 4096
        assert options["num_ctx"] == 8192
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


def test_ollama_review_uses_independent_shorter_timeout() -> None:
    seen_read_timeouts: list[float] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "POST"
        seen_read_timeouts.append(timeout.read)
        return {
            "message": {
                "content": json.dumps(
                    {
                        "project_patch": {},
                        "review_notes": ["初稿无需修改。"],
                        "script_reviewed": True,
                    },
                    ensure_ascii=False,
                )
            }
        }

    provider = OllamaTextModel(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b",
        generation_timeout=300,
        review_timeout=45,
        max_retries=0,
        transport=fake_transport,
    )

    reviewed = provider.review_project(
        MockTextModel().generate_project("独立审查超时", "漫画", 2)
    )

    assert reviewed.script_reviewed is True
    assert seen_read_timeouts == [45]


def test_openai_compatible_review_uses_independent_shorter_timeout() -> None:
    seen_read_timeouts: list[float] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "POST"
        seen_read_timeouts.append(timeout.read)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "project_patch": {},
                                "review_notes": ["初稿无需修改。"],
                                "script_reviewed": True,
                            },
                            ensure_ascii=False,
                        )
                    },
                }
            ]
        }

    provider = OpenAICompatibleTextModel(
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="test-model",
        generation_timeout=300,
        review_timeout=40,
        max_retries=0,
        transport=fake_transport,
    )

    reviewed = provider.review_project(
        MockTextModel().generate_project("兼容接口审查超时", "漫画", 2)
    )

    assert reviewed.script_reviewed is True
    assert seen_read_timeouts == [40]


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


def test_openai_compatible_qwen3_disables_thinking_for_ollama_endpoint() -> None:
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
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            comic_payload(1), ensure_ascii=False
                        )
                    },
                }
            ]
        }

    provider = OpenAICompatibleTextModel(
        base_url="http://127.0.0.1:11434/v1",
        api_key="placeholder",
        model="qwen3:4b",
        max_retries=0,
        transport=fake_transport,
    )

    provider.generate_project("关闭推理", "漫画", 1)

    payload = payloads[0]
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == 4096
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert any(
        str(message.get("content", "")).startswith("/no_think")
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    )


def test_openai_compatible_local_ollama_can_release_model_resources() -> None:
    calls: list[tuple[str, str, dict[str, str], dict[str, object] | None]] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        calls.append((method, url, headers, payload))
        return {"done": True}

    provider = OpenAICompatibleTextModel(
        base_url="http://127.0.0.1:11434/v1",
        api_key="placeholder",
        model="qwen3:4b",
        transport=fake_transport,
    )

    status = provider.release_resources()

    assert status.attempted is True
    assert status.released is True
    assert calls == [
        (
            "POST",
            "http://127.0.0.1:11434/api/generate",
            {},
            {"model": "qwen3:4b", "keep_alive": 0, "stream": False},
        )
    ]


def test_remote_openai_compatible_does_not_receive_ollama_release_request() -> None:
    called = False

    def fake_transport(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    provider = OpenAICompatibleTextModel(
        base_url="https://example.invalid/v1",
        api_key="placeholder",
        model="qwen3:4b",
        transport=fake_transport,
    )

    status = provider.release_resources()

    assert status.attempted is False
    assert status.released is False
    assert called is False


def test_native_ollama_can_release_model_resources() -> None:
    payloads: list[dict[str, object] | None] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert method == "POST"
        assert url == "http://127.0.0.1:11434/api/generate"
        payloads.append(payload)
        return {"done": True}

    provider = OllamaTextModel(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b",
        transport=fake_transport,
    )

    status = provider.release_resources()

    assert status.released is True
    assert payloads == [
        {"model": "qwen3:4b", "keep_alive": 0, "stream": False}
    ]


def test_openai_compatible_generic_model_keeps_standard_payload() -> None:
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
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            comic_payload(1), ensure_ascii=False
                        )
                    }
                }
            ]
        }

    provider = OpenAICompatibleTextModel(
        base_url="https://example.invalid/v1",
        api_key="placeholder",
        model="generic-model",
        max_retries=0,
        transport=fake_transport,
    )

    provider.generate_project("通用模型", "漫画", 1)

    assert "reasoning_effort" not in payloads[0]
    messages = payloads[0]["messages"]
    assert isinstance(messages, list)
    assert all(
        not str(message.get("content", "")).startswith("/no_think")
        for message in messages
        if isinstance(message, dict)
    )


def test_openai_compatible_repairs_missing_fields_from_clean_context() -> None:
    payloads: list[dict[str, object]] = []
    incomplete_marker = "INCOMPLETE_RESPONSE_MUST_NOT_BE_ECHOED"
    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": incomplete_marker,
                                    "panels": [],
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                comic_payload(2),
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
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
        assert method == "POST"
        assert payload is not None
        payloads.append(payload)
        return next(responses)

    provider = OpenAICompatibleTextModel(
        base_url="https://example.invalid/v1",
        api_key="placeholder",
        model="demo-model",
        max_retries=1,
        transport=fake_transport,
    )

    project = provider.generate_project("寻找走失的小狗", "治愈水彩", 2)

    assert len(project.panels) == 2
    assert len(payloads) == 2
    assert payloads[0]["temperature"] == 0.2
    assert payloads[1]["temperature"] == 0.2
    second_messages = payloads[1]["messages"]
    assert isinstance(second_messages, list)
    assert incomplete_marker not in json.dumps(second_messages, ensure_ascii=False)
    assert "characters" in json.dumps(second_messages, ensure_ascii=False)
    assert "story" in json.dumps(second_messages, ensure_ascii=False)


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


def test_openai_compatible_retries_truncation_with_larger_clean_budget() -> None:
    payloads: list[dict[str, object]] = []
    truncated_marker = "TRUNCATED_CONTENT_MUST_NOT_BE_REUSED"
    responses = iter(
        [
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": truncated_marker},
                    }
                ]
            },
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                comic_payload(2), ensure_ascii=False
                            )
                        },
                    }
                ]
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
        assert payload is not None
        payloads.append(payload)
        return next(responses)

    provider = OpenAICompatibleTextModel(
        base_url="https://example.invalid/v1",
        api_key="placeholder",
        model="demo-model",
        max_tokens=4096,
        max_retries=0,
        transport=fake_transport,
    )

    project = provider.generate_project("自动扩容", "漫画", 2)

    assert project.panel_count == 2
    assert [payload["max_tokens"] for payload in payloads] == [4096, 8192]
    retry_messages = payloads[1]["messages"]
    assert truncated_marker not in json.dumps(retry_messages, ensure_ascii=False)
    assert "长度上限" in json.dumps(retry_messages, ensure_ascii=False)


def test_ollama_translation_repairs_item_count_with_stable_ids() -> None:
    project = MockTextModel().generate_project("翻译数量", "漫画", 2)
    invalid = {
        "title": "First attempt",
        "panels": [
            {
                "sequence": panel.sequence,
                "text_items": (
                    ["Merged text"] if panel.sequence == 2 else ["One", "Two"]
                ),
            }
            for panel in project.panels
        ],
    }
    valid = {
        "title": "Stable translated comic",
        "texts": {
            f"P{panel.sequence}-I{index}": f"Translated {panel.sequence}-{index}"
            for panel in project.panels
            for index, _ in enumerate(panel.text_items)
        },
    }
    responses = iter([invalid, valid])
    request_payloads: list[dict[str, object]] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert payload is not None
        request_payloads.append(payload)
        return {
            "message": {
                "content": json.dumps(next(responses), ensure_ascii=False)
            }
        }

    provider = OllamaTextModel(
        base_url="http://ollama.invalid",
        model="qwen3:4b",
        max_retries=1,
        transport=fake_transport,
    )

    translated = provider.translate_project(project, "en")

    assert translated.content_language == "en"
    assert len(request_payloads) == 2
    repair_messages = request_payloads[1]["messages"]
    assert "P2-I1" in json.dumps(repair_messages, ensure_ascii=False)
    assert all(
        len(panel.text_items) == len(source.text_items)
        for panel, source in zip(translated.panels, project.panels, strict=True)
    )


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


def test_ollama_reports_truncated_generation_with_configuration_advice() -> None:
    def fake_transport(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "done_reason": "length",
            "message": {"content": '{"title": "truncated"'},
        }

    provider = OllamaTextModel(
        base_url="http://ollama.invalid",
        model="qwen3:4b",
        transport=fake_transport,
    )

    try:
        provider.generate_project("测试", "漫画", 4)
    except TextModelOutputError as exc:
        assert "输出达到长度上限" in str(exc)
        assert "OLLAMA_NUM_PREDICT" in str(exc)
    else:
        raise AssertionError("Expected TextModelOutputError")


def test_ollama_retries_truncated_story_revision_with_larger_budget() -> None:
    project = MockTextModel().generate_project("特洛伊木马", "复古漫画", 4)
    revised_payload = project.model_dump(mode="json")
    revised_payload["story"] = "按照用户提供的正确事件顺序重做。"
    responses = iter(
        [
            {
                "done_reason": "length",
                "message": {"content": '{"title":"被截断"'},
            },
            {
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(revised_payload, ensure_ascii=False)
                },
            },
        ]
    )
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
        return next(responses)

    provider = OllamaTextModel(
        base_url="http://ollama.invalid",
        model="qwen3:4b",
        num_predict=4096,
        num_ctx=8192,
        transport=fake_transport,
    )

    revised = provider.revise_project_with_guidance(
        project,
        "木马入城后，希腊士兵在夜间打开城门。",
    )

    assert revised.story == "按照用户提供的正确事件顺序重做。"
    assert revised.script_reviewed is True
    assert len(payloads) == 2
    first_options = payloads[0]["options"]
    second_options = payloads[1]["options"]
    assert isinstance(first_options, dict)
    assert isinstance(second_options, dict)
    assert first_options["num_predict"] == 4096
    assert first_options["num_ctx"] == 8192
    assert second_options["num_predict"] == 8192
    assert second_options["num_ctx"] == 16384
    retry_messages = payloads[1]["messages"]
    assert "不要续写或复述残缺内容" in json.dumps(
        retry_messages,
        ensure_ascii=False,
    )
