import json

import pytest
from provider_fixtures import comic_payload

from comicforge_ai.models.base import TextModelOutputError
from comicforge_ai.models.parsing import extract_json_object, parse_comic_project


def test_extracts_json_from_markdown_code_fence() -> None:
    raw = "模型结果如下：\n```json\n{\"title\": \"测试\"}\n```\n结束"

    assert extract_json_object(raw) == {"title": "测试"}


def test_parses_and_validates_correct_project_json() -> None:
    raw = json.dumps(comic_payload(3), ensure_ascii=False)

    project = parse_comic_project(
        raw,
        theme="寻找走失的小狗",
        style="治愈水彩",
        panel_count=3,
    )

    assert project.title == "雨后的线索"
    assert len(project.panels) == 3
    assert project.panels[0].visual_description
    assert project.panels[0].image_prompt


def test_invalid_json_has_understandable_error() -> None:
    with pytest.raises(TextModelOutputError, match="JSON 格式无效"):
        parse_comic_project(
            '{"title": "缺少结尾"',
            theme="测试",
            style="水彩",
            panel_count=1,
        )

def test_missing_panel_field_has_understandable_error() -> None:
    payload = comic_payload(1)
    del payload["panels"][0]["image_prompt"]

    with pytest.raises(TextModelOutputError, match=r"panels\[0\]\.image_prompt"):
        parse_comic_project(
            json.dumps(payload, ensure_ascii=False),
            theme="测试",
            style="水彩",
            panel_count=1,
        )


def test_wrong_field_type_has_understandable_error() -> None:
    payload = comic_payload(1)
    payload["panels"][0]["characters"] = "小雨"

    with pytest.raises(TextModelOutputError, match="结构校验失败"):
        parse_comic_project(
            json.dumps(payload, ensure_ascii=False),
            theme="测试",
            style="水彩",
            panel_count=1,
        )
