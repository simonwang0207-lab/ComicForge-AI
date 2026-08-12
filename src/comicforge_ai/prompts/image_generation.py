"""Provider-aware image prompts for one comic panel at a time."""

from __future__ import annotations

import re

from comicforge_ai.layout import (
    custom_frame_for_sequence,
    custom_frame_prompt,
    panel_target_aspect_ratio,
)
from comicforge_ai.schemas import (
    CharacterProfile,
    ComicProject,
    PanelImageRequest,
    PanelSpec,
)

PROMPT_PROFILE_NEUTRAL = "neutral"
PROMPT_PROFILE_RICH_LOCALIZED = "rich_localized"
PROMPT_PROFILE_SD_COMFYUI = "sd_comfyui"
PROMPT_PROFILE_ANIMAGINE_XL = "animagine_xl"

_SUPPORTED_PROMPT_PROFILES = {
    PROMPT_PROFILE_NEUTRAL,
    PROMPT_PROFILE_RICH_LOCALIZED,
    PROMPT_PROFILE_SD_COMFYUI,
    PROMPT_PROFILE_ANIMAGINE_XL,
}

_STYLE_PROMPTS = {
    "清新治愈": "clean 2D comic illustration, crisp expressive line art, flat cel shading, bright controlled colors",
    "热血日漫": "dynamic 2D action manga illustration, crisp ink lines, flat cel shading, dramatic lighting",
    "复古像素": "retro pixel-art comic, deliberate pixel clusters, limited coherent palette",
    "水彩童话": "storybook watercolor comic illustration, clean readable outlines, light paper texture, warm whimsical colors",
    "科幻霓虹": "neon 2D science-fiction comic illustration, crisp line art, cel shading, cinematic colored lighting",
}

_ANIMAGINE_STYLE_PROMPTS = {
    "清新治愈": (
        "(healing anime style:1.25), wholesome atmosphere, gentle pastel palette, "
        "soft daylight, airy composition, clean anime lineart, simple cel shading"
    ),
    "热血日漫": (
        "(dynamic shounen manga style:1.25), energetic action pose, dramatic "
        "perspective, bold ink lines, high contrast cel shading, vivid colors"
    ),
    "复古像素": (
        "(retro pixel art style:1.25), deliberate pixel clusters, limited color "
        "palette, crisp hard edges, classic game illustration"
    ),
    "水彩童话": (
        "(storybook watercolor style:1.25), delicate transparent washes, light paper "
        "texture, warm whimsical palette, readable illustration outlines"
    ),
    "科幻霓虹": (
        "(neon science fiction anime style:1.25), cyan and magenta rim light, "
        "futuristic environment, cinematic contrast, crisp cel shading"
    ),
}

_ANIMAGINE_CUSTOM_STYLE_TAGS = (
    (("清新", "治愈", "温馨"), "healing anime, wholesome, soft daylight"),
    (("可爱", "萌", "Q版"), "cute anime, charming, simplified appealing shapes"),
    (("粉彩", "柔和"), "gentle pastel palette, soft controlled colors"),
    (("水彩",), "storybook watercolor, transparent washes, light paper texture"),
    (("童话", "绘本"), "whimsical storybook illustration, warm fairytale mood"),
    (("像素",), "retro pixel art, deliberate pixel clusters, limited palette"),
    (("复古",), "retro comic illustration, vintage color palette"),
    (("热血", "动作"), "dynamic shounen manga, action pose, dramatic perspective"),
    (("科幻", "未来"), "science fiction anime, futuristic environment"),
    (("霓虹", "赛博"), "neon cyberpunk lighting, cyan and magenta rim light"),
    (("黑白", "墨线"), "black and white manga, bold expressive ink lines"),
    (("古风", "国风"), "classical Chinese inspired illustration, elegant linework"),
)

_PLACEHOLDER_VALUES = {"", "none", "null", "n/a", "na", "未指定", "无"}

_POSITION_PROMPTS = {
    "top_left": "upper left",
    "top_center": "upper center",
    "top_right": "upper right",
    "middle_left": "middle left",
    "middle_right": "middle right",
    "bottom_left": "lower left",
    "bottom_right": "lower right",
}

