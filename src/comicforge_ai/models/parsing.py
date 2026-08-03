"""Safe extraction and validation of model-generated comic JSON."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from comicforge_ai.models.base import TextModelOutputError
from comicforge_ai.schemas import (
    ComicLocalization,
    ComicProject,
    ContentLanguage,
    LayoutMode,
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)

_PROJECT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "story": (
        "summary",
        "synopsis",
        "story_summary",
        "story_outline",
        "outline",
        "plot",
        "故事",
        "故事梗概",
    ),
    "characters": (
        "character_profiles",
        "character_list",
        "cast",
        "roles",
        "角色",
        "角色列表",
        "角色设定",
    ),
}


def extract_json_object(raw_output: str) -> dict[str, Any]:
    """Extract one JSON object from plain text or a Markdown code fence."""
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise TextModelOutputError("模型返回内容为空")

    stripped = raw_output.strip()
    fence_match = _JSON_FENCE.search(stripped)
    candidate = fence_match.group(1).strip() if fence_match else stripped
    start = candidate.find("{")
    if start < 0:
        raise TextModelOutputError("模型返回内容中没有 JSON 对象")
    fragment = candidate[start:]
    try:
        value, _ = json.JSONDecoder().raw_decode(fragment)
    except json.JSONDecodeError as exc:
        # Local models occasionally put a literal line break/tab inside a JSON
        # string. Python's lenient decoder safely accepts control characters while
        # preserving normal JSON structure; it does not execute any model output.
        if "Invalid control character" in exc.msg:
            try:
                value, _ = json.JSONDecoder(strict=False).raw_decode(fragment)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(value, dict):
                    return value
        detail = _json_error_advice(exc)
        raise TextModelOutputError(
            f"模型返回的 JSON 格式无效（第 {exc.lineno} 行第 {exc.colno} 列）："
            f"{detail}"
        ) from exc
    if not isinstance(value, dict):
        raise TextModelOutputError("模型 JSON 顶层必须是对象")
    return value


def _json_error_advice(exc: json.JSONDecodeError) -> str:
    """Map parser details to safe, user-facing advice without exposing output."""
    message = exc.msg.lower()
    if "unterminated string" in message or exc.pos >= max(0, len(exc.doc) - 2):
        return "模型输出可能被长度上限截断，请提高输出长度或缩短故事说明后重试"
    if "invalid control character" in message:
        return "字符串包含未正确转义的换行或制表符"
    if "expecting ',' delimiter" in message:
        return "字符串可能含有未转义引号，或对象字段之间缺少逗号"
    if "expecting property name" in message:
        return "对象字段名或末尾逗号不符合 JSON 语法"
    return "模型没有返回合法的完整 JSON；系统将尝试一次干净重生成"


def _require_keys(value: dict[str, Any], required: set[str], location: str) -> None:
    missing = sorted(required - value.keys())
    if missing:
        prefix = f"{location}." if location else ""
        raise TextModelOutputError(
            "模型 JSON 缺少字段：" + ", ".join(prefix + key for key in missing)
        )


def _normalize_project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a small allow-list of common Provider field aliases.

    Missing content is never invented. If neither the canonical field nor one
    of its known aliases is present, normal validation still reports it.
    """
    normalized = dict(payload)
    for canonical, aliases in _PROJECT_FIELD_ALIASES.items():
        if canonical in normalized:
            continue
        for alias in aliases:
            if alias in normalized:
                normalized[canonical] = normalized[alias]
                break
    return normalized


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
    language: ContentLanguage = "zh-CN",
    layout_mode: LayoutMode = "grid",
    allow_multi_shot_panels: bool = False,
) -> ComicProject:
    """Safely parse provider output and enforce the expected request context."""
    payload = _normalize_project_payload(extract_json_object(raw_output))
    _validate_required_shape(payload)
    payload["theme"] = theme
    payload["style"] = style
    payload["panel_count"] = panel_count
    payload["content_language"] = language
    payload["layout_mode"] = layout_mode
    payload["allow_multi_shot_panels"] = allow_multi_shot_panels
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


def parse_reviewed_project(raw_output: str, draft: ComicProject) -> ComicProject:
    """Parse a reviewed script while preserving immutable request context."""
    payload = _normalize_project_payload(extract_json_object(raw_output))
    _validate_required_shape(payload)
    payload["theme"] = draft.theme
    payload["style"] = draft.style
    payload["panel_count"] = draft.panel_count
    payload["content_language"] = draft.content_language
    payload["layout_mode"] = draft.layout_mode
    payload["allow_multi_shot_panels"] = draft.allow_multi_shot_panels
    payload["user_story_guidance"] = draft.user_story_guidance
    payload["revision_history"] = [
        item.model_dump(mode="json") for item in draft.revision_history
    ]
    payload["script_reviewed"] = True
    try:
        return ComicProject.model_validate(payload)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors()[:5]
        ]
        raise TextModelOutputError(
            "模型修订稿结构校验失败：" + "；".join(problems)
        ) from exc


