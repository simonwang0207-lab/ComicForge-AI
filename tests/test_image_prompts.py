from comicforge_ai.models import MockTextModel
from comicforge_ai.prompts import build_panel_image_request
from comicforge_ai.schemas import SubShot


def test_image_prompt_contains_visual_context_but_not_dialogue() -> None:
    project = MockTextModel().generate_project("猫咪探险", "治愈水彩", 1)
    panel = project.panels[0]

    request = build_panel_image_request(project, panel)

    assert project.style in request.prompt
    assert panel.scene in request.prompt
    assert panel.action in request.prompt
    assert panel.image_prompt in request.prompt
    assert panel.dialogue not in request.prompt
    assert "不要生成文字" in request.prompt
    assert "低细节的负空间" in request.prompt
    assert "全局一致角色设定" in request.prompt
    assert "全项目画风锁定" in request.prompt
    assert "自然且跨格一致的肤色" in request.prompt
    assert "不得在不同分格切换" in request.prompt
    assert "现成气泡" in request.prompt


def test_every_panel_reuses_the_same_project_style_lock() -> None:
    project = MockTextModel().generate_project("雨夜救援", "复古像素", 4)

    prompts = [build_panel_image_request(project, panel).prompt for panel in project.panels]
    anchors = [prompt.split("全项目画风锁定", 1)[1].split("\n", 1)[0] for prompt in prompts]

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

    request = build_panel_image_request(project, panel)

    assert "单张图片内部构图" in request.prompt
    assert "inset" in request.prompt
    assert "手中钥匙的特写" in request.prompt
    assert "不得生成文字或气泡" in request.prompt
