from __future__ import annotations

import json

from provider_fixtures import comic_payload

from comicforge_ai.models.deepseek_text import DeepSeekTextModel
from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.registry import build_default_registry


def test_deepseek_uses_named_provider_and_disables_thinking() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        assert payload is not None
        calls.append((method, url, payload))
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "{}"}}
            ]
        }

    provider = DeepSeekTextModel(
        base_url="https://api.deepseek.com",
        api_key="placeholder",
        model="deepseek-v4-flash",
        transport=fake_transport,
    )

    provider._chat_response(
        [{"role": "user", "content": "Return JSON"}],
        32768,
    )

    method, url, payload = calls[0]
    assert method == "POST"
    assert url == "https://api.deepseek.com/chat/completions"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 32768


def test_deepseek_registry_configuration_is_independent() -> None:
    registry = build_default_registry(
        {
            "DEEPSEEK_API_KEY": "placeholder",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
            "DEEPSEEK_MAX_TOKENS": "24576",
        }
    )

    provider = registry.get("deepseek")
    assert isinstance(provider, DeepSeekTextModel)
    assert provider.model_name == "deepseek-v4-pro"
    assert provider.max_tokens == 24576
    assert provider.configuration_status().configured is True


def test_deepseek_accepts_repairable_optional_layout_fields_without_retry() -> None:
    calls = 0
    response = comic_payload(1)
    response["panels"][0]["character_positions"] = {"小雨": "center_bottom"}
    response["panels"][0]["text_items"] = [
        {
            "type": "speech",
            "speaker": "小雨",
            "text": "找到线索了！",
            "speaker_position": "foreground",
        }
    ]
    response["panels"][0]["subshots"] = [
        {
            "shot_type": "reaction",
            "description": "小雨惊讶地看向脚印",
            "position": "lower_right",
        },
        {"shot_type": "detail", "position": "foreground"},
    ]

    def fake_transport(
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object] | None,
        timeout: HttpTimeout,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(response, ensure_ascii=False)
                    },
                }
            ]
        }

    provider = DeepSeekTextModel(
        base_url="https://api.deepseek.com",
        api_key="placeholder",
        model="deepseek-v4-flash",
        max_retries=1,
        transport=fake_transport,
    )

    project = provider.generate_project("寻找线索", "清新漫画", 1)

    assert calls == 1
    assert project.panels[0].character_positions == {"小雨": "bottom_left"}
    assert project.panels[0].text_items[0].speaker_position is None
    assert len(project.panels[0].subshots) == 1
    assert project.panels[0].subshots[0].visual_description == "小雨惊讶地看向脚印"
    assert project.panels[0].subshots[0].position == "bottom_right"
