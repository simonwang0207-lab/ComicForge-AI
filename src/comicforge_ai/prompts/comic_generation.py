"""Prompts for structured comic planning."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """你是专业漫画编剧和分镜师。请把用户创意转化为结构化漫画方案。
你必须保持角色设定前后一致，让每格承担不同的叙事作用；对白应简短，适合漫画气泡；
image_prompt 应明确角色外观、动作、场景、构图、光线和视觉风格，供后续图像模型使用。
只输出一个合法 JSON 对象，不要使用 Markdown 代码块，不要在 JSON 外添加解释。"""


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


def _schema_example(panel_count: int) -> dict[str, Any]:
    return {
        "title": "漫画标题",
        "theme": "用户提供的主题",
        "style": "用户提供的风格",
        "panel_count": panel_count,
        "story": "完整但精炼的故事梗概",
        "characters": [
            {
                "name": "角色名",
                "role": "主角/配角等定位",
                "appearance": "稳定、可识别的外观特征",
                "personality": "性格设定",
                "visual_prompt": "供后续绘图复用的角色视觉提示词",
            }
        ],
        "panels": [
            {
                "sequence": 1,
                "scene": "时间、地点和场景",
                "visual_description": "镜头、构图、光线和画面内容",
                "characters": ["本格出场角色名"],
                "action": "角色动作、表情和互动",
                "dialogue": "允许为空字符串",
                "narration": "允许为空字符串",
                "image_prompt": "包含一致角色特征和风格的完整绘图提示词",
            }
        ],
    }


def build_comic_generation_messages(
    theme: str,
    style: str,
    panel_count: int,
) -> list[dict[str, str]]:
    """Build provider-neutral chat messages for a complete comic plan."""
    request = {
        "theme": theme,
        "style": style,
        "panel_count": panel_count,
    }
    schema_json = json.dumps(
        _schema_example(panel_count), ensure_ascii=False, indent=2
    )
    user_prompt = f"""创作要求：
{json.dumps(request, ensure_ascii=False)}

必须恰好生成 {panel_count} 个 panels，sequence 从 1 连续编号到 {panel_count}。
characters 可以有任意合理数量；每格的 characters 只能使用角色列表中已有的 name。
所有字段都必须出现，即使 dialogue 或 narration 没有内容也要使用空字符串。

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
) -> list[dict[str, str]]:
    """Ask once more for a corrected full JSON object after parse failure."""
    messages = build_comic_generation_messages(theme, style, panel_count)
    repair_prompt = f"""上一次输出无法通过校验：{error_message}
请修复并重新输出完整 JSON。不要解释，不要省略字段。

上一次输出：
{invalid_output[:12000]}
"""
    messages.append({"role": "assistant", "content": invalid_output[:12000]})
    messages.append({"role": "user", "content": repair_prompt})
    return messages