_COMMON_NEGATIVE_PROMPT = (
    "text, letters, numbers, caption, subtitle, speech bubble, thought bubble, "
    "sound effect lettering, watermark, logo, signature, signage, duplicate subject, "
    "multiple copies of the same character, repeated face, extra limbs, malformed "
    "anatomy, low quality, blurry, smeared details"
)

_ANIMAGINE_QUALITY_NEGATIVE_PROMPT = (
    "lowres, low score, bad score, worst quality, bad anatomy, bad hands, "
    "extra limbs, extra digits, missing fingers, deformed"
)

_PAINTERLY_NEGATIVE_PROMPT = (
    "oil painting, impressionism, impasto, thick brush strokes, loose painterly "
    "rendering, photorealistic photo, 3d render"
)

_WATERCOLOR_NEGATIVE_PROMPT = (
    "oil painting, impressionism, impasto, thick opaque paint, photorealistic photo, "
    "3d render"
)

_SINGLE_SCENE_NEGATIVE_PROMPT = (
    "comic page, manga page, storyboard, contact sheet, collage, split screen, "
    "multiple panels, panel grid, inset frame, border, frame divider, many tiny scenes"
)

_MULTI_SHOT_NEGATIVE_PROMPT = (
    "comic page, manga page, storyboard, contact sheet, dense collage, panel grid, "
    "more than two views, many tiny scenes"
)

_FORBIDDEN_POSITIVE_ITEM = (
    r"(?:text|letters?|numbers?|captions?|watermarks?|logos?|signs?|"
    r"(?:speech\s+)?bubbles?|borders?)"
)
_FORBIDDEN_POSITIVE_CLAUSE = re.compile(
    rf"\s*(?:,|;)?\s*(?:no|without)\s+{_FORBIDDEN_POSITIVE_ITEM}"
    rf"(?:\s*(?:,|or|and)\s*{_FORBIDDEN_POSITIVE_ITEM})*[.;]?",
    flags=re.IGNORECASE,
)


def build_panel_image_request(
    project: ComicProject,
    panel: PanelSpec,
    *,
    profile: str = PROMPT_PROFILE_NEUTRAL,
    reference_character_names: tuple[str, ...] = (),
) -> PanelImageRequest:
    """Build one panel prompt using the selected Provider's prompt profile."""
    _validate_profile(profile)
    if profile == PROMPT_PROFILE_ANIMAGINE_XL:
        prompt = _build_animagine_xl_prompt(
            project,
            panel,
            reference_character_names=reference_character_names,
        )
    elif profile == PROMPT_PROFILE_SD_COMFYUI:
        prompt = _build_sd_comfyui_prompt(
            project,
            panel,
            reference_character_names=reference_character_names,
        )
    else:
        prompt = _build_rich_localized_prompt(project, panel)
    return PanelImageRequest(panel=panel, style=project.style, prompt=prompt)


def build_panel_negative_prompt(
    panel: PanelSpec,
    user_negative_prompt: str = "",
    *,
    profile: str = PROMPT_PROFILE_NEUTRAL,
    project: ComicProject | None = None,
) -> str:
    """Return only exclusions appropriate to the selected Provider profile."""
    _validate_profile(profile)
    user_value = user_negative_prompt.strip()
    if profile not in {
        PROMPT_PROFILE_SD_COMFYUI,
        PROMPT_PROFILE_ANIMAGINE_XL,
    }:
        return user_value
    composition_negative = (
        _MULTI_SHOT_NEGATIVE_PROMPT
        if panel.composition != "single" and panel.subshots
        else _SINGLE_SCENE_NEGATIVE_PROMPT
    )
    style_negative = (
        _WATERCOLOR_NEGATIVE_PROMPT
        if project is not None and project.style.strip() == "水彩童话"
        else _PAINTERLY_NEGATIVE_PROMPT
    )
    subject_negative = (
        _animagine_subject_negative(project, panel)
        if profile == PROMPT_PROFILE_ANIMAGINE_XL and project is not None
        else ""
    )
    return ", ".join(
        part
        for part in (
            user_value,
            (
                _ANIMAGINE_QUALITY_NEGATIVE_PROMPT
                if profile == PROMPT_PROFILE_ANIMAGINE_XL
                else ""
            ),
            _COMMON_NEGATIVE_PROMPT,
            subject_negative,
            composition_negative,
            style_negative,
        )
        if part
    )


