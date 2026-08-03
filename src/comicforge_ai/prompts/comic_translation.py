"""Compact prompts for translating only visible comic lettering."""

from __future__ import annotations

import json

from comicforge_ai.schemas import ComicProject, ContentLanguage

LANGUAGE_NAMES: dict[ContentLanguage, str] = {
    "zh-CN": "简体中文",
    "en": "English",
    "ja-JP": "日本語",
}


def build_comic_translation_messages(
    project: ComicProject,
    target_language: ContentLanguage,
) -> list[dict[str, str]]:
    """Translate title/text through stable IDs instead of fragile arrays."""
    source_texts: dict[str, dict[str, str]] = {}
    for panel in project.panels:
        for index, item in enumerate(panel.text_items):
            source_texts[f"P{panel.sequence}-I{index}"] = {
                "type": item.type,
                "speaker": item.speaker or "",
                "text": item.text,
            }
    story_context = {
        "title": project.title,
        "story": project.story[:1600],
        "characters": [
            {
                "name": character.name,
                "role": character.role,
                "personality": character.personality,
            }
            for character in project.characters
        ],
        "panels": {
            f"P{panel.sequence}": {
                "scene": panel.scene,
                "action": panel.action,
                "narrative_role": panel.narrative_role,
            }
            for panel in project.panels
        },
    }
    example_text = {
        "zh-CN": ("翻译后的漫画标题", "对应原文字项的中文译文"),
        "en": ("Translated comic title", "Translated text for this item"),
        "ja-JP": ("翻訳後の漫画タイトル", "対応する文字項目の日本語訳"),
    }[target_language]
    output_example = {
        "title": example_text[0],
        "texts": {item_id: example_text[1] for item_id in source_texts},
    }
    target_rule = {
        "zh-CN": (
            "使用自然、简洁的现代简体中文漫画表达，避免照搬外语语序、机械书面语和翻译腔；"
            "所有 title 和 texts 值必须是简体中文译文，不得照抄非中文原文。"
        ),
        "en": (
            "Use concise, idiomatic comic-book English rather than word-for-word "
            "Chinese/Japanese syntax. Use natural contractions and spoken rhythm when "
            "appropriate. Every title and texts value MUST be English."
        ),
        "ja-JP": (
            "漫画として自然な日本語にローカライズし、人物関係に合う口調・敬語・語尾を選ぶ。"
            "中国語の語順を直訳せず、title と texts は必ず日本語訳にすること。"
        ),
    }[target_language]
    return [
        {
            "role": "system",
            "content": (
                "你是资深漫画本地化编辑，不是逐字翻译器。只翻译标题和可见文字，不改写"
                "剧情，不增加或删除分格与文字项。先在内部确认每句的说话人、意图、对象、"
                "否定、时序、因果和情绪，再写成目标语言读者自然会说的话，并在输出前对照"
                "原文检查语义。不得改变谁做了什么、人物关系、专名、数量、胜负或结局；"
                "不得为了顺口增添原文没有的事实。对白简短自然，旁白保持叙事语气，拟声词"
                f"使用目标语言漫画中的常见表达。{target_rule}只输出合法 JSON，不要 Markdown 或解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"把以下漫画文字翻译为{LANGUAGE_NAMES[target_language]}。\n"
                "texts 的键是不可更改的文字项 ID。输出必须保留完全相同的键集合；"
                "不得增加、删除、合并、拆分或重命名任何 ID。type、speaker 以及故事/分格"
                "上下文只用于消除歧义，不能翻译或输出这些上下文字段。角色姓名和专有名词在"
                "标题及全部分格中必须采用同一译法。为了适合气泡可以自然压缩句子，但不能"
                "省略改变情节的信息，也不要在译文前添加说话人姓名或解释标签。\n\n"
                "故事与分格上下文：\n"
                f"{json.dumps(story_context, ensure_ascii=False)}\n\n"
                "原文输入：\n"
                f"{json.dumps({'title': project.title, 'texts': source_texts}, ensure_ascii=False)}\n\n"
                "严格输出结构：\n"
                f"{json.dumps(output_example, ensure_ascii=False)}"
            ),
        },
    ]


def build_comic_translation_repair_messages(
    project: ComicProject,
    target_language: ContentLanguage,
    error_message: str,
) -> list[dict[str, str]]:
    """Request a clean small translation JSON after shape/JSON failure."""
    messages = build_comic_translation_messages(project, target_language)
    messages.append(
        {
            "role": "user",
            "content": (
                f"上一次翻译无法校验：{error_message}\n"
                "请从原始输入重新生成，仅输出完整合法 JSON。texts 必须逐字保留原始输入"
                "中的全部 ID 键，不得改变键名、数量或顺序；每个键只对应一个译文字符串。"
            ),
        }
    )
    return messages
