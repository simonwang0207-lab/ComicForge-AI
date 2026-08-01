"""Reusable valid model payloads for provider and parser tests."""

from typing import Any


def comic_payload(panel_count: int = 3) -> dict[str, Any]:
    characters = [
        {
            "name": "小雨",
            "role": "主角",
            "appearance": "短发、黄色雨衣",
            "personality": "乐观、细心",
            "visual_prompt": "短发女孩，黄色雨衣，圆形眼镜",
        }
    ]
    panels = [
        {
            "sequence": index,
            "scene": f"雨后的街道，第 {index} 个场景",
            "visual_description": f"中景，小雨观察第 {index} 条线索",
            "characters": ["小雨"],
            "action": "小雨蹲下观察并露出惊喜表情",
            "dialogue": "原来在这里！" if index == panel_count else "再找找看。",
            "narration": "雨渐渐停了。" if index == 1 else "",
            "image_prompt": "治愈水彩漫画，短发女孩穿黄色雨衣，雨后街道",
        }
        for index in range(1, panel_count + 1)
    ]
    return {
        "title": "雨后的线索",
        "theme": "寻找走失的小狗",
        "style": "治愈水彩",
        "panel_count": panel_count,
        "story": "小雨在雨后沿着脚印找到走失的小狗。",
        "characters": characters,
        "panels": panels,
    }
