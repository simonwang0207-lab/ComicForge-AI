import re

from comicforge_ai.models import MockTextModel
from comicforge_ai.prompts import (
    PROMPT_PROFILE_ANIMAGINE_XL,
    PROMPT_PROFILE_RICH_LOCALIZED,
    PROMPT_PROFILE_SD_COMFYUI,
    build_panel_image_request,
    build_panel_negative_prompt,
)
from comicforge_ai.schemas import SubShot


def test_image_prompt_contains_visual_context_but_not_dialogue() -> None:
    project = MockTextModel().generate_project("猫咪探险", "治愈水彩", 1)
    panel = project.panels[0]
    project.characters[0].visual_prompt = "rounded young adventurer in a bright coat"
    project.characters[1].visual_prompt = "small square companion robot"

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_SD_COMFYUI,
    )

    assert "rounded young adventurer" in request.prompt
    assert "small square companion robot" in request.prompt
    assert panel.dialogue not in request.prompt
    assert "ONE FINISHED 2D COMIC PANEL" in request.prompt
    assert "SINGLE-SCENE COMPOSITION" in request.prompt
    assert "CHARACTER IDENTITY LOCK" in request.prompt
    assert "exactly" in request.prompt
    assert "flat cel shading" in request.prompt
    assert "low-detail negative space" in request.prompt
    assert "SERIES STYLE" in request.prompt
    assert "speech bubble" not in request.prompt.lower()
    assert "watermark" not in request.prompt.lower()
    assert "border" not in request.prompt.lower()
    assert re.search(r"[\u4e00-\u9fff]", request.prompt) is None

    negative = build_panel_negative_prompt(
        panel,
        profile=PROMPT_PROFILE_SD_COMFYUI,
        project=project,
    )
    assert "multiple panels" in negative
    assert "collage" in negative
    assert "speech bubble" in negative
    assert "watermark" in negative
    assert "oil painting" in negative
    assert "multiple copies of the same character" in negative


def test_empty_panel_cast_never_injects_every_project_character() -> None:
    project = MockTextModel().generate_project("空角色环境镜头", "清新治愈", 1)
    panel = project.panels[0]
    panel.characters = []
    panel.character_positions = {}
    project.characters[0].visual_prompt = "unique red hero identity"
    project.characters[1].visual_prompt = "unique blue rival identity"

    animagine = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    ).prompt
    rich = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_RICH_LOCALIZED,
    ).prompt

    assert "exactly 2 featured subjects" not in animagine
    assert "unique red hero identity" not in animagine
    assert "unique blue rival identity" not in animagine
    assert "unique red hero identity" not in rich
    assert "unique blue rival identity" not in rich


def test_animagine_profile_uses_quality_tags_and_strict_single_scene() -> None:
    project = MockTextModel().generate_project("猫咪地铁", "清新治愈", 1)
    panel = project.panels[0]
    project.characters = project.characters[:1]
    project.characters[0].visual_prompt = (
        "one orange cat with round face and big eyes, blue collar"
    )
    project.characters[0].appearance = "橘色小猫"
    project.characters[0].clothing = "None"
    project.characters[0].entity_type = "animal"
    project.characters[0].species_or_category = "domestic cat"
    project.characters[0].body_structure = "four-legged feline body"
    project.characters[0].identity_features = [
        "triangular cat ears",
        "cat muzzle",
        "whiskers",
        "paws",
        "cat tail",
    ]
    project.characters[0].avoid_features = [
        "human face on animal",
        "humanoid body",
        "catgirl",
    ]
    panel.characters = [project.characters[0].name]
    panel.visual_description = "Wide shot of the subject waiting on a subway platform"
    panel.action = "Looking toward the arriving train"
    panel.scene = "Modern subway platform"
    panel.image_prompt = (
        "One orange cat with round face and big eyes, big eyes, close-up, "
        "waiting on a subway platform"
    )

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    )
    negative = build_panel_negative_prompt(
        panel,
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
        project=project,
    )

    assert request.prompt.startswith("masterpiece, high score, great score")
    assert "single scene, one camera view" in request.prompt
    assert "entity type animal" in request.prompt
    assert "species or category domestic cat" in request.prompt
    assert "four-legged feline body" in request.prompt
    assert "cat muzzle" in request.prompt
    assert "None" not in request.prompt
    assert "healing anime style" in request.prompt
    assert "recognizable coherent featured subject" in request.prompt
    assert "all defining features attached to the same subject" in request.prompt
    assert request.prompt.count("big eyes") == 1
    assert "Wide shot of the subject waiting on a subway platform" in request.prompt
    assert "low score, bad score, worst quality" in negative
    assert "multiple panels" in negative
    assert "speech bubble" in negative
    assert "human face on animal" in negative
    assert "catgirl" in negative
    assert "featured subject replaced by an isolated body part" in negative


