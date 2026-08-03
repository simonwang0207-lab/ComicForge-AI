import json

import pytest
from provider_fixtures import comic_payload

from comicforge_ai.models.base import TextModelOutputError
from comicforge_ai.models.mock_text import MockTextModel
from comicforge_ai.models.parsing import (
    extract_json_object,
    parse_comic_project,
    parse_comic_translation,
)
from comicforge_ai.prompts.comic_translation import (
    build_comic_translation_messages,
)


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


def test_literal_newline_inside_json_string_is_safely_repaired() -> None:
    raw = '{"title": "第一行\n第二行"}'

    assert extract_json_object(raw) == {"title": "第一行\n第二行"}


def test_common_project_field_aliases_are_normalized_before_validation() -> None:
    payload = {
        "title": "别名字段测试",
        "summary": "一个完整但使用了常见别名的故事梗概。",
        "character_profiles": [
            {
                "name": "小满",
                "role": "主角",
                "appearance": "短发，黄色雨衣",
                "personality": "勇敢而细心",
                "visual_prompt": "short hair, yellow raincoat",
            }
        ],
        "panels": [
            {
                "sequence": 1,
                "scene": "雨后的街道",
                "visual_description": "小满抬头看见彩虹",
                "characters": ["小满"],
                "action": "停下脚步并抬头",
                "dialogue": "",
                "narration": "雨停了。",
                "image_prompt": "comic panel, child in yellow raincoat, rainbow",
            }
        ],
    }

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="雨后彩虹",
        style="清新漫画",
        panel_count=1,
    )

    assert project.story == payload["summary"]
    assert project.characters[0].name == "小满"


def test_truncated_json_reports_output_length_advice() -> None:
    with pytest.raises(TextModelOutputError, match="输出可能被长度上限截断"):
        extract_json_object('{"title": "尚未结束')


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


def test_translation_only_changes_visible_text_and_language() -> None:
    project = MockTextModel().generate_project("语言测试", "水彩", 2)
    original_visuals = [panel.visual_description for panel in project.panels]
    payload = {
        "title": "Language Test",
        "panels": [
            {
                "sequence": panel.sequence,
                "text_items": [f"EN {index}" for index, _ in enumerate(panel.text_items)],
            }
            for panel in project.panels
        ],
    }

    translated = parse_comic_translation(
        json.dumps(payload),
        project,
        "en",
    )

    assert translated.title == "Language Test"
    assert translated.content_language == "en"
    assert [panel.visual_description for panel in translated.panels] == original_visuals
    assert translated.panels[0].text_items[0].text == "EN 0"


def test_translation_stable_ids_restore_every_original_text_item() -> None:
    project = MockTextModel().generate_project("编号翻译", "水彩", 2)
    payload = {
        "title": "Stable Translation",
        "texts": {
            f"P{panel.sequence}-I{index}": f"Translated {panel.sequence}-{index}"
            for panel in project.panels
            for index, _ in enumerate(panel.text_items)
        },
    }

    translated = parse_comic_translation(json.dumps(payload), project, "en")

    assert translated.content_language == "en"
    assert [
        item.text for panel in translated.panels for item in panel.text_items
    ] == [
        f"Translated {panel.sequence}-{index}"
        for panel in project.panels
        for index, _ in enumerate(panel.text_items)
    ]


def test_translation_prompt_contains_story_and_panel_context() -> None:
    project = MockTextModel().generate_project("语境翻译", "漫画", 2)
    project.story = "主角先误会伙伴，看到证据后才道歉。"
    project.panels[0].action = "主角误以为伙伴拿走了钥匙，语气带有质问。"

    messages = build_comic_translation_messages(project, "en")
    combined = "\n".join(message["content"] for message in messages)

    assert project.story in combined
    assert project.panels[0].action in combined
    assert "不是逐字翻译器" in combined
    assert "不得改变谁做了什么" in combined
    assert "角色姓名和专有名词" in combined


def test_translation_stable_ids_report_the_exact_missing_item() -> None:
    project = MockTextModel().generate_project("编号缺失", "水彩", 1)
    payload = {
        "title": "Missing Item",
        "texts": {"P1-I0": "Only one translated item"},
    }

    with pytest.raises(TextModelOutputError, match="P1-I1"):
        parse_comic_translation(json.dumps(payload), project, "en")


def test_translation_rejects_changed_text_item_count() -> None:
    project = MockTextModel().generate_project("语言测试", "水彩", 1)
    payload = {
        "title": "Language Test",
        "panels": [{"sequence": 1, "text_items": []}],
    }

    with pytest.raises(TextModelOutputError, match="文字项数量"):
        parse_comic_translation(json.dumps(payload), project, "en")


def test_translation_accepts_text_objects_but_rejects_wrong_language() -> None:
    project = MockTextModel().generate_project("语言测试", "水彩", 1)
    object_payload = {
        "title": "Language Test",
        "panels": [
            {
                "sequence": 1,
                "text_items": [
                    {"index": index, "type": item.type, "text": f"Text {index}"}
                    for index, item in enumerate(project.panels[0].text_items)
                ],
            }
        ],
    }

    translated = parse_comic_translation(
        json.dumps(object_payload),
        project,
        "en",
    )
    assert translated.panels[0].text_items[0].text == "Text 0"

    for item in object_payload["panels"][0]["text_items"]:
        item["text"] = "这仍然是中文，没有翻译。"
    with pytest.raises(TextModelOutputError, match="未完成英文翻译"):
        parse_comic_translation(json.dumps(object_payload), project, "en")
