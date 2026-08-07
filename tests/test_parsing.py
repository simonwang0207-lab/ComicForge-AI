import json

import pytest
from provider_fixtures import comic_payload

from comicforge_ai.models.base import TextModelOutputError
from comicforge_ai.models.mock_text import MockTextModel
from comicforge_ai.models.parsing import (
    extract_json_object,
    parse_comic_project,
    parse_comic_translation,
    parse_reviewed_project,
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


def test_repeated_dialogue_template_is_rejected_before_image_generation() -> None:
    payload = comic_payload(4)
    for index, panel in enumerate(payload["panels"], start=1):
        panel["dialogue"] = f"龙王，今日我执行第{index}步！"

    with pytest.raises(TextModelOutputError, match="对白重复使用同一开头"):
        parse_comic_project(
            json.dumps(payload, ensure_ascii=False),
            theme="哪吒闹海",
            style="水彩童话",
            panel_count=4,
        )


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


def test_missing_panel_sequence_is_inferred_from_array_order() -> None:
    payload = comic_payload(3)
    for panel in payload["panels"]:
        del panel["sequence"]

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="顺序补全",
        style="清新漫画",
        panel_count=3,
    )

    assert [panel.sequence for panel in project.panels] == [1, 2, 3]


def test_compact_panel_payload_inherits_safe_schema_defaults() -> None:
    payload = comic_payload(1)
    payload["panels"] = [
        {
            "sequence": 1,
            "scene": "雨天的街道",
            "image_prompt": "wide shot, a child crossing a rainy street",
            "text_items": [{"type": "sfx", "text": "沙沙"}],
        }
    ]

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="精简分镜",
        style="清新漫画",
        panel_count=1,
    )

    panel = project.panels[0]
    assert panel.scene == "雨天的街道"
    assert panel.visual_description == panel.scene
    assert panel.characters == []
    assert panel.action == panel.dialogue == panel.narration == ""


def test_common_panel_field_aliases_are_normalized() -> None:
    payload = comic_payload(1)
    payload["panels"] = [
        {
            "panel_number": 1,
            "setting": "雨后的街道",
            "description": "孩子撑伞走过斑马线",
            "character_names": ["小满"],
            "actions": "小心看向两侧",
            "speech": "现在可以走了。",
            "caption": "雨渐渐停了。",
            "prompt": "wide comic shot, child crossing a rainy street",
        }
    ]

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="字段别名",
        style="清新漫画",
        panel_count=1,
    )

    panel = project.panels[0]
    assert panel.scene == "雨后的街道"
    assert panel.visual_description == "孩子撑伞走过斑马线"
    assert panel.characters == ["小满"]
    assert panel.dialogue == "现在可以走了。"
    assert panel.narration == "雨渐渐停了。"


def test_compact_provider_panel_does_not_confuse_composition_with_scene() -> None:
    payload = {
        "title": "哪吒闹海",
        "story": "哪吒保护陈塘关。",
        "characters": [
            {
                "name": "哪吒",
                "role": "主角",
                "appearance": "红袍金发",
                "personality": "勇敢",
                "visual_prompt": "Chinese boy, red robe, golden hair, fire wheel",
            },
            {
                "name": "敖丙",
                "role": "对手",
                "appearance": "蓝色龙鳞甲",
                "personality": "骄傲",
                "visual_prompt": "dragon prince, blue scales, long spear",
            },
        ],
        "panels": [
            {
                "sequence": 1,
                "composition": "single",
                "scene": "暴风雨中的海岸",
                "image_prompt": (
                    "Chinese boy in a red robe with golden hair riding a fire wheel "
                    "above a stormy coastline"
                ),
                "text_items": [
                    {"type": "speech", "speaker": "哪吒", "text": "我来保护大家！"}
                ],
                "character_positions": {"哪吒": "bottom_right"},
            },
            {
                "sequence": 2,
                "composition": "single",
                "scene": "海浪上的对峙",
                "image_prompt": "dragon prince with blue scales and a long spear on a wave",
                "text_items": [
                    {"type": "speech", "speaker": "敖丙", "text": "接受挑战！"}
                ],
                "character_positions": {"哪吒": "bottom_right"},
            },
        ],
    }

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="哪吒闹海",
        style="清新治愈",
        panel_count=2,
    )

    assert project.panels[0].scene == "暴风雨中的海岸"
    assert project.panels[0].visual_description == project.panels[0].scene
    assert project.panels[0].characters == ["哪吒"]
    assert project.panels[1].characters == ["敖丙"]
    assert project.panels[1].character_positions == {}