def _build_animagine_xl_prompt(
    project: ComicProject,
    panel: PanelSpec,
    *,
    reference_character_names: tuple[str, ...] = (),
) -> str:
    """Build a tag-forward prompt for Animagine XL without affecting Recraft."""
    style = _animagine_style_prompt(project)
    target_ratio = panel_target_aspect_ratio(
        project.layout_mode,
        project.panels,
        panel.sequence,
        project.custom_layout,
    )
    orientation = (
        "wide horizontal composition"
        if target_ratio >= 1.8
        else "horizontal composition"
        if target_ratio >= 1.15
        else "portrait composition"
        if target_ratio <= 0.85
        else "square composition"
    )
    prompt_parts = [
        "masterpiece, high score, great score, absurdres, safe",
        style,
        "anime comic illustration, single scene, one camera view, full-frame composition",
        orientation,
        (
            "story scene and described action take priority over any reference image; "
            "use reference only for character identity, never copy its pose, framing, "
            "background or camera angle"
        ),
        _animagine_scene_prompt(
            project,
            panel,
            reference_character_names=reference_character_names,
        ),
        (
            "recognizable coherent featured subject, intact identity and silhouette, "
            "all defining features attached to the same subject"
        ),
        _animagine_character_anchor(
            project,
            panel,
            reference_character_names=reference_character_names,
        ),
        (
            "same visual style across the comic series, consistent species and body "
            "anatomy, consistent character design, consistent colors, clean lineart, "
            "controlled cel shading, coherent background"
        ),
    ]
    return ", ".join(part for part in prompt_parts if part)


def _animagine_style_prompt(project: ComicProject) -> str:
    """Return an English, visibly differentiated style anchor for Animagine."""
    clean_style = project.style.strip()
    if clean_style in _ANIMAGINE_STYLE_PROMPTS:
        return _ANIMAGINE_STYLE_PROMPTS[clean_style]
    model_style = project.story_bible.visual_style_prompt.strip()
    if model_style and model_style.isascii():
        return f"({model_style}:1.2), consistent series art direction"
    combined = f"{clean_style} {project.story_bible.visual_style}".strip()
    if combined.isascii() and combined:
        return f"({combined}:1.2), consistent series art direction"
    matched = [
        tags
        for markers, tags in _ANIMAGINE_CUSTOM_STYLE_TAGS
        if any(marker in combined for marker in markers)
    ]
    if matched:
        return ", ".join(dict.fromkeys(matched)) + ", consistent series art direction"
    return (
        "(polished 2D anime comic style:1.2), coherent line art, controlled color "
        "palette, consistent series art direction"
    )


def _selected_characters(
    project: ComicProject,
    panel: PanelSpec,
) -> list[CharacterProfile]:
    named_characters = set(panel.characters)
    if not named_characters:
        return []
    return [
        character
        for character in project.characters
        if character.name in named_characters
    ][:3]


def _clean_character_parts(character: CharacterProfile) -> list[str]:
    raw_parts = [
        f"entity type {character.entity_type}" if character.entity_type else "",
        (
            f"species or category {character.species_or_category}"
            if character.species_or_category
            else ""
        ),
        (
            f"body structure {character.body_structure}"
            if character.body_structure
            else ""
        ),
        ", ".join(character.identity_features),
        character.visual_prompt,
        character.clothing,
        ", ".join(character.signature_items),
        ", ".join(character.primary_colors),
    ]
    return [
        part.strip()
        for part in raw_parts
        if part.strip().lower() not in _PLACEHOLDER_VALUES and part.strip().isascii()
    ]