def test_animagine_identity_lock_is_generic_for_non_animal_subjects() -> None:
    project = MockTextModel().generate_project("机器人探险", "科幻霓虹", 1)
    robot = project.characters[1]
    project.characters = [robot]
    project.panels[0].characters = [robot.name]

    request = build_panel_image_request(
        project,
        project.panels[0],
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    )
    negative = build_panel_negative_prompt(
        project.panels[0],
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
        project=project,
    )

    assert "entity type robot" in request.prompt
    assert "species or category small companion robot" in request.prompt
    assert "body structure compact square mechanical body" in request.prompt
    assert "domestic cat" not in request.prompt
    assert "human face" in negative
    assert "organic human body" in negative


def test_animagine_styles_are_distinct_and_custom_chinese_style_is_mapped() -> None:
    healing = MockTextModel().generate_project("风格测试", "清新治愈", 1)
    neon = MockTextModel().generate_project("风格测试", "科幻霓虹", 1)
    custom = MockTextModel().generate_project("风格测试", "粉彩童话绘本", 1)
    custom.story_bible.visual_style_prompt = (
        "pastel paper-cut storybook, layered paper texture, gentle warm lighting"
    )

    healing_prompt = build_panel_image_request(
        healing,
        healing.panels[0],
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    ).prompt
    neon_prompt = build_panel_image_request(
        neon,
        neon.panels[0],
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    ).prompt
    custom_prompt = build_panel_image_request(
        custom,
        custom.panels[0],
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    ).prompt

    assert "healing anime style" in healing_prompt
    assert "neon science fiction anime style" in neon_prompt
    assert healing_prompt != neon_prompt
    assert "pastel paper-cut storybook" in custom_prompt
    assert "layered paper texture" in custom_prompt


def test_every_panel_reuses_the_same_project_style_lock() -> None:
    project = MockTextModel().generate_project("雨夜救援", "复古像素", 4)

    prompts = [
        build_panel_image_request(
            project,
            panel,
            profile=PROMPT_PROFILE_SD_COMFYUI,
        ).prompt
        for panel in project.panels
    ]
    anchors = [
        prompt.split("SERIES STYLE", 1)[1].split("\n", 1)[0]
        for prompt in prompts
    ]

    assert len(set(anchors)) == 1


def test_multi_shot_panel_prompt_is_explicit_but_still_forbids_text() -> None:
    project = MockTextModel().generate_project("钥匙谜题", "复古漫画", 1)
    panel = project.panels[0]
    panel.composition = "inset"
    panel.subshots = [
        SubShot(
            shot_type="close_up",
            visual_description="手中钥匙的特写",
            focus="钥匙纹理",
            position="top_right",
        )
    ]

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_SD_COMFYUI,
    )

    assert "TWO-VIEW COMPOSITION" in request.prompt
    assert "maximum two views" in request.prompt

    negative = build_panel_negative_prompt(
        panel,
        profile=PROMPT_PROFILE_SD_COMFYUI,
    )
    assert "more than two views" in negative
    assert "inset frame" not in negative