def parse_comic_translation(
    raw_output: str,
    project: ComicProject,
    target_language: ContentLanguage,
) -> ComicProject:
    """Apply a compact validated translation without changing visual fields."""
    payload = _normalize_translation_payload(
        extract_json_object(raw_output),
        project,
    )
    try:
        translation = ComicLocalization.model_validate(payload)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in exc.errors()[:5]
        ]
        raise TextModelOutputError(
            "漫画文字翻译结构校验失败：" + "；".join(problems)
        ) from exc

    expected_sequences = [panel.sequence for panel in project.panels]
    if [panel.sequence for panel in translation.panels] != expected_sequences:
        raise TextModelOutputError("翻译结果的分格序号或数量与原项目不一致")

    updated = project.model_copy(deep=True)
    updated.title = translation.title.strip()
    updated.content_language = target_language
    for panel, translated in zip(updated.panels, translation.panels, strict=True):
        if len(translated.text_items) != len(panel.text_items):
            raise TextModelOutputError(
                f"第 {panel.sequence} 格翻译文字项数量与原项目不一致"
            )
        for item, translated_text in zip(
            panel.text_items,
            translated.text_items,
            strict=True,
        ):
            clean = translated_text.strip()
            if not clean:
                raise TextModelOutputError(
                    f"第 {panel.sequence} 格存在空白翻译文字"
                )
            item.text = clean
        _sync_panel_legacy_text(panel)
    _validate_translation_language(updated, target_language)
    return updated


def _normalize_translation_payload(
    payload: dict[str, Any],
    project: ComicProject,
) -> dict[str, Any]:
    """Normalize stable-ID and legacy panel-array translation responses."""
    normalized = dict(payload)
    texts = normalized.get("texts")
    if isinstance(texts, list):
        texts = {
            str(item.get("id")): item.get("text")
            for item in texts
            if isinstance(item, dict) and item.get("id") is not None
        }
    if isinstance(texts, dict):
        expected_ids = [
            f"P{panel.sequence}-I{index}"
            for panel in project.panels
            for index, _ in enumerate(panel.text_items)
        ]
        normalized_texts = {
            str(item_id): (
                value.get("text")
                if isinstance(value, dict) and isinstance(value.get("text"), str)
                else value
            )
            for item_id, value in texts.items()
        }
        missing = [item_id for item_id in expected_ids if item_id not in normalized_texts]
        unexpected = [
            item_id for item_id in normalized_texts if item_id not in expected_ids
        ]
        if missing:
            raise TextModelOutputError(
                "翻译结果缺少文字项 ID：" + "、".join(missing)
            )
        if unexpected:
            raise TextModelOutputError(
                "翻译结果包含未知文字项 ID：" + "、".join(unexpected)
            )
        normalized["panels"] = [
            {
                "sequence": panel.sequence,
                "text_items": [
                    normalized_texts[f"P{panel.sequence}-I{index}"]
                    for index, _ in enumerate(panel.text_items)
                ],
            }
            for panel in project.panels
        ]
        return normalized

    panels = normalized.get("panels")
    if not isinstance(panels, list):
        return normalized
    normalized_panels: list[Any] = []
    for panel in panels:
        if not isinstance(panel, dict):
            normalized_panels.append(panel)
            continue
        normalized_panel = dict(panel)
        items = normalized_panel.get("text_items")
        if isinstance(items, list):
            normalized_panel["text_items"] = [
                item.get("text")
                if isinstance(item, dict) and isinstance(item.get("text"), str)
                else item
                for item in items
            ]
        normalized_panels.append(normalized_panel)
    normalized["panels"] = normalized_panels
    return normalized


def _validate_translation_language(
    project: ComicProject,
    target_language: ContentLanguage,
) -> None:
    visible = " ".join(
        [project.title]
        + [item.text for panel in project.panels for item in panel.text_items]
    )
    latin = len(re.findall(r"[A-Za-z]", visible))
    cjk = len(re.findall(r"[\u3400-\u9fff]", visible))
    kana = len(re.findall(r"[\u3040-\u30ff]", visible))
    if target_language == "en" and cjk > max(2, latin // 2):
        raise TextModelOutputError("模型返回的文字仍以中文/日文为主，未完成英文翻译")
    if target_language == "zh-CN" and latin > max(12, cjk * 2):
        raise TextModelOutputError("模型返回的文字仍以英文为主，未完成中文翻译")
    if target_language == "ja-JP" and kana < 2:
        raise TextModelOutputError("模型返回内容缺少日文假名，可能未完成日文翻译")


def _sync_panel_legacy_text(panel: Any) -> None:
    speeches = []
    narrations = []
    for item in panel.text_items:
        if item.type in {"speech", "thought"}:
            speeches.append(f"{item.speaker}：{item.text}" if item.speaker else item.text)
        elif item.type == "narration":
            narrations.append(item.text)
    panel.dialogue = " ".join(speeches)
    panel.narration = " ".join(narrations)