def _animagine_character_anchor(
    project: ComicProject,
    panel: PanelSpec,
    *,
    reference_character_names: tuple[str, ...] = (),
) -> str:
    """Use provider-neutral structured identity before the scene description."""
    referenced = set(reference_character_names).intersection(panel.characters)
    descriptions: list[str] = []
    for character in _selected_characters(project, panel):
        if character.name in referenced:
            continue
        parts = _clean_character_parts(character)
        description = ", ".join(dict.fromkeys(parts))
        if description:
            descriptions.append(description)
    anchors: list[str] = []
    if referenced:
        anchors.append(
            "REFERENCE IMAGE IDENTITY LOCK: same character as the reference image; "
            "preserve identity, outfit, hairstyle and face from the reference image; "
            "change only action, expression, scene and camera"
        )
    if not descriptions:
        return "; ".join(anchors)
    quantity = (
        "one text-described subject"
        if len(descriptions) == 1
        else f"exactly {len(descriptions)} text-described subjects"
    )
    anchors.append(
        f"SUBJECT IDENTITY LOCK: {quantity}; keep the exact entity type, species or "
        "category, body structure, silhouette, colors, clothing and signature items "
        "described here; never replace it with another kind of entity: "
        + "; ".join(descriptions)
    )
    return "; ".join(anchors)


def _animagine_scene_prompt(
    project: ComicProject,
    panel: PanelSpec,
    *,
    reference_character_names: tuple[str, ...] = (),
) -> str:
    """Keep scene/camera information separate from the identity anchor.

    Text providers often repeat a character's eyes, face, body and colors inside
    ``image_prompt``. Repeating those tokens after the identity anchor can make a
    diffusion model over-emphasize one body part. Prefer the English storyboard
    description and only fall back to ``image_prompt`` for legacy projects.
    """
    detailed_storyboard_is_english = bool(
        panel.visual_description.strip()
        and panel.action.strip()
        and panel.visual_description.strip().isascii()
        and panel.action.strip().isascii()
    )
    candidates = (
        (panel.visual_description, panel.action, panel.scene)
        if detailed_storyboard_is_english
        else (
            panel.image_prompt,
            panel.visual_description,
            panel.action,
            panel.scene,
        )
    )
    scene_parts = [
        value.strip()
        for value in candidates
        if value.strip() and value.strip().isascii()
    ]
    scene_prompt = ", ".join(dict.fromkeys(scene_parts))
    if not scene_prompt:
        scene_prompt = panel.image_prompt or panel.visual_description
    scene_prompt = _strip_referenced_character_appearance(
        scene_prompt,
        project,
        panel,
        reference_character_names,
    )
    return _clean_positive_prompt(scene_prompt).rstrip(".")


def _animagine_subject_negative(
    project: ComicProject,
    panel: PanelSpec,
) -> str:
    selected = _selected_characters(project, panel)
    if not selected:
        return ""
    provider_agnostic = (
        "different entity type, changed species or category, changed body structure, "
        "character replacement, inconsistent identity, inconsistent silhouette, "
        "featured subject replaced by an isolated body part, detached defining feature, "
        "unintended abstract substitute for the featured subject"
    )
    avoided = [
        item.strip()
        for character in selected
        for item in character.avoid_features
        if item.strip() and item.strip().isascii()
    ]
    return ", ".join(dict.fromkeys((provider_agnostic, *avoided)))


