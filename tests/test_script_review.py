import json
from collections.abc import Iterator

import pytest

from comicforge_ai.models.base import RemoteTextModelProvider, TextModelStatus
from comicforge_ai.models.mock_text import MockTextModel
from comicforge_ai.prompts import (
    build_comic_generation_messages,
    build_story_guidance_revision_messages,
    build_story_review_messages,
)
from comicforge_ai.schemas import ComicProject
from comicforge_ai.service import enhance_multi_shot_compositions


class ReviewProvider(RemoteTextModelProvider):
    model_id = "review-test"
    display_name = "Review Test"
    provider_type = "test"

    def __init__(self, responses: list[str]) -> None:
        super().__init__(max_retries=1)
        self.responses: Iterator[str] = iter(responses)
        self.messages: list[list[dict[str, str]]] = []

    @property
    def model_name(self) -> str:
        return "review-model"

    def check_availability(self) -> TextModelStatus:
        return self._configuration_status()

    def _configuration_status(self) -> TextModelStatus:
        return TextModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=True,
            available=True,
            message="test",
        )

    def _chat(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        return next(self.responses)


def _draft_and_review() -> tuple[ComicProject, ComicProject]:
    draft = MockTextModel().generate_project("时间线故事", "水彩", 4, "zh-CN")
    reviewed = draft.model_copy(deep=True)
    reviewed.script_reviewed = True
    reviewed.review_notes = ["修正人物身份与相邻分镜因果。"]
    reviewed.panels[1].narrative_role = "警告被忽视"
    return draft, reviewed


def test_draft_enters_review_and_returns_revised_project() -> None:
    draft, reviewed = _draft_and_review()
    provider = ReviewProvider(
        [draft.model_dump_json(), reviewed.model_dump_json()]
    )

    result = provider.generate_reviewed_project(
        "时间线故事",
        "水彩",
        4,
        "zh-CN",
    )

    assert len(provider.messages) == 2
    assert result.script_reviewed is True
    assert result.review_notes
    review_prompt = provider.messages[1][-1]["content"]
    for phrase in ("时间线", "身份", "因果", "连续", "静态图片"):
        assert phrase in review_prompt


def test_invalid_review_json_uses_safe_repair_retry() -> None:
    draft, reviewed = _draft_and_review()
    provider = ReviewProvider(
        [draft.model_dump_json(), "not valid json", reviewed.model_dump_json()]
    )

    result = provider.generate_reviewed_project("修订重试", "水彩", 4)

    assert result.script_reviewed is True
    assert len(provider.messages) == 3
    assert "无法通过结构校验" in provider.messages[2][-1]["content"]


def test_partial_review_character_inherits_validated_draft_fields() -> None:
    draft, reviewed = _draft_and_review()
    reviewed_payload = reviewed.model_dump(mode="json")
    reviewed_payload["characters"][0] = {
        "name": draft.characters[0].name,
        "personality": "审查后更加谨慎",
    }
    provider = ReviewProvider(
        [
            draft.model_dump_json(),
            json.dumps(reviewed_payload, ensure_ascii=False),
        ]
    )

    result = provider.generate_reviewed_project("角色字段继承", "水彩", 4)

    assert result.characters[0].personality == "审查后更加谨慎"
    assert result.characters[0].role == draft.characters[0].role
    assert result.characters[0].appearance == draft.characters[0].appearance
    assert result.characters[0].visual_prompt == draft.characters[0].visual_prompt
    assert result.characters[0].entity_type == draft.characters[0].entity_type
    assert (
        result.characters[0].body_structure
        == draft.characters[0].body_structure
    )
    assert (
        result.story_bible.visual_style_prompt
        == draft.story_bible.visual_style_prompt
    )
    assert len(provider.messages) == 2


def test_partial_review_panel_inherits_validated_draft_fields() -> None:
    draft, reviewed = _draft_and_review()
    reviewed_payload = reviewed.model_dump(mode="json")
    reviewed_payload["panels"][0].pop("characters")
    reviewed_payload["panels"][0].pop("image_prompt")
    reviewed_payload["panels"][0]["action"] = "审查后调整的动作"
    provider = ReviewProvider(
        [
            draft.model_dump_json(),
            json.dumps(reviewed_payload, ensure_ascii=False),
        ]
    )

    result = provider.generate_reviewed_project("分镜字段继承", "水彩", 4)

    assert result.panels[0].action == "审查后调整的动作"
    assert result.panels[0].characters == draft.panels[0].characters
    assert result.panels[0].image_prompt == draft.panels[0].image_prompt
    assert len(provider.messages) == 2


def test_partial_story_bible_character_inherits_name_and_identity() -> None:
    draft, reviewed = _draft_and_review()
    reviewed_payload = reviewed.model_dump(mode="json")
    reviewed_payload["story_bible"]["characters"][0] = {
        "motivation": "审查后修正的动机"
    }
    provider = ReviewProvider(
        [
            draft.model_dump_json(),
            json.dumps(reviewed_payload, ensure_ascii=False),
        ]
    )

    result = provider.generate_reviewed_project("故事圣经字段继承", "水彩", 4)

    character = result.story_bible.characters[0]
    assert character.name == draft.story_bible.characters[0].name
    assert character.identity == draft.story_bible.characters[0].identity
    assert character.motivation == "审查后修正的动机"
    assert len(provider.messages) == 2


def test_compact_review_patch_updates_only_selected_panel_fields() -> None:
    draft = MockTextModel().generate_project("紧凑审查", "漫画", 4)
    patch = {
        "project_patch": {
            "panels": [
                {
                    "sequence": 2,
                    "action": "审查后更清晰的静态动作",
                    "dialogue": "小漫：现在行动！",
                }
            ]
        },
        "review_notes": ["修正第二格动作"],
        "script_reviewed": True,
    }
    provider = ReviewProvider([json.dumps(patch, ensure_ascii=False)])

    reviewed = provider.review_project(draft)

    assert reviewed.panels[1].action == "审查后更清晰的静态动作"
    assert reviewed.panels[1].image_prompt == draft.panels[1].image_prompt
    assert reviewed.panels[0] == draft.panels[0]
    assert reviewed.review_notes == ["修正第二格动作"]


@pytest.mark.parametrize(
    ("bad_item", "expected_type", "expected_text"),
    [
        ({"type": "dialogue", "content": "现在出发"}, "speech", "现在出发"),
        ({"type": "对白", "dialogue": "快躲开", "speaker": "小漫"}, "speech", "快躲开"),
        ({"kind": "旁白", "value": "夜幕降临"}, "narration", "夜幕降临"),
        ({"category": "sound_effect", "sfx": "轰隆"}, "sfx", "轰隆"),
        ({"narration": "城市恢复平静"}, "narration", "城市恢复平静"),
    ],
)
def test_review_patch_normalizes_nonstandard_text_items(
    bad_item: dict[str, object],
    expected_type: str,
    expected_text: str,
) -> None:
    draft = MockTextModel().generate_project("文字项兼容", "漫画", 2)
    patch = {
        "project_patch": {
            "panels": [{"sequence": 1, "text_items": [bad_item]}]
        },
        "review_notes": [],
        "script_reviewed": True,
    }
    provider = ReviewProvider([json.dumps(patch, ensure_ascii=False)])

    reviewed = provider.review_project(draft)

    item = reviewed.panels[0].text_items[0]
    assert item.type == expected_type
    assert item.text == expected_text


def test_review_patch_preserves_draft_text_when_all_items_are_unusable() -> None:
    draft = MockTextModel().generate_project("坏文字项回退", "漫画", 2)
    original = [item.model_copy(deep=True) for item in draft.panels[0].text_items]
    patch = {
        "project_patch": {
            "panels": [
                {
                    "sequence": 1,
                    "text_items": [
                        {"type": "unknown"},
                        {"content": ""},
                        "not-an-object",
                    ],
                }
            ]
        },
        "review_notes": [],
        "script_reviewed": True,
    }
    provider = ReviewProvider([json.dumps(patch, ensure_ascii=False)])

    reviewed = provider.review_project(draft)

    assert reviewed.panels[0].text_items == original


def test_review_prompt_contains_story_bible_and_fact_checks() -> None:
    project = MockTextModel().generate_project("历史故事", "漫画", 4)
    content = build_story_review_messages(project)[-1]["content"]

    assert "story_bible" in content


def test_review_prompt_uses_compact_narrative_snapshot() -> None:
    project = MockTextModel().generate_project("紧凑审查上下文", "漫画", 6)
    project.panels[0].image_prompt = "very long visual prompt " * 200

    content = build_story_review_messages(project)[-1]["content"]

    assert "very long visual prompt" not in content
    assert '"image_prompt"' not in content
    assert "不要返回或修改 image_prompt" in content
    assert '"scene"' in content
    assert '"story_bible"' in content
    assert "事实冲突" in content
    assert "角色、道具和场景状态" in content


def test_multi_shot_option_promotes_a_clear_reveal_instead_of_every_panel() -> None:
    project = MockTextModel().generate_project("线索揭晓", "悬疑漫画", 4)
    project.allow_multi_shot_panels = True
    for panel in project.panels:
        panel.composition = "single"
        panel.subshots = []
        panel.importance = 2
        panel.narrative_role = "发展"
    project.panels[2].narrative_role = "关键线索揭示"
    project.panels[2].action = "主角打开盒子，同时伙伴注意到盒盖内的徽记。"
    project.panels[2].importance = 5

    enhanced = enhance_multi_shot_compositions(project)

    promoted = [panel for panel in enhanced.panels if panel.composition != "single"]
    assert [panel.sequence for panel in promoted] == [3]
    assert promoted[0].composition == "inset"
    assert len(promoted[0].subshots) == 1
    assert "关键反应或细节" in enhanced.review_notes[-1]


def test_user_story_guidance_rebuilds_complete_validated_project() -> None:
    draft, revised = _draft_and_review()
    guidance = (
        "第一幕：特洛伊人把“木马”拉入城内。\n"
        "第二幕：希腊士兵夜间出木马并打开城门。"
    )
    revised.story = "按用户提供的事件顺序重写。"
    provider = ReviewProvider([revised.model_dump_json()])

    result = provider.revise_project_with_guidance(draft, guidance)

    assert result.user_story_guidance == guidance
    assert result.panel_count == draft.panel_count
    assert result.script_reviewed is True
    prompt = provider.messages[0][-1]["content"]
    assert guidance in prompt
    assert "最高优先级事实来源" in prompt
    assert "重新设计" in prompt


def test_user_guidance_json_retry_uses_clean_context() -> None:
    draft, revised = _draft_and_review()
    invalid = '{"title": "被截断的错误输出'
    provider = ReviewProvider([invalid, revised.model_dump_json()])

    result = provider.revise_project_with_guidance(
        draft,
        "以用户提供的事件顺序为准。",
    )

    assert result.script_reviewed is True
    assert len(provider.messages) == 2
    repair_messages = provider.messages[1]
    assert all(invalid not in message["content"] for message in repair_messages)
    assert "从干净上下文重新生成" in repair_messages[-1]["content"]


def test_user_story_guidance_prompt_preserves_request_context() -> None:
    project = MockTextModel().generate_project("特洛伊木马", "史诗绘本", 6)
    guidance = "只使用我明确提供的人物和事件，不确定处不要编造。"

    content = build_story_guidance_revision_messages(project, guidance)[-1]["content"]

    assert guidance in content
    assert "全部 6 格分镜" in content
    assert "不要沿用与它冲突的旧情节" in content
    assert "story 控制在 300 字以内" in content
    assert "image_prompt 只使用英文" in content


def test_first_generation_can_use_an_authoritative_user_script() -> None:
    source_story = (
        "第一幕：船队撤离并留下木马。第二幕：特洛伊人将木马拖入城内。"
        "第三幕：士兵夜间从木马中出来打开城门。"
    )

    messages = build_comic_generation_messages(
        "特洛伊木马",
        "复古漫画",
        4,
        source_story=source_story,
    )
    prompt = messages[-1]["content"]

    assert source_story in prompt
    assert "最高优先级内容依据" in prompt
    assert "不得另编一套故事" in prompt
    assert "用户没有提供完整剧本" not in prompt


def test_generation_prompt_separates_identity_from_panel_scene_prompt() -> None:
    messages = build_comic_generation_messages("任意主题", "任意风格", 3)

    assert "适用时明确正常的数量" in messages[0]["content"]
    assert "不要重复堆叠角色外貌、器官或" in messages[-1]["content"]
    assert "这些固定身份信息由 characters 字段统一提供" in messages[-1]["content"]
