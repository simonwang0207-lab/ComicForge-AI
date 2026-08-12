"""Safe extraction and validation of model-generated comic JSON."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from comicforge_ai.models.base import (
    TextModelOutputError,
    VisibleTextLanguageError,
)
from comicforge_ai.schemas import (
    ComicLocalization,
    ComicProject,
    ContentLanguage,
    LayoutMode,
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)

_PROJECT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": (
        "name",
        "comic_title",
        "project_title",
        "标题",
        "漫画标题",
    ),
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

_PANEL_SEQUENCE_ALIASES = (
    "index",
    "panel_index",
    "panel_number",
    "panel_no",
    "panel_id",
    "panel",
    "number",
    "序号",
    "格号",
    "分格序号",
    "分镜序号",
)

_TEXT_INDEX_ALIASES = (
    "text_index",
    "item_index",
    "text_number",
    "number",
    "序号",
    "索引",
    "文字序号",
)

_PANEL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "scene": ("setting", "location", "场景", "地点"),
    "visual_description": (
        "description", "visual", "shot_description",
        "画面描述", "构图描述",
    ),
    "characters": ("character_names", "cast", "角色", "出场角色"),
    "action": ("actions", "pose", "动作"),
    "dialogue": ("speech", "dialog", "对白", "台词"),
    "narration": ("caption", "narrator", "旁白"),
    "image_prompt": ("prompt", "visual_prompt", "image_description", "绘图提示词"),
}

_TEXT_TYPE_ALIASES = {
    "speech": "speech",
    "dialogue": "speech",
    "dialog": "speech",
    "对白": "speech",
    "对话": "speech",
    "thought": "thought",
    "thinking": "thought",
    "inner_monologue": "thought",
    "思考": "thought",
    "心理": "thought",
    "narration": "narration",
    "narrator": "narration",
    "caption": "narration",
    "旁白": "narration",
    "sfx": "sfx",
    "sound_effect": "sfx",
    "sound effect": "sfx",
    "拟声": "sfx",
    "拟声词": "sfx",
}
_PANEL_POSITIONS = {
    "top_left", "top_center", "top_right", "middle_left", "middle_right",
    "bottom_left", "bottom_right",
}
_PANEL_POSITION_ALIASES = {
    "upper_left": "top_left",
    "upper_center": "top_center",
    "upper_right": "top_right",
    "center_left": "middle_left",
    "center": "top_center",
    "middle_center": "top_center",
    "center_right": "middle_right",
    "lower_left": "bottom_left",
    "lower_center": "bottom_left",
    "bottom_center": "bottom_left",
    "lower_right": "bottom_right",
    "left": "middle_left",
    "right": "middle_right",
    "左上": "top_left",
    "上方": "top_center",
    "顶部": "top_center",
    "右上": "top_right",
    "左侧": "middle_left",
    "中央": "top_center",
    "中间": "top_center",
    "右侧": "middle_right",
    "左下": "bottom_left",
    "下方": "bottom_left",
    "底部": "bottom_left",
    "右下": "bottom_right",
}
_TEXT_PRESENTATIONS = {"auto", "bubble", "text_only", "caption", "burst"}


def _normalize_panel_position(value: Any) -> str | None:
    """Map common model spellings to the closed PanelPosition vocabulary."""
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = re.sub(r"[\s-]+", "_", value.strip().lower())
    if normalized in _PANEL_POSITIONS:
        return normalized
    alias = _PANEL_POSITION_ALIASES.get(normalized)
    if alias is not None:
        return alias

    compact = normalized.replace("_", "")
    semantic_aliases = (
        (("左上", "topleft", "upperleft"), "top_left"),
        (("右上", "topright", "upperright"), "top_right"),
        (("左下", "bottomleft", "lowerleft"), "bottom_left"),
        (("右下", "bottomright", "lowerright"), "bottom_right"),
        (("左侧", "middleleft", "centerleft"), "middle_left"),
        (("右侧", "middleright", "centerright"), "middle_right"),
        (("上方", "顶部", "topcenter", "uppercenter"), "top_center"),
        (("下方", "底部", "bottomcenter", "lowercenter", "centerbottom"), "bottom_left"),
        (("中央", "中间", "center", "middlecenter"), "top_center"),
    )
    for markers, position in semantic_aliases:
        if any(marker in compact for marker in markers):
            return position
    return None


def _normalize_anchor(value: Any) -> dict[str, float] | None:
    """Accept numeric anchor strings while discarding ambiguous coordinates."""
    if not isinstance(value, dict):
        return None
    coordinates: dict[str, float] = {}
    for axis in ("x", "y"):
        raw = value.get(axis)
        if isinstance(raw, bool):
            return None
        try:
            coordinate = float(raw)
        except (TypeError, ValueError):
            return None
        if not 0 <= coordinate <= 1:
            return None
        coordinates[axis] = coordinate
    return coordinates


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
    panels = normalized.get("panels")
    if isinstance(panels, list):
        normalized_panels: list[Any] = []
        for position, panel in enumerate(panels, start=1):
            if not isinstance(panel, dict):
                normalized_panels.append(panel)
                continue
            normalized_panel = dict(panel)
            if "sequence" not in normalized_panel:
                for alias in _PANEL_SEQUENCE_ALIASES:
                    if alias in normalized_panel:
                        normalized_panel["sequence"] = normalized_panel[alias]
                        break
                else:
                    # Array order is an unambiguous, deterministic sequence source.
                    normalized_panel["sequence"] = position
            for canonical, aliases in _PANEL_FIELD_ALIASES.items():
                if canonical in normalized_panel:
                    continue
                for alias in aliases:
                    if alias in normalized_panel:
                        normalized_panel[canonical] = normalized_panel[alias]
                        break
            normalized_panels.append(normalized_panel)
        normalized["panels"] = normalized_panels
    return normalized


def _apply_initial_panel_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply safe schema defaults only to a newly generated draft.

    Review patches deliberately skip this step so an omitted field can still
    inherit the corresponding value from the already validated draft.
    """
    normalized = dict(payload)
    panels = normalized.get("panels")
    if not isinstance(panels, list):
        return normalized
    normalized_panels: list[Any] = []
    for panel in panels:
        if not isinstance(panel, dict):
            normalized_panels.append(panel)
            continue
        updated = dict(panel)
        updated.setdefault("characters", [])
        updated.setdefault("action", "")
        updated.setdefault("dialogue", "")
        updated.setdefault("narration", "")
        if _is_empty_storyboard_text(updated.get("scene")):
            updated["scene"] = (
                (
                    ""
                    if _is_empty_storyboard_text(updated.get("visual_description"))
                    else updated.get("visual_description")
                )
                or updated.get("image_prompt")
                or ""
            )
        if _is_empty_storyboard_text(updated.get("visual_description")):
            updated["visual_description"] = (
                updated.get("scene") or updated.get("image_prompt") or ""
            )
        normalized_panels.append(updated)
    normalized["panels"] = normalized_panels
    return _infer_initial_panel_characters(normalized)