def test_chinese_project_replaces_mixed_english_display_fields_but_keeps_prompt() -> None:
    payload = comic_payload(1)
    payload["panels"][0]["scene"] = "天空中，哪吒与敖丙对决"
    payload["panels"][0]["visual_description"] = (
        "High angle shot of which吒 flying while敖丙 raises a long spear"
    )
    payload["panels"][0]["action"] = "Which吒 dodges waves while敖丙 attacks"
    payload["panels"][0]["image_prompt"] = (
        "High angle shot of Nezha dodging waves while Ao Bing attacks"
    )

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="哪吒闹海",
        style="清新治愈",
        panel_count=1,
        language="zh-CN",
    )

    panel = project.panels[0]
    assert panel.visual_description == panel.scene
    assert panel.action == ""
    assert panel.image_prompt == payload["panels"][0]["image_prompt"]


def test_draft_without_any_comic_text_is_rejected_for_repair() -> None:
    payload = comic_payload(2)
    for panel in payload["panels"]:
        panel["dialogue"] = ""
        panel["narration"] = ""
        panel["text_items"] = []

    with pytest.raises(TextModelOutputError, match="所有分格.*均为空"):
        parse_comic_project(
            json.dumps(payload, ensure_ascii=False),
            theme="必须有漫画文字",
            style="清新治愈",
            panel_count=2,
        )


def test_chinese_project_rejects_english_visible_comic_text() -> None:
    payload = comic_payload(2)
    payload["panels"][0]["dialogue"] = "I will protect everyone!"
    payload["panels"][0]["text_items"] = [
        {
            "type": "speech",
            "speaker": "小满",
            "text": "I will protect everyone!",
        }
    ]

    with pytest.raises(
        TextModelOutputError,
        match="第 1 格.*未使用项目内容语言 zh-CN",
    ):
        parse_comic_project(
            json.dumps(payload, ensure_ascii=False),
            theme="中文台词校验",
            style="清新漫画",
            panel_count=2,
            language="zh-CN",
        )


def test_user_story_recovers_wrong_language_panels_and_empty_lettering() -> None:
    payload = comic_payload(4)
    for index, panel in enumerate(payload["panels"], start=1):
        panel["scene"] = f"English scene {index}"
        panel["visual_description"] = f"English visual description {index}"
        panel["action"] = f"English action {index}"
        panel["dialogue"] = ""
        panel["narration"] = ""
        panel["text_items"] = []
    source_story = (
        "哪吒发现海边出现巨浪。巡海夜叉掀翻渔船。"
        "哪吒踩着风火轮迎战。百姓最终恢复平静。"
    )

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="哪吒闹海",
        style="清新治愈",
        panel_count=4,
        language="zh-CN",
        source_story=source_story,
    )

    assert all("\u4e00" <= panel.scene[0] <= "\u9fff" for panel in project.panels)
    assert all(panel.visual_description == panel.scene for panel in project.panels)
    assert all(panel.narration for panel in project.panels)
    assert all(panel.text_items for panel in project.panels)
    assert [panel.image_prompt for panel in project.panels] == [
        panel["image_prompt"] for panel in payload["panels"]
    ]


