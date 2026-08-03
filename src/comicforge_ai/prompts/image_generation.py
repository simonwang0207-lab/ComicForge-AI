"""Provider-independent image prompts for one comic panel at a time."""

from __future__ import annotations

from comicforge_ai.layout import custom_frame_for_sequence, custom_frame_prompt
from comicforge_ai.schemas import ComicProject, PanelImageRequest, PanelSpec


def build_panel_image_request(
    project: ComicProject,
    panel: PanelSpec,
) -> PanelImageRequest:
    """Combine only the visual context needed for one panel image."""
    named_characters = set(panel.characters)
    character_details = [
        "；".join(
            part
            for part in (
                character.name,
                character.appearance,
                character.hairstyle,
                character.facial_features,
                character.clothing,
                "、".join(character.signature_items),
                "、".join(character.primary_colors),
                character.visual_prompt,
            )
            if part
        )
        for character in project.characters
        if not named_characters or character.name in named_characters
    ]
    prompt_parts = [
        f"漫画视觉风格：{project.style}",
        f"漫画内容语言：{project.content_language}（仅供后期本地气泡排版，图片本身不得含文字）",
        f"统一故事时代与地点：{project.story_bible.time_period}；{project.story_bible.location}",
        f"统一视觉设定：{project.story_bible.visual_style or project.style}",
        f"场景：{panel.scene}",
        f"画面与构图：{panel.visual_description}",
        f"人物动作与表情：{panel.action}",
        _project_style_lock(project),
    ]
    if project.layout_mode == "custom_page":
        frame_instruction = custom_frame_prompt(
            custom_frame_for_sequence(project.custom_layout, panel.sequence)
        )
        if frame_instruction:
            prompt_parts.append(f"最终页面画幅约束：{frame_instruction}")
    if character_details:
        prompt_parts.append("全局一致角色设定（不得改变服装、发型和主色）：" + "；".join(character_details))
    if panel.character_positions:
        prompt_parts.append(
            "角色构图位置："
            + "；".join(
                f"{name}位于{position}"
                for name, position in panel.character_positions.items()
            )
        )
    if panel.composition != "single" and panel.subshots:
        prompt_parts.append(
            "单张图片内部构图："
            f"使用 {panel.composition} 漫画构图；保留一个明确主画面，并加入以下辅助镜头："
            + "；".join(
                f"{item.shot_type}位于{item.position}，{item.visual_description}，"
                f"重点{item.focus or '清晰可辨'}"
                for item in panel.subshots
            )
            + "。辅助镜头之间使用清楚但自然的漫画分隔，不得生成文字或气泡。"
        )
    reserved_regions = panel.reserved_bubble_regions or [
        item.preferred_position for item in panel.text_items
    ]
    if reserved_regions:
        prompt_parts.append(
            "气泡构图预留："
            + "、".join(dict.fromkeys(reserved_regions))
            + "区域必须保留自然、干净、低细节的负空间；人物面部、手部和关键道具不要进入这些区域"
        )
    prompt_parts.extend(
        [
            f"原始分镜绘图提示词：{panel.image_prompt}",
            (
                "只生成漫画画面。不要生成文字；画面中绝对不要出现任何语言的字母、数字、对白、"
                "旁白、拟声词、标题、标志、水印、边框、分镜编号或现成气泡。"
            ),
        ]
    )
    return PanelImageRequest(
        panel=panel,
        style=project.style,
        prompt="\n".join(part for part in prompt_parts if not part.endswith("：")),
    )


def _project_style_lock(project: ComicProject) -> str:
    """Return one exact project-wide style anchor reused by every panel call."""
    palette = list(
        dict.fromkeys(
            color.strip()
            for character in project.characters
            for color in character.primary_colors
            if color.strip()
        )
    )
    palette_text = (
        "、".join(palette)
        if palette
        else "由当前风格确定的一套固定主色、阴影色和背景色"
    )
    return (
        "全项目画风锁定（每格必须完全一致）："
        f"固定采用“{project.style}”；"
        f"统一视觉说明“{project.story_bible.visual_style or project.style}”；"
        f"固定调色板为“{palette_text}”；"
        "所有分格保持完全相同的线条粗细、像素/笔触密度、色温、饱和度、"
        "阴影方式和材质表现。人类角色必须使用自然且跨格一致的肤色，"
        "不得因夜景、戏剧色调或背景配色变成蓝色、紫色、灰色或不同人种肤色，"
        "除非角色设定明确如此。不得在不同分格切换单色、双色、全彩或不同画师风格。"
    )
