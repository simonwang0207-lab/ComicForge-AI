from collections.abc import Iterator

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


def test_review_prompt_contains_story_bible_and_fact_checks() -> None:
    project = MockTextModel().generate_project("历史故事", "漫画", 4)
    content = build_story_review_messages(project)[-1]["content"]

    assert "story_bible" in content
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
    assert "image_prompt 控制在 220 字以内" in content


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
