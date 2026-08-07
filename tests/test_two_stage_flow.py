from pathlib import Path

import pytest

from comicforge_ai.models import (
    ImageProviderRegistry,
    MockImageModel,
    MockTextModel,
    TextModelRegistry,
)
from comicforge_ai.models.base import (
    TextModelOutputError,
    TextModelResourceReleaseStatus,
)
from comicforge_ai.schemas import ComicProject, ContentLanguage
from comicforge_ai.service import ComicGenerator, ImageGenerationOptions
from comicforge_ai.ui import relocalize_for_ui


class CountingImageProvider(MockImageModel):
    model_id = "counting-image"
    display_name = "Counting Image"

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().generate(*args, **kwargs)  # type: ignore[arg-type]


class LocalCountingImageProvider(CountingImageProvider):
    model_id = "local-counting-image"
    uses_local_accelerator = True

    def __init__(self) -> None:
        super().__init__()
        self.active_calls = 0
        self.max_active_calls = 0

    def generate(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            return super().generate(*args, **kwargs)
        finally:
            self.active_calls -= 1


class ReleasableTextProvider(MockTextModel):
    model_id = "releasable-text"

    def __init__(self, *, succeeds: bool = True) -> None:
        super().__init__()
        self.release_calls = 0
        self.succeeds = succeeds

    def release_resources(self) -> TextModelResourceReleaseStatus:
        self.release_calls += 1
        return TextModelResourceReleaseStatus(
            attempted=True,
            released=self.succeeds,
            message=("显存已释放" if self.succeeds else "显存释放失败"),
            elapsed_seconds=0.01,
        )


class IndependentReviewProvider(MockTextModel):
    model_id = "independent-review"
    display_name = "Independent Review"

    def __init__(self) -> None:
        super().__init__()
        self.review_calls = 0

    def review_project(self, project: ComicProject) -> ComicProject:
        self.review_calls += 1
        reviewed = project.model_copy(deep=True)
        reviewed.review_notes.append("独立审查模型已检查")
        reviewed.script_reviewed = True
        return reviewed


class FailingReviewProvider(MockTextModel):
    model_id = "failing-review"
    display_name = "Failing Review"

    def review_project(self, project: ComicProject) -> ComicProject:
        raise TextModelOutputError("审查补丁仍然无效")


class TranslationTextProvider(MockTextModel):
    model_id = "translation-test"
    display_name = "Translation Test"

    def __init__(self) -> None:
        super().__init__()
        self.translation_calls = 0

    def translate_project(
        self,
        project: ComicProject,
        target_language: ContentLanguage,
    ) -> ComicProject:
        self.translation_calls += 1
        translated = project.model_copy(deep=True)
        translated.content_language = target_language
        translated.title = "Translated comic"
        for panel in translated.panels:
            for item in panel.text_items:
                item.text = f"EN {item.text}"
            panel.dialogue = " ".join(
                item.text
                for item in panel.text_items
                if item.type in {"speech", "thought"}
            )
            panel.narration = " ".join(
                item.text for item in panel.text_items if item.type == "narration"
            )
        return translated


def test_script_confirmation_prevents_early_image_calls(tmp_path: Path) -> None:
    image_provider = CountingImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    script = generator.generate_script_with_status(
        "两阶段漫画",
        "现代彩漫",
        4,
        "mock",
        "en",
    )

    assert image_provider.calls == 0
    assert script.project.script_reviewed is True
    assert script.project.content_language == "en"

    result = generator.render_confirmed_project(
        script.project,
        "counting-image",
        ImageGenerationOptions(),
    )

    assert image_provider.calls == 4
    assert result.project.output_path is not None
    assert result.project_json_path is not None
    saved = result.project_json_path.read_text(encoding="utf-8")
    assert '"content_language": "en"' in saved


def test_confirmed_project_can_sync_a_new_style_without_stale_style_prompt() -> None:
    generator = ComicGenerator()
    project = MockTextModel().generate_project("风格切换", "清新治愈", 3)
    project.story_bible.visual_style_prompt = "old healing style prompt"

    updated = generator.apply_style_selection(project, "科幻霓虹")

    assert updated.style == "科幻霓虹"
    assert updated.story_bible.visual_style == "科幻霓虹"
    assert updated.story_bible.visual_style_prompt == ""
    assert project.style == "清新治愈"


def test_confirmed_project_keeps_matching_model_authored_style_prompt() -> None:
    generator = ComicGenerator()
    project = MockTextModel().generate_project("风格保持", "清新治愈", 3)
    project.story_bible.visual_style_prompt = "matching healing style prompt"

    updated = generator.apply_style_selection(project, "清新治愈")

    assert updated.story_bible.visual_style_prompt == "matching healing style prompt"


def test_storyboard_edit_can_override_panel_text_position() -> None:
    generator = ComicGenerator()
    project = MockTextModel().generate_project("手动排字", "漫画", 1)
    rows = [[1, "画面", "小漫：出发！", "清晨", "bottom_right"]]

    updated = generator.apply_storyboard_edits(project, rows)

    positioned = [
        item.preferred_position
        for item in updated.panels[0].text_items
        if item.type in {"speech", "narration"}
    ]
    assert positioned == ["bottom_right", "bottom_right"]


def test_script_can_use_a_separate_review_provider() -> None:
    reviewer = IndependentReviewProvider()
    generator = ComicGenerator(
        registry=TextModelRegistry([MockTextModel(), reviewer])
    )

    result = generator.generate_script_with_status(
        "独立审查",
        "漫画",
        2,
        provider_id="mock",
        review_provider_id="independent-review",
    )

    assert reviewer.review_calls == 1
    assert result.project.script_reviewed is True
    assert result.project.requested_text_provider == "mock"
    assert result.project.actual_text_provider == "mock"
    assert result.project.requested_review_provider == "independent-review"
    assert result.project.actual_review_provider == "independent-review"
    assert result.project.review_applied is True
    assert "独立审查模型已检查" in result.project.review_notes
    assert "Independent Review" in result.actual_provider_name


def test_failed_review_keeps_the_validated_draft_usable() -> None:
    generator = ComicGenerator(
        registry=TextModelRegistry([MockTextModel(), FailingReviewProvider()]),
        fallback_to_mock=False,
    )

    result = generator.generate_script_with_status(
        "保留初稿",
        "漫画",
        2,
        provider_id="mock",
        review_provider_id="failing-review",
    )

    assert result.project.panel_count == 2
    assert result.project.script_reviewed is False
    assert result.fallback_used is False
    assert "审查未应用" in result.fallback_reason
    assert "审查未应用" in result.actual_provider_name


def test_user_can_supply_a_script_before_first_storyboard_generation(
    tmp_path: Path,
) -> None:
    image_provider = CountingImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    source_story = "小猫先错过地铁，随后在站务员帮助下找到正确站台。"

    script = generator.generate_script_with_status(
        "小猫坐地铁",
        "清新治愈",
        4,
        "mock",
        source_story=source_story,
    )

    assert image_provider.calls == 0
    assert script.project.user_story_guidance == source_story
    assert script.project.story == source_story
    assert script.project.script_reviewed is True


def test_user_guided_redesign_still_does_not_call_image_provider(
    tmp_path: Path,
) -> None:
    image_provider = CountingImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    script = generator.generate_script_with_status(
        "特洛伊木马",
        "史诗绘本",
        4,
        "mock",
    )

    redesigned = generator.redesign_script_with_guidance(
        script.project,
        "木马被特洛伊人拉入城内；夜间希腊士兵出来打开城门。",
        "mock",
    )

    assert image_provider.calls == 0
    assert redesigned.project.user_story_guidance.startswith("木马被特洛伊人")
    assert redesigned.project.script_reviewed is True
    assert len(redesigned.project.panels) == 4

    second = generator.redesign_script_with_guidance(
        redesigned.project,
        "继续基于上一版：第三格必须强调城门从内部开启。",
        "mock",
    )

    assert image_provider.calls == 0
    assert len(second.project.revision_history) == 2
    assert "木马被特洛伊人" in second.project.user_story_guidance
    assert "城门从内部开启" in second.project.user_story_guidance


def test_explicit_auto_mode_calls_text_then_images(tmp_path: Path) -> None:
    image_provider = CountingImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.generate_auto_with_status(
        "自动模式",
        "现代彩漫",
        3,
        text_provider_id="mock",
        image_provider_id="counting-image",
        layout_mode="webtoon",
        allow_multi_shot_panels=True,
        image_options=ImageGenerationOptions(),
    )

    assert image_provider.calls == 3
    assert result.project.layout_mode == "webtoon"
    assert result.project.allow_multi_shot_panels is True
    assert result.project.output_path is not None


def test_auto_mode_releases_local_text_resources_before_local_images(
    tmp_path: Path,
) -> None:
    text_provider = ReleasableTextProvider()
    image_provider = LocalCountingImageProvider()
    generator = ComicGenerator(
        registry=TextModelRegistry([MockTextModel(), text_provider]),
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.generate_auto_with_status(
        "显存交接",
        "现代彩漫",
        2,
        text_provider_id="releasable-text",
        image_provider_id="local-counting-image",
    )

    assert text_provider.release_calls == 1
    assert image_provider.calls == 2
    assert result.text_resource_release_attempted is True
    assert result.text_resource_release_succeeded is True
    assert result.text_resource_release_message == "显存已释放"


def test_release_failure_does_not_block_local_image_generation(
    tmp_path: Path,
) -> None:
    text_provider = ReleasableTextProvider(succeeds=False)
    image_provider = LocalCountingImageProvider()
    generator = ComicGenerator(
        registry=TextModelRegistry([MockTextModel(), text_provider]),
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    result = generator.render_confirmed_project(
        text_provider.generate_project("释放失败", "漫画", 1),
        "local-counting-image",
        text_provider_id="releasable-text",
    )

    assert text_provider.release_calls == 1
    assert image_provider.calls == 1
    assert result.text_resource_release_attempted is True
    assert result.text_resource_release_succeeded is False


def test_local_image_provider_is_forced_to_single_panel_concurrency(
    tmp_path: Path,
) -> None:
    image_provider = LocalCountingImageProvider()
    generator = ComicGenerator(
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )

    generator.generate_with_status(
        "本地显卡串行",
        "漫画",
        4,
        provider_id="mock",
        image_provider_id="local-counting-image",
        image_options=ImageGenerationOptions(concurrency=4),
    )

    assert image_provider.calls == 4
    assert image_provider.max_active_calls == 1


def test_old_project_json_migrates_language_and_text_items() -> None:
    project = ComicGenerator().text_model.generate_project("旧项目", "水彩", 1)
    payload = project.model_dump(mode="json")
    payload.pop("content_language", None)
    panel = payload["panels"][0]
    panel.pop("text_items", None)
    panel["dialogue"] = "小漫：我们走吧！"
    panel["narration"] = "清晨。"

    migrated = type(project).model_validate(payload)

    assert migrated.content_language == "zh-CN"
    assert [item.type for item in migrated.panels[0].text_items] == [
        "speech",
        "narration",
    ]
    assert migrated.panels[0].text_items[0].speaker == "小漫"


def test_language_switch_reuses_raw_panels_and_cached_translation(
    tmp_path: Path,
) -> None:
    image_provider = CountingImageProvider()
    translator = TranslationTextProvider()
    generator = ComicGenerator(
        registry=TextModelRegistry([MockTextModel(), translator]),
        image_registry=ImageProviderRegistry([MockImageModel(), image_provider]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("语言切换", "复古漫画", 4)
    generated = generator.render_confirmed_project(
        project,
        "counting-image",
        ImageGenerationOptions(),
    )
    original_title = generated.project.title
    rows = [
        [panel.sequence, panel.visual_description, panel.dialogue, panel.narration]
        for panel in generated.project.panels
    ]

    english = generator.relocalize_rendered_project(
        generated.project,
        rows,
        generated.project.title,
        "en",
        "translation-test",
        translate_with_model=True,
        layout_mode="adaptive_page",
        image_options=ImageGenerationOptions(),
    )

    assert image_provider.calls == 4
    assert translator.translation_calls == 1
    assert english.project.content_language == "en"
    assert english.output_path.name == "comic_en.png"
    assert english.output_path.exists()
    assert set(english.project.localizations) == {"zh-CN", "en"}

    english_rows = [
        [panel.sequence, panel.visual_description, panel.dialogue, panel.narration]
        for panel in english.project.panels
    ]
    chinese = generator.relocalize_rendered_project(
        english.project,
        english_rows,
        english.project.title,
        "zh-CN",
        "translation-test",
        translate_with_model=True,
        layout_mode="adaptive_page",
        image_options=ImageGenerationOptions(),
    )

    assert image_provider.calls == 4
    assert translator.translation_calls == 1
    assert chinese.used_cached_translation is True
    assert chinese.project.title == original_title
    assert chinese.output_path.name == "comic_zh_CN.png"


def test_language_switch_ui_returns_updated_language_and_preview(tmp_path: Path) -> None:
    translator = TranslationTextProvider()
    generator = ComicGenerator(
        registry=TextModelRegistry([MockTextModel(), translator]),
        image_registry=ImageProviderRegistry([MockImageModel()]),
        output_dir=tmp_path,
        image_fallback_to_mock=False,
    )
    project = MockTextModel().generate_project("语言按钮", "漫画", 2)
    generated = generator.render_confirmed_project(
        project,
        "mock-image",
        ImageGenerationOptions(),
    )
    rows = [
        [panel.sequence, panel.visual_description, panel.dialogue, panel.narration]
        for panel in generated.project.panels
    ]

    result = relocalize_for_ui(
        generated.project.model_dump(mode="json"),
        rows,
        generated.project.title,
        "en",
        "model",
        "translation-test",
        "adaptive_page",
        "classic",
        "immersive",
        True,
        False,
        True,
        generator,
    )

    assert result[0]["content_language"] == "en"
    assert result[3] == "Translated comic"
    assert result[4] == "en"
    assert result[5] is not None
    assert Path(result[7]).read_bytes().startswith(b"%PDF")
    assert "当前漫画语言：`en`" in result[9]


def test_manual_language_switch_rejects_unchanged_source_text(tmp_path: Path) -> None:
    generator = ComicGenerator(output_dir=tmp_path)
    project = MockTextModel().generate_project("手动译文", "漫画", 2)
    generated = generator.render_confirmed_project(
        project,
        "mock-image",
        ImageGenerationOptions(),
    )
    rows = [
        [panel.sequence, panel.visual_description, panel.dialogue, panel.narration]
        for panel in generated.project.panels
    ]

    with pytest.raises(ValueError, match="手动译文模式不会自动翻译"):
        generator.relocalize_rendered_project(
            generated.project,
            rows,
            generated.project.title,
            "en",
            "mock",
            translate_with_model=False,
            layout_mode="adaptive_page",
        )