def test_review_story_bible_object_lists_are_normalized_to_strings() -> None:
    draft = MockTextModel().generate_project("故事圣经对象列表", "清新漫画", 2)
    payload = {"project_patch": {}}
    payload["project_patch"]["story_bible"] = {
        "timeline": [
            {"sequence": 1, "event": "主角发现线索"},
            {"sequence": 2, "description": "主角解决问题"},
        ],
        "key_objects": [
            {"name": "关键钥匙"},
            {"item": "旧地图"},
        ],
    }

    reviewed = parse_reviewed_project(
        json.dumps(payload, ensure_ascii=False),
        draft,
    )

    assert reviewed.story_bible.timeline == ["主角发现线索", "主角解决问题"]
    assert reviewed.story_bible.key_objects == ["关键钥匙", "旧地图"]


def test_review_panel_character_objects_are_normalized_to_names() -> None:
    draft = MockTextModel().generate_project("角色对象引用", "清新漫画", 2)
    payload = {"project_patch": {"panels": []}}
    for panel in draft.panels:
        payload["project_patch"]["panels"].append(
            {
                "sequence": panel.sequence,
                "characters": [{"name": name} for name in panel.characters],
            }
        )

    reviewed = parse_reviewed_project(
        json.dumps(payload, ensure_ascii=False),
        draft,
    )

    assert [panel.characters for panel in reviewed.panels] == [
        panel.characters for panel in draft.panels
    ]


def test_review_position_aliases_are_normalized_before_validation() -> None:
    draft = MockTextModel().generate_project("审查位置别名", "清新漫画", 2)
    payload = {
        "project_patch": {
            "panels": [
                {
                    "sequence": 1,
                    "character_positions": {"小漫": "center"},
                    "reserved_bubble_regions": ["upper_left", "右上"],
                }
            ]
        }
    }

    reviewed = parse_reviewed_project(
        json.dumps(payload, ensure_ascii=False),
        draft,
    )

    assert reviewed.panels[0].character_positions["小漫"] == "top_center"
    assert reviewed.panels[0].reserved_bubble_regions == [
        "top_left",
        "top_right",
    ]


def test_unknown_review_character_position_inherits_validated_draft_value() -> None:
    draft = MockTextModel().generate_project("审查位置回退", "清新漫画", 2)
    draft.panels[0].character_positions = {"小漫": "bottom_right"}
    payload = {
        "project_patch": {
            "panels": [
                {
                    "sequence": 1,
                    "character_positions": {"小漫": "near_the_camera"},
                }
            ]
        }
    }

    reviewed = parse_reviewed_project(
        json.dumps(payload, ensure_ascii=False),
        draft,
    )

    assert reviewed.panels[0].character_positions == {"小漫": "bottom_right"}


def test_panel_index_alias_is_normalized_to_sequence() -> None:
    payload = comic_payload(2)
    for panel in payload["panels"]:
        panel["index"] = panel.pop("sequence")

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="序号别名",
        style="清新漫画",
        panel_count=2,
    )

    assert [panel.sequence for panel in project.panels] == [1, 2]


def test_missing_draft_title_uses_user_theme_without_inventing_story() -> None:
    payload = comic_payload(1)
    del payload["title"]

    project = parse_comic_project(
        json.dumps(payload, ensure_ascii=False),
        theme="一只猫第一次坐地铁",
        style="清新漫画",
        panel_count=1,
    )

    assert project.title == "一只猫第一次坐地铁"
    assert project.story == payload["story"]


def test_missing_review_title_inherits_validated_draft_title() -> None:
    draft = MockTextModel().generate_project("保留标题", "清新漫画", 1)
    payload = draft.model_dump(mode="json")
    del payload["title"]

    reviewed = parse_reviewed_project(
        json.dumps(payload, ensure_ascii=False),
        draft,
    )

    assert reviewed.title == draft.title


def test_partial_review_inherits_wholly_omitted_story_and_characters() -> None:
    draft = MockTextModel().generate_project("保留故事与角色", "清新漫画", 2)
    payload = {
        "title": draft.title,
        "panels": [panel.model_dump(mode="json") for panel in draft.panels],
        "review_notes": ["只修改了分镜。"],
    }

    reviewed = parse_reviewed_project(
        json.dumps(payload, ensure_ascii=False),
        draft,
    )

    assert reviewed.story == draft.story
    assert reviewed.characters == draft.characters


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