def _normalize_panel_layout_fields(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Repair optional model layout hints without inventing story content.

    Position hints are advisory, so unknown values are removed and schema
    defaults can apply. A subshot is retained only when the model supplied a
    usable visual description (possibly under a known alias or ``focus``).
    """
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return payload
    normalized_panels: list[Any] = []
    for panel in panels:
        if not isinstance(panel, dict):
            normalized_panels.append(panel)
            continue
        updated = dict(panel)

        positions = updated.get("character_positions")
        if isinstance(positions, dict):
            updated["character_positions"] = {
                str(name): position
                for name, raw_position in positions.items()
                if (position := _normalize_panel_position(raw_position)) is not None
            }

        regions = updated.get("reserved_bubble_regions")
        if isinstance(regions, list):
            normalized_regions: list[str] = []
            for raw_position in regions:
                position = _normalize_panel_position(raw_position)
                if position is not None and position not in normalized_regions:
                    normalized_regions.append(position)
            updated["reserved_bubble_regions"] = normalized_regions

        text_items = updated.get("text_items")
        if isinstance(text_items, list):
            normalized_items: list[Any] = []
            for item in text_items:
                if not isinstance(item, dict):
                    normalized_items.append(item)
                    continue
                normalized_item = dict(item)
                raw_preferred = normalized_item.get(
                    "preferred_position",
                    normalized_item.get("position"),
                )
                preferred = _normalize_panel_position(raw_preferred)
                if preferred is None:
                    normalized_item.pop("preferred_position", None)
                else:
                    normalized_item["preferred_position"] = preferred
                speaker_position = _normalize_panel_position(
                    normalized_item.get("speaker_position")
                )
                if speaker_position is None:
                    normalized_item.pop("speaker_position", None)
                else:
                    normalized_item["speaker_position"] = speaker_position
                anchor = _normalize_anchor(normalized_item.get("speaker_anchor"))
                if anchor is None:
                    normalized_item.pop("speaker_anchor", None)
                else:
                    normalized_item["speaker_anchor"] = anchor
                normalized_items.append(normalized_item)
            updated["text_items"] = normalized_items

        subshots = updated.get("subshots")
        if isinstance(subshots, list):
            normalized_subshots: list[dict[str, Any]] = []
            for subshot in subshots:
                if not isinstance(subshot, dict):
                    continue
                normalized_subshot = dict(subshot)
                description = next(
                    (
                        str(normalized_subshot[key]).strip()
                        for key in (
                            "visual_description",
                            "description",
                            "visual",
                            "shot_description",
                            "scene",
                            "action",
                            "画面描述",
                            "focus",
                        )
                        if normalized_subshot.get(key) is not None
                        and str(normalized_subshot[key]).strip()
                    ),
                    "",
                )
                if not description:
                    continue
                normalized_subshot["visual_description"] = description
                position = _normalize_panel_position(
                    normalized_subshot.get("position")
                )
                if position is None:
                    normalized_subshot.pop("position", None)
                else:
                    normalized_subshot["position"] = position
                normalized_subshots.append(normalized_subshot)
            updated["subshots"] = normalized_subshots

        normalized_panels.append(updated)
    normalized = dict(payload)
    normalized["panels"] = normalized_panels
    return normalized


def _is_empty_storyboard_text(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    return value.strip().lower() in {
        "single", "single scene", "single_scene", "none", "null", "n/a",
        "单格", "单镜头", "单场景",
    }


def _english_content_words(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    ignored = {
        "with", "young", "holding", "standing", "background", "comic",
        "style", "clean", "dramatic", "lighting", "character", "human",
    }
    return {
        word
        for word in re.findall(r"[a-z][a-z0-9-]{2,}", value.lower())
        if word not in ignored
    }


def _infer_initial_panel_characters(payload: dict[str, Any]) -> dict[str, Any]:
    """Recover omitted panel cast without coupling to a specific Provider.

    Evidence is restricted to structured speakers, literal character names and
    distinctive English profile tokens. Layout-only positions are a last resort
    because small models often fill them with the main character by default.
    """
    profiles = payload.get("characters")
    panels = payload.get("panels")
    if not isinstance(profiles, list) or not isinstance(panels, list):
        return payload
    profile_by_name = {
        str(item.get("name", "")).strip(): item
        for item in profiles
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    }
    normalized_panels: list[Any] = []
    for panel in panels:
        if not isinstance(panel, dict) or panel.get("characters"):
            normalized_panels.append(panel)
            continue
        updated = dict(panel)
        inferred: list[str] = []
        text_items = updated.get("text_items")
        if isinstance(text_items, list):
            for item in text_items:
                speaker = (
                    str(item.get("speaker", "")).strip()
                    if isinstance(item, dict)
                    else ""
                )
                if speaker in profile_by_name and speaker not in inferred:
                    inferred.append(speaker)
        searchable = " ".join(
            str(updated.get(key, ""))
            for key in ("scene", "visual_description", "action", "dialogue")
        )
        for name in profile_by_name:
            if name in searchable and name not in inferred:
                inferred.append(name)
        prompt_words = _english_content_words(updated.get("image_prompt"))
        for name, profile in profile_by_name.items():
            identity_words = _english_content_words(
                " ".join(
                    str(profile.get(key, ""))
                    for key in ("visual_prompt", "appearance", "clothing")
                )
            )
            if len(prompt_words.intersection(identity_words)) >= 2 and name not in inferred:
                inferred.append(name)
        positions = updated.get("character_positions")
        if not inferred and isinstance(positions, dict):
            inferred.extend(name for name in positions if name in profile_by_name)
        updated["characters"] = inferred
        if inferred and isinstance(positions, dict):
            updated["character_positions"] = {
                name: position
                for name, position in positions.items()
                if name in inferred
            }
        normalized_panels.append(updated)
    normalized = dict(payload)
    normalized["panels"] = normalized_panels
    return normalized


def _language_script_ratio(value: Any, language: ContentLanguage) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    relevant = [char for char in value if char.isalpha()]
    if not relevant:
        return 0.0
    if language == "zh-CN":
        matched = [char for char in relevant if "\u4e00" <= char <= "\u9fff"]
    elif language == "ja-JP":
        matched = [
            char
            for char in relevant
            if "\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff"
        ]
    else:
        matched = [char for char in relevant if char.isascii()]
    return len(matched) / len(relevant)


def _normalize_panel_display_language(
    payload: dict[str, Any],
    language: ContentLanguage,
    source_story: str = "",
) -> dict[str, Any]:
    """Keep user-facing storyboard fields in the selected content language.

    The English image prompt remains untouched. When a small model mixes an
    English visual/action field into an otherwise localized panel, the reliable
    localized scene is preferable to showing broken hybrids such as ``which吒``.
    """
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return payload
    story_segments = _story_segments_for_panels(
        source_story,
        len(panels),
        language,
    )
    has_visible_text = any(
        isinstance(panel, dict)
        and (
            str(panel.get("dialogue", "")).strip()
            or str(panel.get("narration", "")).strip()
            or any(
                isinstance(item, dict) and str(item.get("text", "")).strip()
                for item in panel.get("text_items", [])
                if isinstance(panel.get("text_items"), list)
            )
        )
        for panel in panels
    )
    normalized_panels: list[Any] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            normalized_panels.append(panel)
            continue
        updated = dict(panel)
        scene = updated.get("scene")
        localized_scene = _language_script_ratio(scene, language) >= 0.6
        grounded_segment = story_segments[index] if index < len(story_segments) else ""
        if not localized_scene and grounded_segment:
            updated["scene"] = grounded_segment
            updated["visual_description"] = grounded_segment
            updated["action"] = ""
            localized_scene = True
        if localized_scene:
            if _language_script_ratio(updated.get("visual_description"), language) < 0.35:
                updated["visual_description"] = scene
            if (
                updated.get("action")
                and _language_script_ratio(updated.get("action"), language) < 0.35
            ):
                updated["action"] = ""
        if not has_visible_text and grounded_segment:
            updated["narration"] = grounded_segment
        normalized_panels.append(updated)
    normalized = dict(payload)
    normalized["panels"] = normalized_panels
    return normalized


def _story_segments_for_panels(
    source_story: str,
    panel_count: int,
    language: ContentLanguage,
) -> list[str]:
    """Split user-provided facts into grounded, contiguous panel summaries."""
    clean = source_story.strip()
    if not clean or panel_count < 1 or _language_script_ratio(clean, language) < 0.35:
        return []
    sentences = [
        item.strip()
        for item in re.split(r"(?<=[。！？.!?])\s*", clean)
        if item.strip()
    ]
    if not sentences:
        return []
    segments: list[str] = []
    for index in range(panel_count):
        start = index * len(sentences) // panel_count
        end = (index + 1) * len(sentences) // panel_count
        selected = sentences[start:max(start + 1, end)]
        segments.append("".join(selected).strip()[:180])
    return segments


def _normalize_story_bible_lists(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize common structured list items emitted by small reviewers."""
    story_bible = payload.get("story_bible")
    if not isinstance(story_bible, dict):
        return payload
    updated_bible = dict(story_bible)
    field_keys = {
        "timeline": ("event", "description", "summary", "text", "action", "value"),
        "key_objects": ("name", "object", "item", "description", "text", "value"),
    }
    for field, candidate_keys in field_keys.items():
        items = updated_bible.get(field)
        if not isinstance(items, list):
            continue
        normalized_items: list[Any] = []
        for item in items:
            if isinstance(item, str):
                normalized_items.append(item)
                continue
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue
            value = next(
                (
                    str(item[key]).strip()
                    for key in candidate_keys
                    if item.get(key) is not None and str(item[key]).strip()
                ),
                "",
            )
            # Keep an unrecognized object invalid so Pydantic reports it rather
            # than silently discarding potentially important story information.
            normalized_items.append(value if value else item)
        updated_bible[field] = normalized_items
    normalized = dict(payload)
    normalized["story_bible"] = updated_bible
    return normalized


def _normalize_panel_character_names(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept reviewer character references as names or small name objects."""
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return payload
    normalized_panels: list[Any] = []
    for panel in panels:
        if not isinstance(panel, dict):
            normalized_panels.append(panel)
            continue
        updated = dict(panel)
        characters = updated.get("characters")
        if isinstance(characters, list):
            normalized_characters: list[Any] = []
            for character in characters:
                if isinstance(character, str):
                    normalized_characters.append(character)
                    continue
                if not isinstance(character, dict):
                    normalized_characters.append(character)
                    continue
                name = next(
                    (
                        str(character[key]).strip()
                        for key in ("name", "character", "character_name", "角色名")
                        if character.get(key) is not None
                        and str(character[key]).strip()
                    ),
                    "",
                )
                normalized_characters.append(name if name else character)
            updated["characters"] = normalized_characters
        normalized_panels.append(updated)
    normalized = dict(payload)
    normalized["panels"] = normalized_panels
    return normalized


def _validate_user_facing_storyboard(project: ComicProject) -> None:
    """Reject structurally valid but unusable drafts before image generation."""
    visible_text = [
        item.text.strip()
        for panel in project.panels
        for item in panel.text_items
        if item.text.strip()
    ]
    if not visible_text:
        raise TextModelOutputError(
            "所有分格的 dialogue、narration 和 text_items 均为空；"
            "请根据故事冲突至少生成一项对白、旁白、思考或拟声词"
        )
    wrong_language_items = sorted(
        (panel.sequence, index)
        for panel in project.panels
        for index, item in enumerate(panel.text_items)
        if item.type != "sfx"
        and item.text.strip()
        and _language_script_ratio(
            item.text,
            project.content_language,
        )
        < 0.35
    )
    wrong_language_panels = sorted(
        {sequence for sequence, _ in wrong_language_items}
    )
    if wrong_language_panels:
        sequences = "、".join(str(item) for item in wrong_language_panels)
        raise VisibleTextLanguageError(
            f"第 {sequences} 格的对白、思考或旁白未使用项目内容语言 "
            f"{project.content_language}；所有可见漫画文字必须使用用户选择的语言，"
            "只有 image_prompt 使用英文",
            project=project,
            panel_sequences=tuple(wrong_language_panels),
            text_indexes=tuple(wrong_language_items),
        )


def apply_visible_text_language_repair(
    raw_patch: str,
    draft: ComicProject,
) -> ComicProject:
    """Apply an index-based lettering patch without trusting other fields."""
    payload = extract_json_object(raw_patch)
    panels = payload.get("panels")
    if not isinstance(panels, list) or not panels:
        raise TextModelOutputError("可见文字修复结果缺少 panels 数组")

    updated = draft.model_copy(deep=True)
    panel_by_sequence = {panel.sequence: panel for panel in updated.panels}
    expected = {
        (panel.sequence, index)
        for panel in updated.panels
        for index, text_item in enumerate(panel.text_items)
        if text_item.type != "sfx"
        and text_item.text.strip()
        and _language_script_ratio(
            text_item.text,
            updated.content_language,
        )
        < 0.35
    }
    applied: set[tuple[int, int]] = set()
    touched_sequences: set[int] = set()
    expected_sequences = {sequence for sequence, _ in expected}

    for panel_patch_index, panel_patch in enumerate(panels):
        if not isinstance(panel_patch, dict):
            raise TextModelOutputError("可见文字修复的 panel 必须是对象")
        raw_sequence = _first_present_value(
            panel_patch,
            ("sequence", *_PANEL_SEQUENCE_ALIASES),
        )
        if raw_sequence is None and len(panels) == 1 and len(expected_sequences) == 1:
            sequence = next(iter(expected_sequences))
        else:
            sequence = _coerce_repair_integer(
                raw_sequence,
                error_message=(
                    "可见文字修复 panel 缺少有效 sequence"
                    f"（panels[{panel_patch_index}]）"
                ),
            )
        panel = panel_by_sequence.get(sequence)
        if panel is None:
            raise TextModelOutputError(
                f"可见文字修复包含未知分格 sequence={sequence}"
            )
        texts = _first_present_value(
            panel_patch,
            ("texts", "text_items", "items", "文字", "修复文字"),
        )
        if not isinstance(texts, list) or not texts:
            raise TextModelOutputError(
                f"第 {sequence} 格可见文字修复缺少 texts 数组"
            )
        expected_indexes = {
            index for expected_sequence, index in expected
            if expected_sequence == sequence
        }
        for text_patch_index, text_patch in enumerate(texts):
            if not isinstance(text_patch, dict):
                raise TextModelOutputError(
                    f"第 {sequence} 格 texts 项必须是对象"
                )
            raw_index = _first_present_value(
                text_patch,
                ("index", *_TEXT_INDEX_ALIASES),
            )
            if raw_index is None and len(texts) == 1 and len(expected_indexes) == 1:
                index = next(iter(expected_indexes))
            else:
                index = _coerce_repair_integer(
                    raw_index,
                    error_message=(
                        f"第 {sequence} 格文字修复缺少有效 index"
                        f"（texts[{text_patch_index}]）"
                    ),
                )
            key = (sequence, index)
            if key in applied:
                raise TextModelOutputError(
                    f"第 {sequence} 格文字索引 {index} 被重复修复"
                )
            if not 0 <= index < len(panel.text_items):
                raise TextModelOutputError(
                    f"第 {sequence} 格文字索引 {index} 超出范围"
                )
            text = _first_present_value(
                text_patch,
                (
                    "text",
                    "translated_text",
                    "revised_text",
                    "fixed_text",
                    "译文",
                    "修复文本",
                    "文字",
                ),
            )
            if not isinstance(text, str) or not text.strip():
                raise TextModelOutputError(
                    f"第 {sequence} 格文字索引 {index} 的修复文本为空"
                )
            panel.text_items[index].text = text.strip()
            applied.add(key)
            touched_sequences.add(sequence)

    missing = sorted(expected - applied)
    if missing:
        formatted = "、".join(f"{sequence}:{index}" for sequence, index in missing)
        raise TextModelOutputError(
            f"可见文字修复未覆盖全部错误文字索引：{formatted}"
        )

    for sequence in touched_sequences:
        panel = panel_by_sequence[sequence]
        panel.dialogue = " ".join(
            f"{item.speaker}：{item.text}" if item.speaker else item.text
            for item in panel.text_items
            if item.type in {"speech", "thought"}
        )
        panel.narration = " ".join(
            item.text for item in panel.text_items if item.type == "narration"
        )

    _validate_user_facing_storyboard(updated)
    _validate_dialogue_diversity(updated)
    return updated


def _first_present_value(
    payload: dict[str, Any],
    field_names: tuple[str, ...],
) -> Any:
    for field_name in field_names:
        if field_name in payload:
            return payload[field_name]
    return None


def _coerce_repair_integer(value: Any, *, error_message: str) -> int:
    """Accept common model spellings while rejecting ambiguous identifiers."""
    if isinstance(value, bool):
        raise TextModelOutputError(error_message)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdecimal():
            return int(stripped)
        match = re.fullmatch(
            r"(?:(?:panel|text|item)[_\s-]*|第\s*)?(\d+)\s*(?:格|项)?",
            stripped,
            flags=re.IGNORECASE,
        )
        if match:
            return int(match.group(1))
    raise TextModelOutputError(error_message)


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
        "image_prompt",
    }
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise TextModelOutputError(f"panels[{index}] 必须是对象")
        _require_keys(panel, required_panel_keys, f"panels[{index}]")


def _validate_dialogue_diversity(project: ComicProject) -> None:
    """Reject obvious repeated dialogue templates before costly image calls."""
    dialogues = [panel.dialogue.strip() for panel in project.panels if panel.dialogue.strip()]
    if len(dialogues) < 3:
        return
    prefixes: dict[str, int] = {}
    for dialogue in dialogues:
        compact = re.sub(r"[\s，。！？、：；,.!?:;\"'“”‘’]", "", dialogue)
        if len(compact) < 6:
            continue
        prefix = compact[:4]
        prefixes[prefix] = prefixes.get(prefix, 0) + 1
    threshold = max(3, (len(dialogues) * 2 + 2) // 3)
    repeated = next(
        (prefix for prefix, count in prefixes.items() if count >= threshold),
        "",
    )
    if repeated:
        raise TextModelOutputError(
            f"多格对白重复使用同一开头“{repeated}…”；请让每格对白体现不同反应、"
            "信息或冲突推进，不要套用同一句式"
        )


def _inherit_review_character_fields(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Complete partial review characters from the already validated draft.

    Review models commonly return only fields they changed.  Reusing the draft
    is safe here because it has already passed Pydantic validation; new
    characters without a matching name or position remain subject to the normal
    strict required-field checks.
    """
    characters = payload.get("characters")
    if not isinstance(characters, list):
        return payload
    draft_by_name = {item.name: item for item in draft.characters}
    merged_characters: list[Any] = []
    for index, character in enumerate(characters):
        if not isinstance(character, dict):
            merged_characters.append(character)
            continue
        name = character.get("name")
        source = draft_by_name.get(name) if isinstance(name, str) else None
        if source is None and index < len(draft.characters):
            source = draft.characters[index]
        if source is None:
            merged_characters.append(character)
            continue
        inherited = source.model_dump(mode="json")
        inherited.update(character)
        merged_characters.append(inherited)
    normalized = dict(payload)
    normalized["characters"] = merged_characters
    return normalized


def _inherit_missing_review_project_fields(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Restore unchanged required project fields omitted by a reviewer.

    Some small models return a partial full-project response instead of the
    requested ``project_patch`` envelope. The draft is already validated, so
    inheriting only wholly omitted story and character fields is deterministic
    and does not hide malformed values that the reviewer did return.
    """
    normalized = dict(payload)
    if "story" not in normalized:
        normalized["story"] = draft.story
    if "characters" not in normalized:
        normalized["characters"] = [
            character.model_dump(mode="json") for character in draft.characters
        ]
    return normalized


def _inherit_review_story_bible_fields(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Preserve validated story-wide visual anchors omitted by a reviewer."""
    story_bible = payload.get("story_bible")
    inherited = draft.story_bible.model_dump(mode="json")
    if isinstance(story_bible, dict):
        inherited.update(story_bible)
        reviewed_characters = story_bible.get("characters")
        if isinstance(reviewed_characters, list):
            draft_characters = draft.story_bible.characters
            draft_by_name = {item.name: item for item in draft_characters}
            merged_characters: list[Any] = []
            for index, character in enumerate(reviewed_characters):
                if not isinstance(character, dict):
                    merged_characters.append(character)
                    continue
                name = character.get("name")
                source = (
                    draft_by_name.get(name)
                    if isinstance(name, str)
                    else None
                )
                if source is None and index < len(draft_characters):
                    source = draft_characters[index]
                if source is None:
                    merged_characters.append(character)
                    continue
                merged = source.model_dump(mode="json")
                merged.update(character)
                merged_characters.append(merged)
            inherited["characters"] = merged_characters
    normalized = dict(payload)
    normalized["story_bible"] = inherited
    return normalized


def _inherit_review_panel_fields(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Complete partial review panels from their validated draft versions.

    A reviewer may legitimately return only the fields it changed. Matching is
    restricted to an existing sequence (or the same array position), so this
    never invents a new panel or hides a missing top-level panels array.
    """
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return payload
    draft_by_sequence = {item.sequence: item for item in draft.panels}
    merged_panels: list[Any] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            merged_panels.append(panel)
            continue
        sequence = panel.get("sequence")
        source = (
            draft_by_sequence.get(sequence)
            if isinstance(sequence, int)
            else None
        )
        if source is None and index < len(draft.panels):
            source = draft.panels[index]
        if source is None:
            merged_panels.append(panel)
            continue
        inherited = source.model_dump(mode="json")
        inherited.update(panel)
        merged_panels.append(inherited)
    normalized = dict(payload)
    normalized["panels"] = merged_panels
    return normalized


def _expand_review_patch(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Apply a compact reviewer patch to a validated draft locally."""
    patch = payload.get("project_patch")
    if not isinstance(patch, dict):
        return payload
    merged = draft.model_dump(mode="json")
    panel_patch = patch.get("panels")
    for key, value in patch.items():
        if key != "panels":
            merged[key] = value
    if "panels" in patch:
        panel_patch = _validate_review_panel_patch(
            panel_patch,
            draft,
            location="project_patch.panels",
        )
        panels_by_sequence = {
            item["sequence"]: item for item in merged["panels"]
        }
        for item in panel_patch:
            panels_by_sequence[item["sequence"]].update(item)
    for key in ("review_notes", "script_reviewed"):
        if key in payload:
            merged[key] = payload[key]
    return merged


def _validate_review_panel_patch(
    panels: Any,
    draft: ComicProject,
    *,
    location: str,
) -> list[dict[str, Any]]:
    """Validate that reviewer panel edits map unambiguously to draft panels."""
    if not isinstance(panels, list):
        raise TextModelOutputError(
            f"审查稿 panels 无法安全合并：{location} 必须是数组"
        )

    known_sequences = {panel.sequence for panel in draft.panels}
    seen_sequences: set[int] = set()
    validated: list[dict[str, Any]] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise TextModelOutputError(
                f"审查稿 panels 无法安全合并：{location}[{index}] 必须是对象"
            )
        sequence = panel.get("sequence")
        if type(sequence) is not int:
            raise TextModelOutputError(
                "审查稿 panels 无法安全合并："
                f"{location}[{index}].sequence 缺失或不是整数"
            )
        if sequence in seen_sequences:
            raise TextModelOutputError(
                "审查稿 panels 无法安全合并："
                f"{location} 中 sequence={sequence} 重复"
            )
        if sequence not in known_sequences:
            raise TextModelOutputError(
                "审查稿 panels 无法安全合并："
                f"{location} 中 sequence={sequence} 不属于已验证初稿"
            )
        seen_sequences.add(sequence)
        validated.append(panel)
    return validated


def _normalize_partial_review_panels_to_patch(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Treat a valid top-level panel subset as the patch small reviewers intended.

    The review prompt requires ``project_patch``, but small models sometimes return
    ``panels`` at the top level while including only the panels they changed. Panel
    deletion is not permitted during review, so a unique subset of known sequences
    can be merged safely into the already validated draft. Invalid subsets are
    rejected with a specific safe-merge error so the service
    can visibly retain the validated draft instead of reporting only a generic
    panel-count mismatch.
    """
    if isinstance(payload.get("project_patch"), dict):
        return payload
    if "panels" not in payload:
        return payload
    panels = payload["panels"]
    if not isinstance(panels, list):
        raise TextModelOutputError(
            "审查稿 panels 无法安全合并：顶层 panels 必须是数组"
        )
    if len(panels) > draft.panel_count:
        raise TextModelOutputError(
            "审查稿 panels 无法安全合并："
            f"返回了 {len(panels)} 格，但已验证初稿只有 {draft.panel_count} 格"
        )
    if len(panels) == draft.panel_count:
        return payload
    panels = _validate_review_panel_patch(
        panels,
        draft,
        location="panels",
    )
    patch_keys = {
        "title",
        "title_candidates",
        "story",
        "characters",
        "story_bible",
        "panels",
    }
    normalized = {
        key: value
        for key, value in payload.items()
        if key not in patch_keys
    }
    normalized["project_patch"] = {
        key: value for key, value in payload.items() if key in patch_keys
    }
    normalized["project_patch"]["panels"] = panels
    return normalized


def _reject_ambiguous_top_level_review_panel_subset(
    payload: dict[str, Any],
    draft: ComicProject,
) -> None:
    """Require an explicit sequence before generic normalization adds positions."""
    if isinstance(payload.get("project_patch"), dict):
        return
    panels = payload.get("panels")
    if not isinstance(panels, list) or len(panels) >= draft.panel_count:
        return
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            continue
        has_sequence = "sequence" in panel or any(
            alias in panel for alias in _PANEL_SEQUENCE_ALIASES
        )
        if not has_sequence:
            raise TextModelOutputError(
                "审查稿 panels 无法安全合并："
                f"panels[{index}].sequence 缺失，无法判断要修改初稿中的哪一格"
            )


def _normalize_review_text_items(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Normalize common reviewer text aliases without trusting malformed items."""
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return payload
    draft_by_sequence = {item.sequence: item for item in draft.panels}
    normalized_panels: list[Any] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            normalized_panels.append(panel)
            continue
        updated_panel = dict(panel)
        items = panel.get("text_items")
        if not isinstance(items, list):
            normalized_panels.append(updated_panel)
            continue
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_type = str(
                item.get("type")
                or item.get("kind")
                or item.get("category")
                or ""
            ).strip().lower()
            item_type = _TEXT_TYPE_ALIASES.get(raw_type)
            text = next(
                (
                    str(item[key]).strip()
                    for key in (
                        "text", "content", "value", "dialogue", "narration",
                        "caption", "sfx",
                    )
                    if item.get(key) is not None and str(item[key]).strip()
                ),
                "",
            )
            if not text:
                continue
            if item_type is None:
                if "narration" in item or "caption" in item:
                    item_type = "narration"
                elif "sfx" in item:
                    item_type = "sfx"
                else:
                    item_type = "speech" if item.get("speaker") else "narration"
            normalized_item: dict[str, Any] = {
                "type": item_type,
                "text": text,
            }
            speaker = item.get("speaker")
            if isinstance(speaker, str) and speaker.strip():
                normalized_item["speaker"] = speaker.strip()
            position = _normalize_panel_position(
                item.get("preferred_position") or item.get("position")
            )
            if position is not None:
                normalized_item["preferred_position"] = position
            speaker_position = _normalize_panel_position(
                item.get("speaker_position")
            )
            if speaker_position is not None:
                normalized_item["speaker_position"] = speaker_position
            presentation = item.get("presentation")
            if presentation in _TEXT_PRESENTATIONS:
                normalized_item["presentation"] = presentation
            anchor = _normalize_anchor(item.get("speaker_anchor"))
            if anchor is not None:
                normalized_item["speaker_anchor"] = anchor
            normalized_items.append(normalized_item)
        if normalized_items:
            updated_panel["text_items"] = normalized_items
        else:
            sequence = updated_panel.get("sequence")
            source = (
                draft_by_sequence.get(sequence)
                if isinstance(sequence, int)
                else draft.panels[index] if index < len(draft.panels) else None
            )
            if source is not None:
                updated_panel["text_items"] = [
                    item.model_dump(mode="json") for item in source.text_items
                ]
            else:
                updated_panel.pop("text_items", None)
        normalized_panels.append(updated_panel)
    normalized = dict(payload)
    normalized["panels"] = normalized_panels
    return normalized


def _normalize_review_panel_positions(
    payload: dict[str, Any],
    draft: ComicProject,
) -> dict[str, Any]:
    """Repair optional reviewer position aliases without weakening schemas."""
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return payload
    draft_by_sequence = {item.sequence: item for item in draft.panels}
    normalized_panels: list[Any] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            normalized_panels.append(panel)
            continue
        updated = dict(panel)
        sequence = updated.get("sequence")
        source = (
            draft_by_sequence.get(sequence)
            if isinstance(sequence, int)
            else draft.panels[index] if index < len(draft.panels) else None
        )
        positions = updated.get("character_positions")
        if isinstance(positions, dict):
            normalized_positions: dict[str, str] = {}
            for name, raw_position in positions.items():
                position = _normalize_panel_position(raw_position)
                if position is None and source is not None:
                    position = source.character_positions.get(str(name))
                if position is not None:
                    normalized_positions[str(name)] = position
            updated["character_positions"] = normalized_positions
        regions = updated.get("reserved_bubble_regions")
        if isinstance(regions, list):
            normalized_regions: list[str] = []
            for raw_position in regions:
                position = _normalize_panel_position(raw_position)
                if position is not None and position not in normalized_regions:
                    normalized_regions.append(position)
            if not normalized_regions and source is not None:
                normalized_regions = list(source.reserved_bubble_regions)
            updated["reserved_bubble_regions"] = normalized_regions
        normalized_panels.append(updated)
    normalized = dict(payload)
    normalized["panels"] = normalized_panels
    return normalized


def parse_comic_project(
    raw_output: str,
    *,
    theme: str,
    style: str,
    panel_count: int,
    language: ContentLanguage = "zh-CN",
    layout_mode: LayoutMode = "grid",
    allow_multi_shot_panels: bool = False,
    source_story: str = "",
) -> ComicProject:
    """Safely parse provider output and enforce the expected request context."""
    payload = _normalize_project_payload(extract_json_object(raw_output))
    payload = _apply_initial_panel_defaults(payload)
    payload = _normalize_panel_layout_fields(payload)
    payload = _normalize_panel_character_names(payload)
    payload = _normalize_panel_display_language(payload, language, source_story)
    payload = _normalize_story_bible_lists(payload)
    if not isinstance(payload.get("title"), str) or not payload["title"].strip():
        payload["title"] = theme.strip()
    _validate_required_shape(payload)
    payload["theme"] = theme
    payload["style"] = style
    payload["panel_count"] = panel_count
    payload["content_language"] = language
    payload["layout_mode"] = layout_mode
    payload["allow_multi_shot_panels"] = allow_multi_shot_panels
    try:
        project = ComicProject.model_validate(payload)
        _validate_user_facing_storyboard(project)
        _validate_dialogue_diversity(project)
        return project
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
    payload = extract_json_object(raw_output)
    _reject_ambiguous_top_level_review_panel_subset(payload, draft)
    payload = _normalize_project_payload(payload)
    payload = _normalize_partial_review_panels_to_patch(payload, draft)
    payload = _expand_review_patch(payload, draft)
    payload = _normalize_panel_character_names(payload)
    payload = _normalize_story_bible_lists(payload)
    payload = _inherit_missing_review_project_fields(payload, draft)
    payload = _inherit_review_character_fields(payload, draft)
    payload = _inherit_review_story_bible_fields(payload, draft)
    payload = _inherit_review_panel_fields(payload, draft)
    payload = _normalize_review_text_items(payload, draft)
    payload = _normalize_review_panel_positions(payload, draft)
    payload = _normalize_panel_layout_fields(payload)
    payload = _normalize_panel_display_language(payload, draft.content_language)
    if not isinstance(payload.get("title"), str) or not payload["title"].strip():
        payload["title"] = draft.title
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
        project = ComicProject.model_validate(payload)
        _validate_user_facing_storyboard(project)
        _validate_dialogue_diversity(project)
        return project
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