def _build_sd_comfyui_prompt(
    project: ComicProject,
    panel: PanelSpec,
    *,
    reference_character_names: tuple[str, ...] = (),
) -> str:
    """Build the concise English prompt used by the local SD/ComfyUI workflow."""
    structure_prompt = (
        "TWO-VIEW COMPOSITION: one dominant continuous scene with one small "
        "supporting inset detail, maximum two views."
        if panel.composition != "single" and panel.subshots
        else (
            "SINGLE-SCENE COMPOSITION: one continuous scene, one camera view, "
            "one full-frame composition."
        )
    )
    prompt_parts = [
        (
            "ONE FINISHED 2D COMIC PANEL: crisp outlines, flat cel shading, "
            "clear focal subject, readable silhouette, coherent background."
        ),
        structure_prompt,
        _clean_positive_prompt(
            _strip_referenced_character_appearance(
                panel.image_prompt,
                project,
                panel,
                reference_character_names,
            )
        ),
        _sd_character_anchor(
            project,
            panel,
            reference_character_names=reference_character_names,
        ),
        _sd_project_style_lock(project),
    ]
    target_ratio = panel_target_aspect_ratio(
        project.layout_mode,
        project.panels,
        panel.sequence,
        project.custom_layout,
    )
    orientation = (
        "wide horizontal"
        if target_ratio >= 1.8
        else "horizontal"
        if target_ratio >= 1.15
        else "tall portrait"
        if target_ratio <= 0.85
        else "square"
    )
    prompt_parts.append(
        f"TARGET PANEL SHAPE: {orientation}, approximately {target_ratio:.2f}:1. "
        "Keep the complete featured character inside this canvas."
    )
    if panel.character_positions:
        positions = [
            _POSITION_PROMPTS[position]
            for position in panel.character_positions.values()
            if position in _POSITION_PROMPTS
        ]
        if positions:
            prompt_parts.append(
                "Place the main characters around the "
                + " and ".join(dict.fromkeys(positions))
                + " of the composition."
            )
    reserved_regions = panel.reserved_bubble_regions or [
        item.preferred_position for item in panel.text_items
    ]
    positions = [
        _POSITION_PROMPTS[item]
        for item in dict.fromkeys(reserved_regions)
        if item in _POSITION_PROMPTS
    ]
    if positions:
        prompt_parts.append(
            "Leave clean, natural, low-detail negative space at the "
            + ", ".join(positions)
            + ". Keep faces, hands, and important props in the detailed area."
        )
    return "\n".join(part for part in prompt_parts if part)


def _build_rich_localized_prompt(project: ComicProject, panel: PanelSpec) -> str:
    """Preserve the detailed Stage 3 prompt used successfully by Recraft."""
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
        if character.name in named_characters
    ]
    prompt_parts = [
        f"漫画视觉风格：{project.style}",
        f"漫画内容语言：{project.content_language}（仅供后期本地气泡排版，图片本身不得含文字）",
        f"统一故事时代与地点：{project.story_bible.time_period}；{project.story_bible.location}",
        f"统一视觉设定：{project.story_bible.visual_style or project.style}",
        f"场景：{panel.scene}",
        f"画面与构图：{panel.visual_description}",
        f"人物动作与表情：{panel.action}",
        _localized_project_style_lock(project),
    ]
    if project.layout_mode == "custom_page":
        frame_instruction = custom_frame_prompt(
            custom_frame_for_sequence(project.custom_layout, panel.sequence)
        )
        if frame_instruction:
            prompt_parts.append(f"最终页面画幅约束：{frame_instruction}")
    if character_details:
        prompt_parts.append(
            "全局一致角色设定（不得改变服装、发型和主色）："
            + "；".join(character_details)
        )
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
    if re.search(r"[\u4e00-\u9fff]", panel.image_prompt):
        prompt_parts.append(f"原始分镜绘图提示词：{panel.image_prompt}")
    prompt_parts.append(
        "只生成漫画画面。不要生成文字；画面中绝对不要出现任何语言的字母、数字、对白、"
        "旁白、拟声词、标题、标志、水印、边框、分镜编号或现成气泡。"
    )
    return "\n".join(part for part in prompt_parts if not part.endswith("："))


def _clean_positive_prompt(prompt: str) -> str:
    """Remove negative clauses that diffusion models may reinforce as concepts."""
    cleaned = _FORBIDDEN_POSITIVE_CLAUSE.sub("", prompt.strip())
    cleaned = re.sub(
        r"\b(?:minimal|plain|empty|blank)\s+background\b",
        "detailed story-relevant environment",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bminimal\s+(?:details?|detail)\b",
        "rich story-scene detail",
        cleaned,
        flags=re.IGNORECASE,
    )
    words = cleaned.replace("\n", " ").split()
    value = " ".join(words[:55]).strip(" ,;.")
    return value + "." if value else ""


