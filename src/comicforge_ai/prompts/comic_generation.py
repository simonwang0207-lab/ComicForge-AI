"""Prompts for structured comic planning, review, and repair."""

from __future__ import annotations

import json
from typing import Any

from comicforge_ai.schemas import ComicProject, ContentLanguage, LayoutMode

SYSTEM_PROMPT = """你是专业漫画编剧、事实核查员和分镜师。请把用户创意转化为结构化漫画方案。
先建立 story_bible，再写分镜。必须保持人物身份、时间线、道具状态和角色设定前后一致；
每格承担不同的叙事作用，动作必须能由单张静态图片表现；对白简短自然，适合漫画气泡；
每格应规划角色位置、气泡位置和干净负空间。image_prompt 应明确统一角色外观、当前动作、
场景、构图、光线、视觉风格和负空间，并禁止画面中出现文字、水印或现成气泡。
对无法确定的事实不要编造为确定事实。
只输出一个合法 JSON 对象，不要使用 Markdown 代码块，不要在 JSON 外添加解释。"""

LANGUAGE_NAMES: dict[ContentLanguage, str] = {
    "zh-CN": "简体中文",
    "en": "English",
    "ja-JP": "日本語",
}


def add_no_think_directive(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Copy messages and add Qwen's prompt fallback when API think is unsupported."""
    updated = [message.copy() for message in messages]
    for message in reversed(updated):
        if message.get("role") == "user":
            message["content"] = "/no_think\n" + message["content"]
            break
    return updated


def add_truncation_retry_directive(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Retry a truncated structured response without echoing partial JSON."""
    updated = [message.copy() for message in messages]
    updated.append(
        {
            "role": "user",
            "content": (
                "上一次输出达到长度上限并被截断。请从原始要求重新生成完整 JSON，"
                "不要续写或复述残缺内容。保持全部必要字段和分格，但压缩措辞：故事梗概、"
                "人物字段、每格画面/动作/绘图提示词和审查说明只保留生成漫画所需信息；"
                "对白与旁白保持简短。只输出完整 JSON。"
            ),
        }
    )
    return updated


def _schema_example(
    panel_count: int,
    language: ContentLanguage,
    layout_mode: LayoutMode = "grid",
    allow_multi_shot_panels: bool = False,
) -> dict[str, Any]:
    return {
        "title": "漫画标题",
        "title_candidates": ["候选标题一", "候选标题二", "候选标题三"],
        "theme": "用户提供的主题",
        "style": "用户提供的风格",
        "panel_count": panel_count,
        "content_language": language,
        "layout_mode": layout_mode,
        "allow_multi_shot_panels": allow_multi_shot_panels,
        "user_story_guidance": "用户补充的故事事实；没有时为空字符串",
        "story": "完整但精炼的故事梗概",
        "characters": [
            {
                "name": "角色名",
                "role": "主角/配角等定位",
                "appearance": "稳定、可识别的外观特征",
                "personality": "性格设定",
                "visual_prompt": "供后续绘图复用的角色视觉提示词",
                "age": "年龄或年龄段",
                "gender": "性别或外观性别表达",
                "hairstyle": "固定发型与发色",
                "facial_features": "固定面部特征",
                "clothing": "固定服装",
                "signature_items": ["标志性道具"],
                "era": "所属时代",
                "primary_colors": ["主色调"],
            }
        ],
        "story_bible": {
            "time_period": "故事发生时间",
            "location": "主要地点",
            "characters": [
                {
                    "name": "角色名",
                    "identity": "准确身份与关系",
                    "appearance": "固定外观",
                    "clothing": "固定服装",
                    "motivation": "本故事中的动机",
                }
            ],
            "key_objects": ["贯穿故事的关键道具及状态"],
            "timeline": ["按因果顺序排列的事件"],
            "visual_style": "所有分格统一视觉风格",
        },
        "panels": [
            {
                "sequence": 1,
                "scene": "时间、地点和场景",
                "visual_description": "镜头、构图、光线和画面内容",
                "characters": ["本格出场角色名"],
                "action": "角色动作、表情和互动",
                "dialogue": "允许为空字符串，兼容字段",
                "narration": "允许为空字符串，兼容字段",
                "narrative_role": "建立/发展/转折/结果等",
                "importance": 3,
                "composition": "single",
                "subshots": [],
                "character_positions": {"角色名": "bottom_right"},
                "reserved_bubble_regions": ["top_left"],
                "text_items": [
                    {
                        "type": "speech",
                        "speaker": "角色名",
                        "text": "简短自然的气泡台词",
                        "preferred_position": "top_left",
                        "speaker_position": "bottom_right",
                        "speaker_anchor": {"x": 0.75, "y": 0.68},
                        "presentation": "auto",
                    },
                    {
                        "type": "narration",
                        "speaker": None,
                        "text": "必要且不重复对白的简短旁白",
                        "preferred_position": "top_right",
                        "speaker_position": None,
                        "speaker_anchor": None,
                        "presentation": "auto",
                    },
                ],
                "image_prompt": "统一角色特征、当前动作、构图、负空间和禁字要求",
            }
        ],
        "review_notes": [],
        "revision_history": [],
        "script_reviewed": False,
    }


def build_comic_generation_messages(
    theme: str,
    style: str,
    panel_count: int,
    language: ContentLanguage = "zh-CN",
    layout_mode: LayoutMode = "grid",
    allow_multi_shot_panels: bool = False,
    source_story: str = "",
) -> list[dict[str, str]]:
    """Build provider-neutral chat messages for a complete comic draft."""
    request = {
        "theme": theme,
        "style": style,
        "panel_count": panel_count,
        "content_language": language,
        "layout_mode": layout_mode,
        "allow_multi_shot_panels": allow_multi_shot_panels,
    }
    clean_source_story = source_story.strip()
    schema_json = json.dumps(
        _schema_example(
            panel_count, language, layout_mode, allow_multi_shot_panels
        ),
        ensure_ascii=False,
        indent=2,
    )
    source_story_block = (
        f"""
用户已经提供故事或剧本原文。它是本次分镜的最高优先级内容依据：
--- 用户原文开始 ---
{clean_source_story}
--- 用户原文结束 ---

必须依据用户原文提炼故事、人物、时间线和分镜，不得另编一套故事；可以为了适配
{panel_count} 格漫画压缩情节和台词，但不得改变关键事实、人物关系、事件顺序、因果、
否定含义和结局。原文没有说明的事实不要擅自补成确定内容。
"""
        if clean_source_story
        else "\n用户没有提供完整剧本，请根据漫画主题创作故事。\n"
    )
    user_prompt = f"""创作要求：
{json.dumps(request, ensure_ascii=False)}
{source_story_block}

必须恰好生成 {panel_count} 个 panels，sequence 从 1 连续编号到 {panel_count}。
characters 可以有任意合理数量；每格的 characters 只能使用角色列表中已有的 name。
标题、概要、对白、旁白、拟声词和常见人物译名必须使用{LANGUAGE_NAMES[language]}；JSON 字段名保持英文。
对白建议每项不超过 25 个中文/日文字符或 12 个英文单词，不能写成长段解释。
title_candidates 生成 3 个自然具体、贴合核心冲突的候选标题，title 选择其中最佳一个。
避免“XX的暗影/命运/传奇/觉醒”等与具体情节无关的模板标题，除非用户明确要求。
text_items 支持 speech、thought、narration、sfx；旧版 dialogue/narration 没有内容时使用空字符串。
每个文字项的 presentation 默认使用 auto；普通对白使用 bubble，必要的场景旁白使用 text_only，
拟声词使用 burst。只有刻意需要说明框时才使用 caption，不要把所有文字都做成矩形卡片。
位置只能使用 top_left、top_center、top_right、middle_left、middle_right、bottom_left、bottom_right。
相邻分格必须具备清晰因果，不能让角色无故出现或消失。所有字段都必须出现。
importance 使用 1–5 表示画面重要度，高潮和关键揭示应更高。
allow_multi_shot_panels=false 时，每格 composition=single 且 subshots=[]。
为 true 时，也只在确有必要时使用 split_horizontal、split_vertical、inset 或 montage，
不能每格都拆分；subshots 最多 3 个，并保持一个清晰主画面。若某格同时包含主动作与关键人物反应、
线索/道具细节揭示、远近两个相关动作或需要对照的时刻，应主动选择 1–2 个最有表现力的分格使用
多镜头构图，而不是全部返回 single；辅助镜头不得简单重复主画面。

严格按照以下 JSON 结构输出：
{schema_json}
"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_json_repair_messages(
    invalid_output: str,
    error_message: str,
    theme: str,
    style: str,
    panel_count: int,
    language: ContentLanguage = "zh-CN",
    layout_mode: LayoutMode = "grid",
    allow_multi_shot_panels: bool = False,
    source_story: str = "",
) -> list[dict[str, str]]:
    """Regenerate a complete object from clean context after parse failure."""
    messages = build_comic_generation_messages(
        theme,
        style,
        panel_count,
        language,
        layout_mode,
        allow_multi_shot_panels,
        source_story,
    )
    repair_prompt = f"""上一次输出无法通过校验：{error_message}
请从头重新生成完整 JSON，不要续写或仿照上一次的残缺结构。
顶层必须包含 title、story、characters、panels；characters 中每个对象和
panels 中每个对象都必须包含示例结构列出的全部字段。
panels 必须恰好包含 {panel_count} 个对象，sequence 从 1 连续编号。
只输出一个完整 JSON 对象，不要解释，不要使用 Markdown，不要省略字段。
"""
    messages.append({"role": "user", "content": repair_prompt})
    return messages


def build_story_review_messages(project: ComicProject) -> list[dict[str, str]]:
    """Request a fact-aware review and a fully revised project."""
    requirements = [
        "人物是否属于同一合理时间线，身份和关系是否准确、自洽",
        "相邻分格是否存在明确因果，角色、道具和场景状态是否连续",
        "每格动作是否能由一张静态图片清晰表现",
        "整体是否形成建立—发展—转折—结果（按格数合理调整）",
        "对白是否简短自然，旁白是否与对白重复",
        "是否存在明显事实冲突，或把不确定内容写成确定事实",
        "角色位置、气泡位置和负空间是否互相匹配",
    ]
    payload = project.model_dump(mode="json", exclude={"output_path", "panel_images"})
    user_prompt = f"""下面是漫画初稿：
{json.dumps(payload, ensure_ascii=False, indent=2)}

请逐项审查：
{json.dumps(requirements, ensure_ascii=False, indent=2)}

先在内部完成审查，再直接输出修订后的完整 ComicProject JSON。保持 panel_count、theme、style、
content_language、layout_mode、allow_multi_shot_panels 不变；更新 title_candidates、story_bible、
角色、分镜、text_items 和 image_prompt；将关键修订理由写入
review_notes，并设置 script_reviewed=true。不要输出审查过程或 JSON 之外的文字。
"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_story_guidance_revision_messages(
    project: ComicProject,
    user_guidance: str,
) -> list[dict[str, str]]:
    """Rebuild a storyboard using user-supplied facts as authoritative context."""
    # The old full project can be very large and is explicitly considered wrong by
    # the user. Keep only immutable request context and a short orientation summary.
    context = {
        "theme": project.theme,
        "style": project.style,
        "panel_count": project.panel_count,
        "content_language": project.content_language,
        "current_title": project.title,
        "current_story_for_reference_only": project.story,
        "current_character_names": [item.name for item in project.characters],
        "layout_mode": project.layout_mode,
        "allow_multi_shot_panels": project.allow_multi_shot_panels,
        "previous_user_story_guidance": project.user_story_guidance,
        "revision_rounds_completed": len(project.revision_history),
    }
    schema_json = json.dumps(
        _schema_example(
            project.panel_count,
            project.content_language,
            project.layout_mode,
            project.allow_multi_shot_panels,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    user_prompt = f"""当前请求上下文（旧故事仅供定位，不是事实来源）：
{json.dumps(context, ensure_ascii=False, indent=2)}

用户认为当前故事不合格，并提供了以下故事事实与创作要求：
--- 用户故事依据开始 ---
{user_guidance}
--- 用户故事依据结束 ---

previous_user_story_guidance 是此前各轮已确认的累计约束，本轮用户故事依据是针对当前版本的
追加修正；两者必须同时遵守。只有本轮明确要求替换或纠正旧约束时，才以本轮为准。
两者共同构成本次改写的最高优先级事实来源。不要沿用与它冲突的旧情节，也不要把不确定的
历史、原著或人物关系擅自补写成确定事实。请先据此重写故事梗概和 story_bible，再重新设计
全部 {project.panel_count} 格分镜，而不是只修改某一格。保持 theme、style、panel_count 和
content_language、layout_mode、allow_multi_shot_panels 不变；sequence 必须从 1 连续编号。
每格仍须具有不同叙事作用、清晰因果、
适合静态画面的动作、简短气泡文字、角色位置、气泡预留区和完整 image_prompt。
为避免结构化结果被截断，story 控制在 300 字以内；人物的每个文字字段控制在 80 字以内；
每格 scene、visual_description 和 action 各控制在 100 字以内，image_prompt 控制在 220 字以内；
review_notes 最多 3 条。保持信息完整但不要重复同一事实或堆砌形容词。

在输出 JSON 中把 user_story_guidance 设为空字符串；程序会在校验通过后安全写入用户原文，
不要把用户原文复制进 JSON 字符串。重新生成 3 个具体自然的 title_candidates 并选择最佳 title；
请在 review_notes 中简要说明根据用户依据修订了哪些内容；
设置 script_reviewed=true。只输出可通过 ComicProject 校验的完整 JSON，不要输出解释或 Markdown。

严格按照以下结构输出；panels 必须实际包含 {project.panel_count} 个对象：
{schema_json}
"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_story_guidance_repair_messages(
    project: ComicProject,
    user_guidance: str,
    invalid_output: str,
    error_message: str,
) -> list[dict[str, str]]:
    """Repair malformed JSON returned by a user-guided storyboard revision."""
    messages = build_story_guidance_revision_messages(project, user_guidance)
    # Do not echo a long/truncated malformed response back to a small local model.
    # All authoritative inputs are already present above, so a clean regeneration is
    # safer and uses much less context.
    messages.append(
        {
            "role": "user",
            "content": (
                f"按用户故事依据生成的修订稿无法通过结构校验：{error_message}\n"
                "请从干净上下文重新生成，保留用户事实约束，只输出修复后的完整 JSON，"
                "字段不得省略。不要复述或延续上一次的错误 JSON。"
            ),
        }
    )
    return messages


def build_review_repair_messages(
    project: ComicProject,
    invalid_output: str,
    error_message: str,
) -> list[dict[str, str]]:
    """Repair a malformed review response without executing model output."""
    messages = build_story_review_messages(project)
    messages.append({"role": "assistant", "content": invalid_output[:12000]})
    messages.append(
        {
            "role": "user",
            "content": (
                f"修订稿无法通过结构校验：{error_message}\n"
                "请只重新输出修复后的完整 JSON，字段不得省略。"
            ),
        }
    )
    return messages
