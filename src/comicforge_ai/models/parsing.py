"""Safe extraction and validation of model-generated comic JSON."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from comicforge_ai.models.base import TextModelOutputError
from comicforge_ai.schemas import ComicProject

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def extract_json_object(raw_output: str) -> dict[str, Any]:
    """Extract one JSON object from plain text or a Markdown code fence."""
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise TextModelOutputError("模型返回内容为空")

    stripped = raw_output.strip()
    fence_match = _JSON_FENCE.search(stripped)
    candidate = fence_match.group(1).strip() if fence_match else stripped
    decoder = json.JSONDecoder()
    start = candidate.find("{")
    if start < 0:
        raise TextModelOutputError("模型返回内容中没有 JSON 对象")
    try:
        value, _ = decoder.raw_decode(candidate[start:])
    except json.JSONDecodeError as exc:
        raise TextModelOutputError(
            f"模型返回的 JSON 格式无效（第 {exc.lineno} 行第 {exc.colno} 列）"
        ) from exc
    if not isinstance(value, dict):
        raise TextModelOutputError("模型 JSON 顶层必须是对象")
    return value


def _require_keys(value: dict[str, Any], required: set[str], location: str) -> None:
    missing = sorted(required - value.keys())
    if missing:
        prefix = f"{location}." if location else ""
        raise TextModelOutputError(
            "模型 JSON 缺少字段：" + ", ".join(prefix + key for key in missing)
        )


def _validate_required_shape(payload: dict[str, Any]) -> None:
    _require_keys(payload, {"title", "story", "characters", "panels"}, "")
    characters = payload.get("characters")
    panels = payload.get("panels")
    if not isinstance(characters, list):
        raise TextModelOutputError("模型 JSON 字段 characters 必须是数组")
    if not isinstance(panels, list):
        raise TextModelOutputError("模型 JSON 字段 panels 必须是数组")
    for index, character in enumerate(characters):
        if not isinstance(character, dict):
            raise TextModelOutputError(f"characters[{index}] 必须是对象")
        _require_keys(
            character,
            {"name", "role", "appearance", "personality", "visual_prompt"},
            f"characters[{index}]",
        )
    required_panel_keys = {
        "sequence",
        "scene",
        "visual_description",
        "characters",
        "action",
        "dialogue",
        "narration",
        "image_prompt",
    }
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise TextModelOutputError(f"panels[{index}] 必须是对象")
        _require_keys(panel, required_panel_keys, f"panels[{index}]")


def parse_comic_project(
    raw_output: str,
    *,
    theme: str,
    style: str,
    panel_count: int,
) -> ComicProject:
    """Safely parse provider output and enforce the expected request context."""
    payload = extract_json_object(raw_output)
    _validate_required_shape(payload)
    payload["theme"] = theme
    payload["style"] = style
    payload["panel_count"] = panel_count
    try:
        return ComicProject.model_validate(payload)
    except ValidationError as exc:
        problems: list[str] = []
        for error_item in exc.errors()[:5]:
            location = ".".join(str(part) for part in error_item["loc"])
            problems.append(f"{location}: {error_item['msg']}")
        raise TextModelOutputError(
            "模型 JSON 结构校验失败：" + "；".join(problems)
        ) from exc