def test_rich_localized_profile_preserves_recraft_prompt_behavior() -> None:
    project = MockTextModel().generate_project("猫咪地铁", "清新治愈", 1)
    panel = project.panels[0]

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_RICH_LOCALIZED,
    )

    assert f"漫画视觉风格：{project.style}" in request.prompt
    assert f"场景：{panel.scene}" in request.prompt
    assert f"画面与构图：{panel.visual_description}" in request.prompt
    assert f"人物动作与表情：{panel.action}" in request.prompt
    assert "全项目画风锁定" in request.prompt
    assert "全局一致角色设定" in request.prompt
    assert panel.image_prompt not in request.prompt
    assert "SINGLE-SCENE COMPOSITION" not in request.prompt
    assert "four-legged cat body" not in request.prompt
    assert "human face on animal" not in request.prompt
    assert build_panel_negative_prompt(
        panel,
        profile=PROMPT_PROFILE_RICH_LOCALIZED,
    ) == ""
    assert build_panel_negative_prompt(
        panel,
        "用户明确排除的内容",
        profile=PROMPT_PROFILE_RICH_LOCALIZED,
    ) == "用户明确排除的内容"


def test_animagine_keeps_complete_image_prompt_when_scene_is_also_english() -> None:
    project = MockTextModel().generate_project("特洛伊木马", "复古像素", 1)
    panel = project.panels[0]
    panel.scene = "Troy city walls, day"
    panel.visual_description = "西农站在城墙附近"
    panel.action = "西农观察远方"
    panel.image_prompt = (
        "retro pixel art, Trojan wooden horse entering the fortified city, "
        "Greek soldiers hiding inside"
    )

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    )

    assert "Trojan wooden horse entering the fortified city" in request.prompt
    assert "Greek soldiers hiding inside" in request.prompt
    assert "Troy city walls, day" in request.prompt


def test_animagine_prioritizes_story_scene_over_reference_composition() -> None:
    project = MockTextModel().generate_project("哪吒闹海", "水彩童话", 1)
    panel = project.panels[0]
    panel.image_prompt = (
        "Nezha chases the Dragon King through towering waves, minimal background"
    )

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    )

    assert "story scene and described action take priority" in request.prompt
    assert "never copy its pose" in request.prompt
    assert "minimal background" not in request.prompt
    assert "detailed story-relevant environment" in request.prompt


def test_animagine_reference_identity_overrides_conflicting_text_profile() -> None:
    project = MockTextModel().generate_project("哪吒参考图", "科幻霓虹", 1)
    character = project.characters[0]
    character.visual_prompt = "Young hero with red hair and a blue robe"
    character.identity_features = ["short red hair", "blue robe"]
    character.clothing = "blue robe"
    character.primary_colors = ["red", "blue"]
    panel = project.panels[0]
    panel.characters = [character.name]
    panel.image_prompt = (
        "A young hero with short red hair and blue robe on a wind fire wheel, "
        "defending a coastal town at night, low angle action shot"
    )

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
        reference_character_names=(character.name,),
    )

    assert "REFERENCE IMAGE IDENTITY LOCK" in request.prompt
    assert "same character as the reference image" in request.prompt
    assert "preserve identity, outfit, hairstyle and face" in request.prompt
    assert "red hair" not in request.prompt
    assert "blue robe" not in request.prompt
    assert "wind fire wheel" in request.prompt
    assert "defending a coastal town at night" in request.prompt
    assert "low angle action shot" in request.prompt


def test_animagine_without_reference_keeps_text_character_appearance() -> None:
    project = MockTextModel().generate_project("无参考图外貌", "科幻霓虹", 1)
    character = project.characters[0]
    character.hairstyle = "short red hair"
    character.clothing = "blue robe"
    panel = project.panels[0]
    panel.characters = [character.name]
    panel.image_prompt = "A young hero with short red hair and blue robe in a harbor"

    request = build_panel_image_request(
        project,
        panel,
        profile=PROMPT_PROFILE_ANIMAGINE_XL,
    )

    assert "short red hair" in request.prompt
    assert "blue robe" in request.prompt
    assert "REFERENCE IMAGE IDENTITY LOCK" not in request.prompt