def _sd_project_style_lock(project: ComicProject) -> str:
    """Return one compact English style anchor for the local SD workflow."""
    style = _STYLE_PROMPTS.get(
        project.style.strip(),
        project.style.strip()
        if project.style.strip().isascii()
        else "polished comic illustration, coherent line art, controlled color palette",
    )
    return (
        f"SERIES STYLE: {style}. Keep the same character species, facial design, body "
        "proportions, clothing, signature props, line work, color palette, and rendering. "
        "Use clean shapes and controlled edges; do not switch to painterly rendering."
    )


def _sd_character_anchor(
    project: ComicProject,
    panel: PanelSpec,
    *,
    reference_character_names: tuple[str, ...] = (),
) -> str:
    """Build a short English identity anchor that SD 1.5 can consistently parse."""
    referenced = set(reference_character_names).intersection(panel.characters)
    descriptions: list[str] = []
    for character in _selected_characters(project, panel):
        if character.name in referenced:
            continue
        english_parts = _clean_character_parts(character)
        if english_parts:
            descriptions.append(", ".join(dict.fromkeys(english_parts)))
    anchors: list[str] = []
    if referenced:
        anchors.append(
            "REFERENCE IMAGE IDENTITY LOCK: same character as the reference image; "
            "preserve identity, outfit, hairstyle and face from the reference image; "
            "change only action, expression, scene and camera"
        )
    if not descriptions:
        return "; ".join(anchors)
    quantity = (
        "exactly one featured character"
        if len(descriptions) == 1
        else f"exactly {len(descriptions)} featured characters"
    )
    anchors.append(
        f"CHARACTER IDENTITY LOCK: {quantity}: "
        + "; ".join(descriptions)
        + ". Keep this exact design and do not create duplicate copies."
    )
    return "; ".join(anchors)


_REFERENCE_APPEARANCE_TERMS = re.compile(
    r"\b(?:hair|hairstyle|bangs|braids?|ponytail|buns?|eyes?|face|facial|skin|"
    r"robe|shirt|jacket|coat|dress|skirt|pants|shorts|armor|armour|uniform|"
    r"costume|outfit|clothing|garment|boots?|shoes?|hat|helmet|horns?|ears?)\b",
    flags=re.IGNORECASE,
)


def _strip_referenced_character_appearance(
    prompt: str,
    project: ComicProject,
    panel: PanelSpec,
    reference_character_names: tuple[str, ...],
) -> str:
    """Remove known text-profile traits when a reference owns character identity."""
    referenced = set(reference_character_names).intersection(panel.characters)
    if not referenced or not prompt.strip():
        return prompt

    fragments: set[str] = set()
    for character in project.characters:
        if character.name not in referenced:
            continue
        values = (
            character.appearance,
            character.visual_prompt,
            character.hairstyle,
            character.facial_features,
            character.clothing,
            *character.identity_features,
        )
        for value in values:
            if not value or not value.isascii():
                continue
            candidates = {
                value.strip(),
                re.sub(r"\s*\([^)]*\)", "", value).strip(),
            }
            candidates.update(
                part.strip(" ,.;:")
                for part in re.split(r"\s+(?:with|and)\s+|[,;]", value)
            )
            fragments.update(
                candidate
                for candidate in candidates
                if len(candidate) >= 4
                and _REFERENCE_APPEARANCE_TERMS.search(candidate)
            )

    cleaned = prompt
    for fragment in sorted(fragments, key=len, reverse=True):
        cleaned = re.sub(
            rf"(?<!\w){re.escape(fragment)}(?!\w)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = re.sub(r"\bwith\s+(?:and\s+)?(?=(?:on|in|at|by|under|over)\b)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:with|and)\s*(?=[,;.])", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" ,.;")


def _localized_project_style_lock(project: ComicProject) -> str:
    """Return the original detailed style anchor used by rich Providers."""
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


def _validate_profile(profile: str) -> None:
    if profile not in _SUPPORTED_PROMPT_PROFILES:
        raise ValueError(f"未知图片提示词配置：{profile}")
