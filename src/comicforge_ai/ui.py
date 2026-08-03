"""Gradio user interface for provider-based comic generation."""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr
from PIL import Image

from comicforge_ai.layout import (
    CUSTOM_FRAME_LABELS,
    compose_comic,
    custom_panel_render_size,
    validate_custom_layout,
)
from comicforge_ai.models import (
    ImageModelStatus,
    ImageProviderRegistry,
    TextModelRegistry,
    TextModelStatus,
    build_default_image_registry,
    build_default_registry,
)
from comicforge_ai.models.base import TextModelError, TextModelOutputError
from comicforge_ai.models.image_base import ImageModelError
from comicforge_ai.schemas import (
    ComicProject,
    ContentLanguage,
    CustomPanelFrame,
    LayoutMode,
    LetteringStyle,
)
from comicforge_ai.service import (
    ComicGenerationResult,
    ComicGenerator,
    ImageGenerationOptions,
    ScriptGenerationResult,
    normalize_optional_seed,
)

_CUSTOM_FRAME_CHOICES = [
    (CUSTOM_FRAME_LABELS["square"], "square"),
    (CUSTOM_FRAME_LABELS["portrait"], "portrait"),
    (CUSTOM_FRAME_LABELS["landscape"], "landscape"),
    (CUSTOM_FRAME_LABELS["wide"], "wide"),
]

_LAYOUT_CHOICES = [
    ("传统漫画页（每页最多 6 格，自动分页）", "adaptive_page"),
    ("纵向滚动条漫", "webtoon"),
    ("规则等幅网格（连续排列）", "grid"),
    ("自定义画框布局", "custom_page"),
]
_AUTO_LAYOUT_CHOICES = [item for item in _LAYOUT_CHOICES if item[1] != "custom_page"]


def workflow_mode_updates(
    generation_mode: str,
    layout_mode: LayoutMode,
) -> tuple[object, object, object, object, str]:
    """Connect the workflow choice to visible actions and valid layouts."""
    if generation_mode == "auto":
        effective_layout = (
            "adaptive_page" if layout_mode == "custom_page" else layout_mode
        )
        return (
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(choices=_AUTO_LAYOUT_CHOICES, value=effective_layout),
            gr.update(visible=False),
            (
                '<div class="cf-flow-note"><strong>一键生成</strong> · '
                "自动完成分镜、图片与排版</div>"
            ),
        )
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(choices=_LAYOUT_CHOICES, value=layout_mode),
        gr.update(visible=layout_mode == "custom_page"),
        (
            '<div class="cf-flow-note"><strong>先看分镜</strong> · '
            "确认内容后再生成图片</div>"
        ),
    )


def layout_mode_updates(
    layout_mode: LayoutMode,
    generation_mode: str,
    panel_count: int = 4,
) -> tuple[object, str]:
    """Only expose the custom designer when it will affect generation."""
    custom_active = generation_mode == "manual" and layout_mode == "custom_page"
    count = max(1, int(panel_count))
    descriptions = {
        "adaptive_page": f"{count} 格 · 每页最多 6 格",
        "webtoon": f"{count} 格 · 纵向连续阅读",
        "grid": f"{count} 格 · 规则等幅排列",
        "custom_page": f"{count} 格 · 需要 {count} 个画框",
    }
    return gr.update(visible=custom_active), descriptions[layout_mode]

_APP_THEME = gr.themes.Soft(
    primary_hue="violet",
    secondary_hue="cyan",
    neutral_hue="slate",
    radius_size="lg",
    text_size="md",
)

_APP_CSS = """
.gradio-container {
  background: #f5f7fb;
  min-height: 100vh;
}
.cf-topbar {
  border: 1px solid #e5e9f2 !important;
  border-radius: 16px !important;
  padding: 12px 18px !important;
  margin-bottom: 12px !important;
  background: #ffffff !important;
  box-shadow: 0 8px 24px rgba(35, 42, 68, 0.06);
}
.cf-topbar h1 { margin: 0 !important; letter-spacing: -.035em; font-size: 25px !important; }
.cf-topbar p { margin: 2px 0 0 !important; color: #6d6a83; font-size: 12px; }
.cf-hero {
  border: 1px solid rgba(121, 104, 255, 0.24);
  border-radius: 28px;
  padding: 15px 22px !important;
  margin-bottom: 10px;
  background: linear-gradient(120deg, rgba(255,255,255,.88), rgba(232,247,255,.72));
  box-shadow: 0 18px 50px rgba(73, 61, 150, 0.12);
  backdrop-filter: blur(18px);
}
.cf-hero h1 { letter-spacing: -0.035em; margin-bottom: 4px !important; }
.cf-hero h3, .cf-hero p { margin-top: 3px !important; margin-bottom: 3px !important; }
.cf-sidebar-shell {
  background: #f8f9fc;
  border-right: 1px solid #e2e6ef !important;
  box-shadow: 10px 0 28px rgba(35, 42, 68, .06);
}
.cf-sidebar-shell ::-webkit-scrollbar { width: 8px; }
.cf-sidebar-shell ::-webkit-scrollbar-thumb {
  border-radius: 99px;
  background: linear-gradient(#8b6eff, #43c8e7);
}
.cf-step-map {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin: 2px 0 10px;
  padding: 10px;
  border: 1px solid rgba(113, 98, 230, .16);
  border-radius: 18px;
  background: rgba(255,255,255,.7);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.9), 0 8px 20px rgba(67,64,130,.08);
}
.cf-step-map span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #4d4b69;
  font-size: 12px;
  white-space: nowrap;
}
.cf-step-map b {
  display: grid;
  place-items: center;
  width: 25px;
  height: 25px;
  color: white;
  border-radius: 9px;
  background: linear-gradient(145deg, #765aff, #3fc9e7);
  box-shadow: 0 5px 12px rgba(105, 83, 235, .24), inset 0 1px 1px rgba(255,255,255,.55);
}
.cf-step-map i { color: #a39ebd; font-style: normal; }
.cf-step-section {
  margin-bottom: 9px !important;
  border: 1px solid rgba(111, 95, 220, .16) !important;
  border-radius: 18px !important;
  background: #ffffff !important;
  box-shadow: 0 4px 14px rgba(35, 42, 68, .05);
  overflow: hidden;
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.cf-step-section:hover {
  border-color: rgba(111, 85, 239, .34) !important;
  box-shadow: 0 12px 30px rgba(91, 76, 176, .11), inset 0 1px 0 rgba(255,255,255,.95);
}
.cf-mini-status {
  max-height: 150px;
  overflow: auto;
  border-radius: 14px;
  padding: 9px 11px !important;
  background: linear-gradient(120deg, rgba(236,232,255,.75), rgba(230,249,255,.74));
  font-size: 13px;
}
.cf-main-column {
  padding: 12px 18px;
  background: transparent;
}
.cf-flow-hub {
  --block-background-fill: #ffffff;
  --background-fill-secondary: #ffffff;
  border: 1px solid #e4e8f1 !important;
  border-radius: 18px !important;
  padding: 16px !important;
  margin-bottom: 12px;
  background: #ffffff !important;
  box-shadow: 0 8px 24px rgba(35, 42, 68, .06);
}
.cf-flow-hub h3 { margin: 0 0 4px !important; }
.cf-flow-heading h2 {
  margin: 0 0 8px;
  color: #1d2940;
  font-size: 18px;
}
.cf-workflow-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 5px 0 10px;
  color: #57546f;
  font-size: 13px;
  font-weight: 700;
}
.cf-workflow-line span {
  flex: 1;
  padding: 7px 10px;
  border-radius: 11px;
  text-align: center;
  background: #f7f8fc;
  border: 1px solid #e8eaf1;
}
.cf-workflow-line i { color: #938daa; font-style: normal; }
.cf-flow-note {
  margin: 10px 0 8px;
  color: #596176;
  font-size: 13px;
}
.cf-flow-note strong { color: #27324a; }
#cf-flow-heading,
#cf-flow-heading > div,
#cf-flow-heading .html-container,
#cf-flow-note,
#cf-flow-note > div,
#cf-flow-note .html-container {
  border: 0 !important;
  background: #ffffff !important;
  box-shadow: none !important;
}
.cf-first-run {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 8px 0 12px;
}
.cf-first-run > div {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 11px;
  border: 1px solid rgba(109, 93, 220, .14);
  border-radius: 14px;
  color: #4c4b68;
  background: rgba(255,255,255,.72);
  font-size: 12px;
  line-height: 1.35;
}
.cf-first-run b {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 25px;
  height: 25px;
  border-radius: 9px;
  color: white;
  background: linear-gradient(145deg, #765aff, #39c9e7);
  box-shadow: 0 5px 12px rgba(98, 82, 223, .2);
}
.cf-primary-action button {
  min-height: 54px !important;
  font-size: 17px !important;
  font-weight: 750 !important;
}
.cf-workspace-tabs {
  margin-top: 10px;
  border: 1px solid rgba(107, 99, 185, .18) !important;
  border-radius: 20px !important;
  padding: 8px !important;
  background: rgba(255,255,255,.72);
}
.cf-workspace-tabs .tab-nav button {
  font-weight: 700 !important;
}
.cf-revision-card, .cf-language-card {
  --block-background-fill: #ffffff;
  --background-fill-secondary: #ffffff;
  border: 1px solid rgba(115, 96, 221, .15) !important;
  border-radius: 16px !important;
  padding: 12px !important;
  background: #ffffff !important;
}
.cf-revision-card .form,
.cf-revision-card .block,
.cf-revision-card .wrap,
.cf-revision-card .prose,
.cf-language-card .form,
.cf-language-card .block,
.cf-language-card .wrap,
.cf-language-card .prose,
#cf-revision-heading,
#cf-revision-heading > div {
  background: #ffffff !important;
}
.cf-status {
  border-left: 4px solid #7867f8;
  border-radius: 16px;
  padding: 10px 14px !important;
  background: rgba(255,255,255,.76);
  margin-bottom: 10px !important;
  max-height: 170px;
  overflow: auto;
}
.gradio-container button.primary {
  border: 0 !important;
  background: linear-gradient(110deg, #6d5dfc, #8d6ff7 56%, #36cce7) !important;
  box-shadow: 0 10px 24px rgba(109, 93, 252, .25);
}
.gradio-container button { transition: transform .16s ease, box-shadow .16s ease; }
.gradio-container button:hover { transform: translateY(-1px); }
.gradio-container .form, .gradio-container .block {
  border-color: rgba(111, 119, 165, .18);
}
.cf-frame-table { cursor: pointer; }
.cf-download-row button {
  min-height: 46px !important;
  border-radius: 15px !important;
}
.cf-compact-upload .file-preview {
  min-height: 84px !important;
  max-height: 130px !important;
}
.cf-canvas-shell {
  --block-background-fill: #ffffff;
  --background-fill-secondary: #ffffff;
  border: 1px solid #e3e7ef !important;
  border-radius: 18px !important;
  padding: 12px !important;
  background: #ffffff !important;
  box-shadow: 0 8px 24px rgba(35,42,68,.06);
}
.cf-canvas-shell .form,
.cf-canvas-shell .block,
.cf-canvas-shell .wrap,
.cf-canvas-shell .html-container,
.cf-canvas-shell .prose {
  background-color: #ffffff !important;
}
/*
 * Gradio wraps Group, Radio, Image and Markdown in additional generated divs.
 * Their class names change between Gradio releases, so styling only .form or
 * .wrap leaves strips of the secondary (grey) theme background visible.  Keep
 * every non-interactive canvas wrapper on the same white surface; controls
 * retain their own button/input backgrounds through their element styles.
 */
.cf-canvas-shell > div,
.cf-canvas-shell > div > div,
.cf-canvas-shell > .gap,
.cf-canvas-shell div:has(#cf-preview-mode),
.cf-canvas-shell div:has(#comic-preview),
.cf-canvas-shell div:has(#cf-preview-help) {
  --block-background-fill: #ffffff;
  --background-fill-primary: #ffffff;
  --background-fill-secondary: #ffffff;
  background: #ffffff !important;
}
.cf-canvas-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 2px 10px;
  margin-bottom: 10px;
  border-bottom: 1px solid #e8eaf0;
}
.cf-canvas-heading strong { color: #27324a; font-size: 17px; }
.cf-canvas-heading span { color: #7a8194; font-size: 12px; }
#cf-canvas-heading,
#cf-canvas-heading > div,
#cf-canvas-heading .html-container {
  border: 0 !important;
  background: #ffffff !important;
  box-shadow: none !important;
}
#cf-preview-mode,
#cf-preview-mode > div,
#cf-preview-mode .wrap,
#cf-preview-mode fieldset,
#cf-preview-help,
#cf-preview-help > div,
#cf-preview-help .prose {
  background: #ffffff !important;
  box-shadow: none !important;
}
.cf-preview-mode { max-width: 380px; }
.cf-preview-mode .wrap { gap: 5px !important; }
.cf-preview-help {
  margin: 6px 8px 0 !important;
  color: #77748d;
  font-size: 12px;
  text-align: center;
}
#comic-preview {
  height: min(68vh, 820px);
  min-height: 500px;
  max-height: 820px;
  overflow: hidden !important;
  border-radius: 18px;
  background: #ffffff !important;
}
#comic-preview .image-container,
#comic-preview .wrap,
#comic-preview [data-testid="image"],
#comic-preview > div,
#comic-preview > div > div {
  height: 100% !important;
  max-height: 100% !important;
  background: #ffffff !important;
}
#comic-preview img {
  width: 100% !important;
  height: 100% !important;
  max-height: 100% !important;
  object-fit: contain !important;
  object-position: top center !important;
}
#comic-preview.cf-preview-width .image-container,
#comic-preview.cf-preview-width .wrap,
#comic-preview.cf-preview-width [data-testid="image"] {
  overflow-y: auto !important;
  align-items: flex-start !important;
}
#comic-preview.cf-preview-width img {
  width: 100% !important;
  height: auto !important;
  max-height: none !important;
  object-fit: contain !important;
}
#comic-preview.cf-preview-fit .image-container,
#comic-preview.cf-preview-fit .wrap {
  overflow: hidden !important;
}
@media (max-width: 900px) {
  .cf-sidebar-shell { width: min(92vw, 480px) !important; }
  .cf-step-map span { font-size: 0; }
  .cf-step-map b { font-size: 11px; }
  .cf-main-column { padding: 8px; border-radius: 18px; }
  .cf-first-run { grid-template-columns: 1fr; }
  .cf-canvas-toolbar { position: static; }
  .cf-preview-mode { max-width: none; }
  #comic-preview { height: 62vh; min-height: 390px; }
}
"""


def _custom_frames_from_state(
    state: list[dict[str, object]] | None,
) -> list[CustomPanelFrame]:
    return [CustomPanelFrame.model_validate(item) for item in (state or [])]


def _custom_layout_rows(frames: list[CustomPanelFrame]) -> list[list[object]]:
    return [
        [frame.sequence, CUSTOM_FRAME_LABELS[frame.frame_type]]
        for frame in frames
    ]


def _custom_layout_preview(frames: list[CustomPanelFrame]) -> Image.Image | None:
    if not frames:
        return None
    try:
        validate_custom_layout(frames, len(frames))
    except ValueError:
        return None
    colors = ("#F6C85F", "#6FADD7", "#9ED9A8", "#C7B4E8", "#EF9A9A", "#CDB58A")
    panels = [
        Image.new("RGB", custom_panel_render_size(frame), colors[index % len(colors)])
        for index, frame in enumerate(frames)
    ]
    return compose_comic(
        panels,
        "自定义画框预览",
        layout_mode="custom_page",
        custom_layout=frames,
    )


def _default_custom_frames(panel_count: int) -> list[CustomPanelFrame]:
    """Build a valid starter layout without changing the requested story length."""
    count = max(1, int(panel_count))
    frame_types = (
        ["square"] * count
        if count % 2 == 0
        else ["wide", *(["square"] * (count - 1))]
    )
    return [
        CustomPanelFrame(sequence=index, frame_type=frame_type)
        for index, frame_type in enumerate(frame_types, start=1)
    ]


def _custom_layout_result(
    frames: list[CustomPanelFrame],
    panel_count: int,
    *,
    selected_index: int | None = None,
    message: str = "",
) -> tuple[
    list[dict[str, object]],
    list[list[object]],
    Image.Image | None,
    str,
    int | None,
]:
    frames = [
        frame.model_copy(update={"sequence": index})
        for index, frame in enumerate(frames, start=1)
    ]
    payload = [frame.model_dump(mode="json") for frame in frames]
    if not message:
        try:
            validate_custom_layout(frames, panel_count)
            message = f"✅ 已安排 {len(frames)}/{panel_count} 个画框，布局完整。"
        except ValueError as exc:
            message = f"⚠️ 已安排 {len(frames)}/{panel_count} 个画框：{exc}"
    return (
        payload,
        _custom_layout_rows(frames),
        _custom_layout_preview(frames),
        message,
        selected_index,
    )


def sync_custom_layout_for_ui(
    layout_mode: LayoutMode,
    panel_count: int,
    state: list[dict[str, object]] | None,
) -> tuple[
    list[dict[str, object]],
    list[list[object]],
    Image.Image | None,
    str,
    None,
]:
    """Keep custom frames synchronized with the requested storyboard count."""
    count = max(1, int(panel_count))
    frames = _custom_frames_from_state(state)
    if layout_mode != "custom_page":
        return _custom_layout_result(
            frames,
            count,
            message=(
                f"当前使用自动页面布局；已保存 {len(frames)} 个自定义画框，"
                "切回自定义布局前不会参与生成。"
            ),
        )
    if len(frames) != count:
        previous_count = len(frames)
        frames = _default_custom_frames(count)
        return _custom_layout_result(
            frames,
            count,
            message=(
                f"✅ 分镜数量为 {count}；已将原来的 {previous_count} 个画框"
                f"重新初始化为 {count} 个，可继续调整类型。"
            ),
        )
    return _custom_layout_result(frames, count)


def edit_custom_layout_for_ui(
    action: str,
    frame_type: str,
    state: list[dict[str, object]] | None,
    selected_index: int | None = None,
    target_panel_count: int | None = None,
) -> tuple[
    list[dict[str, object]],
    list[list[object]],
    Image.Image | None,
    str,
    int | None,
]:
    """Edit frame types while keeping storyboard length as the source of truth."""
    frames = _custom_frames_from_state(state)
    panel_count = max(1, int(target_panel_count or len(frames) or 4))
    new_frame = CustomPanelFrame(sequence=len(frames) + 1, frame_type=frame_type)
    if action == "insert":
        if len(frames) >= panel_count:
            return _custom_layout_result(
                frames,
                panel_count,
                selected_index=selected_index,
                message=(
                    f"⚠️ 当前分镜数量是 {panel_count}，不能添加第 {panel_count + 1} 个画框。"
                    "如需更多画框，请先修改“分镜数量”。"
                ),
            )
        insert_at = (
            len(frames)
            if selected_index is None
            else max(0, min(int(selected_index) + 1, len(frames)))
        )
        frames.insert(insert_at, new_frame)
        selected_index = insert_at
    elif action == "delete":
        if selected_index is None or not (0 <= int(selected_index) < len(frames)):
            return _custom_layout_result(
                frames,
                panel_count,
                message="⚠️ 请先点击表格中的一个画框，再删除。",
            )
        frames.pop(int(selected_index))
        selected_index = min(int(selected_index), len(frames) - 1) if frames else None
    elif action == "replace":
        if selected_index is None or not (0 <= int(selected_index) < len(frames)):
            return _custom_layout_result(
                frames,
                panel_count,
                message="⚠️ 请先点击一个画框，再更改它的类型。",
            )
        frames[int(selected_index)] = CustomPanelFrame(
            sequence=int(selected_index) + 1,
            frame_type=frame_type,
        )
    elif action == "reset":
        frames = _default_custom_frames(panel_count)
        selected_index = None
    return _custom_layout_result(
        frames,
        panel_count,
        selected_index=selected_index,
    )


def select_custom_frame_for_ui(event: gr.SelectData) -> tuple[int, str]:
    """Remember the clicked dataframe row for insert/delete operations."""
    index = (
        event.index[0]
        if isinstance(event.index, (tuple, list))
        else event.index
    )
    row_index = int(index)
    return row_index, f"已选中第 {row_index + 1} 个画框，可在其后插入或直接删除。"


def _project_markdown(project: ComicProject) -> str:
    characters = "\n".join(
        f"- **{character.name}**：{character.appearance}；{character.personality}"
        for character in project.characters
    )
    panels = "\n".join(
        (
            f"{panel.sequence}. **{panel.scene}**  \n"
            f"   - 画面：{panel.visual_description or '（无）'}  \n"
            f"   - 角色：{'、'.join(panel.characters) or '（无）'}  \n"
            f"   - 动作：{panel.action or '（无）'}  \n"
            f"   - 对白：{panel.dialogue or '（无）'}  \n"
            f"   - 旁白：{panel.narration or '（无）'}  \n"
            f"   - 绘图提示词：{panel.image_prompt or '（无）'}"
        )
        for panel in project.panels
    )
    guidance = (
        f"\n\n**用户故事依据：** {project.user_story_guidance}"
        if project.user_story_guidance
        else ""
    )
    candidates = "、".join(project.title_candidates) or "（模型未提供）"
    custom_layout_note = (
        f"；自定义画框：`{len(project.custom_layout)}` 个"
        if project.layout_mode == "custom_page"
        else ""
    )
    revision_history = "\n".join(
        f"- 第 {item.round} 轮：{item.instruction}"
        for item in project.revision_history
    )
    return (
        f"### {project.title}\n\n"
        f"**候选标题：** {candidates}\n\n"
        f"**页面版式：** `{project.layout_mode}`；"
        f"单格多镜头：`{project.allow_multi_shot_panels}`"
        f"{custom_layout_note}\n\n"
        f"**故事梗概：** {project.story}{guidance}\n\n"
        f"#### 连续修订记录\n{revision_history or '尚无人工追加修订。'}\n\n"
        f"#### 角色\n{characters}\n\n"
        f"#### 分镜\n{panels}"
    )


def _model_status_markdown(status: TextModelStatus) -> str:
    if status.available:
        state = "✅ 可用"
    elif not status.configured:
        state = "⚠️ 未配置"
    else:
        state = "❌ 不可用"
    return (
        f"**模型状态：{state}**  \n"
        f"Provider：`{status.display_name}`  \n"
        f"模型：`{status.model_name}`  \n"
        f"运行方式：`{status.provider_type}`  \n"
        f"说明：{status.message}"
    )


def _image_model_status_markdown(status: ImageModelStatus) -> str:
    if status.available:
        state = "✅ 已配置"
    elif not status.configured:
        state = "⚠️ 未配置"
    else:
        state = "❌ 不可用"
    missing = (
        f"  \n缺少配置：`{'`、`'.join(status.missing_settings)}`"
        if status.missing_settings
        else ""
    )
    timeouts = ""
    if status.connect_timeout or status.generation_timeout:
        timeouts = (
            f"  \n连接超时：`{status.connect_timeout:g} 秒`"
            f"  \n生成超时：`{status.generation_timeout:g} 秒`"
        )
    return (
        f"**图片模型状态：{state}**  \n"
        f"Provider：`{status.display_name}`  \n"
        f"模型：`{status.model_name}`  \n"
        f"运行方式：`{status.provider_type}`  \n"
        f"说明：{status.message}{missing}{timeouts}"
    )


def _capabilities_markdown(registry: ImageProviderRegistry, provider_id: str) -> str:
    capabilities = registry.capabilities(provider_id)
    labels = {
        "text_to_image": "文生图",
        "image_to_image": "参考图创作",
        "multi_reference": "多张参考图",
        "mask_edit": "指定区域修改",
        "inpainting": "局部重绘",
        "outpainting": "扩图",
        "negative_prompt": "排除不想出现的内容",
        "seed": "固定随机结果",
        "batch": "批量生成",
        "async_task": "排队生成",
        "cancellation": "取消任务",
        "arbitrary_size": "任意尺寸",
        "transparent_background": "透明背景",
        "quality": "质量等级",
        "strength": "编辑强度",
    }
    supported = [labels[name] for name in capabilities.enabled()]
    return "**该图片服务支持：** " + "、".join(supported)


def _generation_status_markdown(result: ComicGenerationResult) -> str:
    provenance = (
        f"实际 Provider：`{result.actual_provider_name}`  \n"
        f"实际模型：`{result.actual_model_name}`"
    )
    if result.fallback_used:
        text_status = (
            "### ⚠️ 已回退到 MockTextModel\n\n"
            f"请求的 Provider `{result.requested_provider_id}` 调用失败。  \n"
            f"失败请求耗时：`{result.requested_provider_seconds:.2f} 秒`  \n"
            f"失败原因：{result.fallback_reason}  \n"
            f"{provenance}  \n"
            f"Mock 回退耗时：`{result.actual_provider_seconds:.2f} 秒`"
        )
    else:
        thinking = (
            f"  \nThinking 控制：`{result.thinking_control}`"
            if result.thinking_control
            else ""
        )
        text_status = (
            f"### ✅ 文本方案生成成功\n\n{provenance}  \n"
            f"文本生成耗时：`{result.requested_provider_seconds:.2f} 秒`"
            f"{thinking}  \n未发生文本 Mock 回退。"
        )

    panel_times = result.panel_image_seconds or {}
    timing_lines = "、".join(
        f"第 {sequence} 格 {seconds:.2f}s"
        for sequence, seconds in sorted(panel_times.items())
    )
    image_providers = "、".join(result.actual_image_provider_names) or "未知"
    image_models = "、".join(result.actual_image_model_names) or "未知"
    if result.image_fallback_used:
        panels = "、".join(str(item) for item in result.image_fallback_panels)
        image_heading = f"### ⚠️ 图片生成完成，第 {panels} 格回退 Mock"
        errors = result.image_error_summaries or {}
        error_lines = "  \n".join(
            f"第 {sequence} 格：{message}"
            for sequence, message in sorted(errors.items())
        )
        error_text = " ".join(errors.values())
        if "AuthenticationError" in error_text or "鉴权" in error_text:
            advice = "检查对应 Provider 的环境变量 Key，然后重启应用。"
        elif "InsufficientBalanceError" in error_text or "余额" in error_text:
            advice = "检查账户余额、配额和模型权限。"
        elif "RateLimitError" in error_text or "429" in error_text:
            advice = "降低并发分格数，稍后重试或检查平台限流。"
        elif "UnsupportedCapabilityError" in error_text:
            advice = "关闭该 Provider 不支持的高级参数，或改选具备相应能力的 Provider。"
        elif "Timeout" in error_text or "超时" in error_text:
            advice = "提高生成/轮询超时，降低并发，并检查服务负载。"
        elif "Configuration" in error_text or "未配置" in error_text:
            advice = "在本地 .env 配置该 Provider 的 Key 和模型后重启。"
        else:
            advice = "查看错误类型，检查模型名、服务地址和网络状态后重试。"
    else:
        image_heading = "### ✅ 图片生成完成，未发生 Mock 回退"
        error_lines = "无"
        advice = "无须处理。"
    image_status = (
        f"{image_heading}\n\n"
        f"请求图片 Provider：`{result.requested_image_provider_id}`  \n"
        f"实际图片 Provider：`{image_providers}`  \n"
        f"实际图片模型：`{image_models}`  \n"
        f"逐格耗时：{timing_lines or '无'}  \n"
        f"图片总耗时：`{result.total_image_seconds:.2f} 秒`  \n"
        f"回退/错误摘要：{error_lines}  \n"
        f"可执行建议：{advice}  \n"
        f"最终漫画：`{result.project.output_path}`  \n"
        f"项目记录：`{result.project_json_path}`"
    )
    request_ids = "、".join(
        f"第 {item.sequence} 格 `{item.request_id}`"
        for item in result.project.panel_images
        if item.request_id
    )
    seeds = "、".join(
        f"第 {item.sequence} 格 `{item.seed}`"
        for item in result.project.panel_images
        if item.seed is not None
    )
    generated_sizes = "、".join(
        f"第 {item.sequence} 格 `"
        f"{item.actual_parameters.get('aspect_ratio') or _record_dimensions(item.actual_parameters)}`"
        for item in result.project.panel_images
    )
    image_status += (
        f"  \n请求 ID：{request_ids or '无'}"
        f"  \n各分格 Seed：{seeds or '未指定/Provider 未返回'}"
        f"  \n实际请求画幅：{generated_sizes or 'Provider 未返回'}"
    )
    return text_status + "\n\n" + image_status


def _record_dimensions(parameters: dict[str, object]) -> str:
    width = parameters.get("width")
    height = parameters.get("height")
    if width and height:
        return f"{width}x{height}"
    return "Provider 默认尺寸"


def _script_status_markdown(result: ScriptGenerationResult) -> str:
    fallback = (
        f"  \n⚠️ 已回退 Mock：{result.fallback_reason}"
        if result.fallback_used
        else "  \n未发生文本 Mock 回退。"
    )
    notes = "  \n".join(f"- {note}" for note in result.project.review_notes)
    return (
        "### ✅ 剧本初稿、审查与修订已完成\n\n"
        f"实际 Provider：`{result.actual_provider_name}`  \n"
        f"实际模型：`{result.actual_model_name}`  \n"
        f"内容语言：`{result.project.content_language}`  \n"
        f"耗时：`{result.actual_provider_seconds:.2f} 秒`{fallback}  \n"
        "**分镜已经生成，尚未开始生成图片。**\n\n"
        f"审查记录：  \n{notes or '- 已完成结构审查。'}"
    )


def _storyboard_rows(project: ComicProject) -> list[list[object]]:
    return [
        [
            panel.sequence,
            panel.visual_description,
            panel.dialogue,
            panel.narration,
        ]
        for panel in project.panels
    ]


def generate_script_for_ui(
    theme: str,
    source_story: str,
    style: str,
    panel_count: int,
    provider_id: str,
    language: ContentLanguage,
    layout_mode: LayoutMode,
    allow_multi_shot_panels: bool,
    custom_layout_state: list[dict[str, object]] | None = None,
    generator: ComicGenerator | None = None,
) -> tuple[dict[str, object], str, list[list[object]], str, str]:
    """Generate and review an editable script without invoking images."""
    service = generator or ComicGenerator()
    try:
        custom_frames = _custom_frames_from_state(custom_layout_state)
        if layout_mode == "custom_page":
            validate_custom_layout(custom_frames, int(panel_count))
        provider_layout: LayoutMode = (
            "adaptive_page" if layout_mode == "custom_page" else layout_mode
        )
        result = service.generate_script_with_status(
            theme,
            style,
            int(panel_count),
            provider_id,
            language,
            provider_layout,
            allow_multi_shot_panels,
            source_story,
        )
        result.project.layout_mode = layout_mode
        result.project.custom_layout = custom_frames if layout_mode == "custom_page" else []
    except TextModelOutputError as exc:
        raise gr.Error(
            "模型服务已经返回内容，但结果结构不完整（不是连接或生成超时）。"
            f"系统自动修复后仍未通过校验：{exc}"
        ) from exc
    except (ValueError, TextModelError) as exc:
        raise gr.Error(str(exc)) from exc
    return (
        result.project.model_dump(mode="json"),
        _project_markdown(result.project),
        _storyboard_rows(result.project),
        result.project.title,
        _script_status_markdown(result),
    )


def redesign_script_for_ui(
    project_state: dict[str, object] | None,
    storyboard_rows: list[list[object]],
    user_guidance: str,
    provider_id: str,
    generator: ComicGenerator | None = None,
) -> tuple[dict[str, object], str, list[list[object]], str, str]:
    """Rebuild a complete storyboard from natural-language user guidance."""
    if not project_state:
        raise gr.Error("请先生成或载入一个分镜方案，再提交故事补充说明。")
    if not (user_guidance or "").strip():
        raise gr.Error("请先说明正确的故事事实、人物关系或必须保留的情节。")

    service = generator or ComicGenerator()
    try:
        project = ComicProject.model_validate(project_state)
        project = service.apply_storyboard_edits(project, storyboard_rows)
        result = service.redesign_script_with_guidance(
            project,
            user_guidance,
            provider_id,
        )
    except (ValueError, TextModelError) as exc:
        raise gr.Error(str(exc)) from exc

    status = _script_status_markdown(result).replace(
        "剧本初稿、审查与修订已完成",
        "已根据你的故事说明重做并审查完整分镜",
        1,
    )
    return (
        result.project.model_dump(mode="json"),
        _project_markdown(result.project),
        _storyboard_rows(result.project),
        result.project.title,
        status,
    )


def render_confirmed_for_ui(
    project_state: dict[str, object] | None,
    storyboard_rows: list[list[object]],
    final_title: str,
    layout_mode: LayoutMode,
    allow_multi_shot_panels: bool,
    custom_layout_state: list[dict[str, object]] | None,
    image_provider_id: str,
    image_model: str,
    negative_prompt: str,
    width: float | None,
    height: float | None,
    aspect_ratio: str,
    quality: str,
    seed: float | None,
    output_format: str,
    reference_images: list[str] | None,
    mask_image: str | None,
    strict_mode: bool,
    secondary_provider_id: str,
    concurrency: float,
    bubble_theme: str,
    lettering_style: LetteringStyle,
    show_narration: bool,
    show_panel_numbers: bool,
    auto_shorten_dialogue: bool,
    generator: ComicGenerator | None = None,
) -> tuple[dict[str, object], object, str, str, str, str, str]:
    """Apply user edits and only then spend image Provider credits."""
    if not project_state:
        raise gr.Error("请先点击“生成并审查分镜”，确认剧本后再生成图片。")
    service = generator or ComicGenerator()
    try:
        project = ComicProject.model_validate(project_state)
        project = service.apply_storyboard_edits(project, storyboard_rows)
        if not final_title.strip():
            raise ValueError("最终漫画标题不能为空")
        project.title = final_title.strip()
        project.layout_mode = layout_mode
        custom_frames = _custom_frames_from_state(custom_layout_state)
        if layout_mode == "custom_page":
            validate_custom_layout(custom_frames, project.panel_count)
            project.custom_layout = custom_frames
        else:
            project.custom_layout = []
        project.allow_multi_shot_panels = allow_multi_shot_panels
        project.bubble_theme = bubble_theme
        project.lettering_style = lettering_style
        project.show_panel_numbers = show_panel_numbers
        result = service.render_confirmed_project(
            project,
            image_provider_id,
            ImageGenerationOptions(
                model=image_model,
                negative_prompt=(negative_prompt or "").strip(),
                width=int(width) if width else None,
                height=int(height) if height else None,
                aspect_ratio=(aspect_ratio or "").strip(),
                quality=quality or "auto",
                seed=normalize_optional_seed(seed),
                output_format=output_format or "png",
                reference_images=tuple(Path(item) for item in (reference_images or [])),
                mask_image=Path(mask_image) if mask_image else None,
                strict_mode=bool(strict_mode),
                fallback_chain=(secondary_provider_id,) if secondary_provider_id else (),
                concurrency=max(1, int(concurrency)),
                bubble_theme=bubble_theme,
                lettering_style=lettering_style,
                show_narration=show_narration,
                show_panel_numbers=show_panel_numbers,
                auto_shorten_dialogue=auto_shorten_dialogue,
            ),
        )
    except (ValueError, TextModelError, ImageModelError) as exc:
        raise gr.Error(str(exc)) from exc
    return (
        result.project.model_dump(mode="json"),
        result.comic_page,
        _project_markdown(result.project),
        str(result.project.output_path),
        str(result.comic_pdf_path),
        str(result.project_json_path),
        _generation_status_markdown(result),
    )


def relocalize_for_ui(
    project_state: dict[str, object] | None,
    storyboard_rows: list[list[object]],
    final_title: str,
    target_language: ContentLanguage,
    translation_mode: str,
    text_provider_id: str,
    layout_mode: LayoutMode,
    bubble_theme: str,
    lettering_style: LetteringStyle,
    show_narration: bool,
    show_panel_numbers: bool,
    auto_shorten_dialogue: bool,
    generator: ComicGenerator | None = None,
) -> tuple[
    dict[str, object],
    str,
    list[list[object]],
    str,
    str,
    object,
    str,
    str,
    str,
    str,
]:
    """Translate/edit lettering and recompose without invoking image Providers."""
    if not project_state:
        raise gr.Error("请先完成一次漫画图片生成，再切换成品语言。")
    service = generator or ComicGenerator()
    try:
        project = ComicProject.model_validate(project_state)
        result = service.relocalize_rendered_project(
            project,
            storyboard_rows,
            final_title,
            target_language,
            text_provider_id,
            translate_with_model=translation_mode == "model",
            layout_mode=layout_mode,
            image_options=ImageGenerationOptions(
                bubble_theme=bubble_theme,
                lettering_style=lettering_style,
                show_narration=show_narration,
                show_panel_numbers=show_panel_numbers,
                auto_shorten_dialogue=auto_shorten_dialogue,
            ),
        )
    except (ValueError, TextModelError, ImageModelError) as exc:
        raise gr.Error(str(exc)) from exc
    source = (
        "项目内缓存译文"
        if result.used_cached_translation
        else result.translation_provider_name
    )
    status = (
        "### ✅ 已使用现有图片重新排版\n"
        "图片保持不变，没有重新调用图片模型。  \n"
        f"当前漫画语言：`{result.project.content_language}`  \n"
        f"文字来源：`{source}`  \n"
        f"翻译耗时：`{result.translation_seconds:.2f} 秒`  \n"
        "原始分格图片没有重新生成。"
    )
    return (
        result.project.model_dump(mode="json"),
        _project_markdown(result.project),
        _storyboard_rows(result.project),
        result.project.title,
        result.project.content_language,
        result.comic_page,
        str(result.output_path),
        str(result.pdf_path),
        str(result.project_json_path),
        status,
    )


def auto_generate_for_ui(
    generation_mode: str,
    theme: str,
    source_story: str,
    style: str,
    panel_count: int,
    provider_id: str,
    language: ContentLanguage,
    layout_mode: LayoutMode,
    allow_multi_shot_panels: bool,
    image_provider_id: str,
    image_model: str,
    negative_prompt: str,
    width: float | None,
    height: float | None,
    aspect_ratio: str,
    quality: str,
    seed: float | None,
    output_format: str,
    reference_images: list[str] | None,
    mask_image: str | None,
    strict_mode: bool,
    secondary_provider_id: str,
    concurrency: float,
    bubble_theme: str,
    lettering_style: LetteringStyle,
    show_narration: bool,
    show_panel_numbers: bool,
    auto_shorten_dialogue: bool,
    generator: ComicGenerator | None = None,
) -> tuple[
    dict[str, object],
    str,
    list[list[object]],
    str,
    object,
    str,
    str,
    str,
    str,
]:
    """Run the explicit no-human-intervention mode and immediately spend units."""
    if generation_mode != "auto":
        raise gr.Error("请先把“人工是否介入”切换为自动生成模式。")
    effective_layout: LayoutMode = (
        "adaptive_page" if layout_mode == "custom_page" else layout_mode
    )
    service = generator or ComicGenerator()
    try:
        result = service.generate_auto_with_status(
            theme,
            style,
            int(panel_count),
            text_provider_id=provider_id,
            image_provider_id=image_provider_id,
            language=language,
            layout_mode=effective_layout,
            allow_multi_shot_panels=allow_multi_shot_panels,
            source_story=(source_story or "").strip(),
            image_options=ImageGenerationOptions(
                model=image_model,
                negative_prompt=(negative_prompt or "").strip(),
                width=int(width) if width else None,
                height=int(height) if height else None,
                aspect_ratio=(aspect_ratio or "").strip(),
                quality=quality or "auto",
                seed=normalize_optional_seed(seed),
                output_format=output_format or "png",
                reference_images=tuple(Path(item) for item in (reference_images or [])),
                mask_image=Path(mask_image) if mask_image else None,
                strict_mode=bool(strict_mode),
                fallback_chain=(secondary_provider_id,) if secondary_provider_id else (),
                concurrency=max(1, int(concurrency)),
                bubble_theme=bubble_theme,
                lettering_style=lettering_style,
                show_narration=show_narration,
                show_panel_numbers=show_panel_numbers,
                auto_shorten_dialogue=auto_shorten_dialogue,
            ),
        )
    except (ValueError, TextModelError, ImageModelError) as exc:
        raise gr.Error(str(exc)) from exc
    status = _generation_status_markdown(result)
    if layout_mode == "custom_page":
        status += "\n\n自动生成模式未使用自定义画框，已按默认传统漫画页排版。"
    return (
        result.project.model_dump(mode="json"),
        _project_markdown(result.project),
        _storyboard_rows(result.project),
        result.project.title,
        result.comic_page,
        str(result.project.output_path),
        str(result.comic_pdf_path),
        str(result.project_json_path),
        status,
    )


def load_project_for_ui(
    project_path: str | None,
    generator: ComicGenerator | None = None,
) -> tuple[object, ...]:
    """Restore language and editable script state from a saved project JSON."""
    if not project_path:
        raise gr.Error("请选择 project.json 文件。")
    service = generator or ComicGenerator()
    try:
        project = service.load_project(project_path)
    except ImageModelError as exc:
        raise gr.Error(str(exc)) from exc
    custom_frames = project.custom_layout
    custom_payload = [frame.model_dump(mode="json") for frame in custom_frames]
    custom_status = (
        f"✅ 已从项目恢复 {len(custom_frames)} 个自定义画框。"
        if custom_frames
        else "当前项目使用默认自动排版。"
    )
    return (
        project.model_dump(mode="json"),
        _project_markdown(project),
        _storyboard_rows(project),
        project.content_language,
        project.user_story_guidance,
        project.title,
        project.layout_mode,
        project.allow_multi_shot_panels,
        custom_payload,
        _custom_layout_rows(custom_frames),
        _custom_layout_preview(custom_frames),
        project.panel_count,
        custom_status,
        None,
        "### ✅ 项目已重新载入\n可继续编辑分镜，然后确认生成图片。",
    )


def check_model_for_ui(
    provider_id: str,
    generator: ComicGenerator | None = None,
) -> str:
    """Thin UI adapter around the service-level availability check."""
    service = generator or ComicGenerator()
    try:
        return _model_status_markdown(service.check_provider(provider_id))
    except TextModelError as exc:
        return f"**模型状态：❌ 检测失败**  \n{exc}"


def check_image_model_for_ui(
    provider_id: str,
    generator: ComicGenerator | None = None,
) -> str:
    """Thin UI adapter around image-provider configuration checks."""
    service = generator or ComicGenerator()
    try:
        return _image_model_status_markdown(
            service.check_image_provider(provider_id)
        )
    except ImageModelError as exc:
        return f"**图片模型状态：❌ 检测失败**  \n{exc}"


def generate_for_ui(
    theme: str,
    style: str,
    panel_count: int,
    provider_id: str = "mock",
    image_provider_id: str = "mock-image",
    generator: ComicGenerator | None = None,
    *,
    image_model: str = "",
    negative_prompt: str = "",
    width: float | None = None,
    height: float | None = None,
    aspect_ratio: str = "",
    quality: str = "auto",
    seed: float | None = None,
    output_format: str = "png",
    reference_images: list[str] | None = None,
    mask_image: str | None = None,
    strict_mode: bool = False,
    secondary_provider_id: str = "",
    concurrency: float = 1,
) -> tuple[object, str, str, str, str]:
    """Return preview, details, PNG, project JSON, and provenance."""
    service = generator or ComicGenerator()
    try:
        result = service.generate_with_status(
            theme=theme,
            style=style,
            panel_count=int(panel_count),
            provider_id=provider_id,
            image_provider_id=image_provider_id,
            image_options=ImageGenerationOptions(
                model=image_model,
                negative_prompt=(negative_prompt or "").strip(),
                width=int(width) if width else None,
                height=int(height) if height else None,
                aspect_ratio=(aspect_ratio or "").strip(),
                quality=quality or "auto",
                seed=normalize_optional_seed(seed),
                output_format=output_format or "png",
                reference_images=tuple(
                    Path(item) for item in (reference_images or [])
                ),
                mask_image=Path(mask_image) if mask_image else None,
                strict_mode=bool(strict_mode),
                fallback_chain=(secondary_provider_id,)
                if secondary_provider_id
                else (),
                concurrency=max(1, int(concurrency)),
            ),
        )
    except (ValueError, TextModelError, ImageModelError) as exc:
        raise gr.Error(str(exc)) from exc
    return (
        result.comic_page,
        _project_markdown(result.project),
        str(result.project.output_path),
        str(result.project_json_path),
        _generation_status_markdown(result),
    )


def create_demo(
    registry: TextModelRegistry | None = None,
    image_registry: ImageProviderRegistry | None = None,
    generator: ComicGenerator | None = None,
) -> gr.Blocks:
    """Build and return the Chinese Gradio interface."""
    active_registry = registry or build_default_registry()
    active_image_registry = image_registry or build_default_image_registry()
    service = generator or ComicGenerator(
        registry=active_registry,
        image_registry=active_image_registry,
    )

    def handle_status(provider_id: str) -> str:
        return check_model_for_ui(provider_id, service)

    def handle_insert_custom_frame(
        frame_type: str,
        state: list[dict[str, object]] | None,
        selected_index: int | None,
        panel_count: int,
    ) -> tuple[object, ...]:
        return edit_custom_layout_for_ui(
            "insert", frame_type, state, selected_index, panel_count
        )

    def handle_delete_custom_frame(
        frame_type: str,
        state: list[dict[str, object]] | None,
        selected_index: int | None,
        panel_count: int,
    ) -> tuple[object, ...]:
        return edit_custom_layout_for_ui(
            "delete", frame_type, state, selected_index, panel_count
        )

    def handle_replace_custom_frame(
        frame_type: str,
        state: list[dict[str, object]] | None,
        selected_index: int | None,
        panel_count: int,
    ) -> tuple[object, ...]:
        return edit_custom_layout_for_ui(
            "replace", frame_type, state, selected_index, panel_count
        )

    def handle_reset_custom_layout(
        frame_type: str,
        state: list[dict[str, object]] | None,
        selected_index: int | None,
        panel_count: int,
    ) -> tuple[object, ...]:
        return edit_custom_layout_for_ui(
            "reset", frame_type, state, selected_index, panel_count
        )

    def handle_image_status(provider_id: str) -> str:
        return check_image_model_for_ui(provider_id, service)

    def handle_script_generation(
        theme: str,
        source_story: str,
        style: str,
        panel_count: int,
        provider_id: str,
        language: ContentLanguage,
        layout_mode: LayoutMode,
        allow_multi_shot_panels: bool,
        custom_layout_state: list[dict[str, object]] | None,
    ) -> tuple[dict[str, object], str, list[list[object]], str, str]:
        return generate_script_for_ui(
            theme,
            source_story,
            style,
            panel_count,
            provider_id,
            language,
            layout_mode,
            allow_multi_shot_panels,
            custom_layout_state,
            service,
        )

    def handle_story_redesign(
        project_state: dict[str, object] | None,
        storyboard_rows: list[list[object]],
        user_guidance: str,
        provider_id: str,
    ) -> tuple[dict[str, object], str, list[list[object]], str, str]:
        return redesign_script_for_ui(
            project_state,
            storyboard_rows,
            user_guidance,
            provider_id,
            service,
        )

    def handle_confirmed_generation(
        project_state: dict[str, object] | None,
        storyboard_rows: list[list[object]],
        final_title: str,
        layout_mode: LayoutMode,
        allow_multi_shot_panels: bool,
        custom_layout_state: list[dict[str, object]] | None,
        image_provider_id: str,
        image_model: str,
        negative_prompt: str,
        width: float | None,
        height: float | None,
        aspect_ratio: str,
        quality: str,
        seed: float | None,
        output_format: str,
        reference_images: list[str] | None,
        mask_image: str | None,
        strict_mode: bool,
        secondary_provider_id: str,
        concurrency: float,
        bubble_theme: str,
        lettering_style: LetteringStyle,
        show_narration: bool,
        show_panel_numbers: bool,
        auto_shorten_dialogue: bool,
    ) -> tuple[dict[str, object], object, str, str, str, str, str]:
        return render_confirmed_for_ui(
            project_state,
            storyboard_rows,
            final_title,
            layout_mode,
            allow_multi_shot_panels,
            custom_layout_state,
            image_provider_id,
            image_model,
            negative_prompt,
            width,
            height,
            aspect_ratio,
            quality,
            seed,
            output_format,
            reference_images,
            mask_image,
            strict_mode,
            secondary_provider_id,
            concurrency,
            bubble_theme,
            lettering_style,
            show_narration,
            show_panel_numbers,
            auto_shorten_dialogue,
            service,
        )

    def handle_relocalization(
        project_state: dict[str, object] | None,
        storyboard_rows: list[list[object]],
        final_title: str,
        target_language: ContentLanguage,
        translation_mode: str,
        text_provider_id: str,
        layout_mode: LayoutMode,
        bubble_theme: str,
        lettering_style: LetteringStyle,
        show_narration: bool,
        show_panel_numbers: bool,
        auto_shorten_dialogue: bool,
    ) -> tuple[object, ...]:
        return relocalize_for_ui(
            project_state,
            storyboard_rows,
            final_title,
            target_language,
            translation_mode,
            text_provider_id,
            layout_mode,
            bubble_theme,
            lettering_style,
            show_narration,
            show_panel_numbers,
            auto_shorten_dialogue,
            service,
        )

    def handle_image_provider_change(provider_id: str) -> tuple[object, ...]:
        definitions = active_image_registry.model_definitions(provider_id)
        definition = definitions[0]
        capabilities = definition.capabilities
        choices = [(item.display_name, item.model_id) for item in definitions]
        return (
            gr.update(choices=choices, value=definition.model_id),
            _image_model_status_markdown(service.check_image_provider(provider_id)),
            _capabilities_markdown(active_image_registry, provider_id),
            gr.update(
                visible=capabilities.negative_prompt,
                interactive=capabilities.negative_prompt,
                value="" if not capabilities.negative_prompt else None,
            ),
            (
                gr.update(visible=True, interactive=True)
                if capabilities.seed
                else gr.update(visible=False, interactive=False, value=None)
            ),
            gr.update(
                visible=bool(
                    capabilities.image_to_image or capabilities.multi_reference
                ),
                interactive=bool(
                    capabilities.image_to_image or capabilities.multi_reference
                ),
                value=None,
            ),
            gr.update(
                visible=bool(capabilities.mask_edit or capabilities.inpainting),
                interactive=bool(
                    capabilities.mask_edit or capabilities.inpainting
                ),
                value=None,
            ),
            gr.update(
                visible=capabilities.quality,
                interactive=capabilities.quality,
            ),
            gr.update(
                choices=list(definition.supported_formats),
                value=(
                    definition.supported_formats[0]
                    if definition.supported_formats
                    else "png"
                ),
            ),
        )

    def handle_project_load(
        project_path: str | None,
    ) -> tuple[object, ...]:
        return load_project_for_ui(project_path, service)

    def handle_auto_generation(*args: object) -> tuple[object, ...]:
        return auto_generate_for_ui(*args, generator=service)  # type: ignore[arg-type]

    with gr.Blocks(
        title="ComicForge AI · AI 漫画创作工作台",
        theme=_APP_THEME,
        css=_APP_CSS,
        fill_width=True,
    ) as demo:
        script_state = gr.State(value=None)
        custom_layout_state = gr.State(value=[])
        custom_selected_index = gr.State(value=None)
        gr.HTML(
            """
            <header class="cf-topbar">
              <h1>🎨 ComicForge AI</h1>
              <p>剧本 · 分镜 · 漫画</p>
            </header>
            """,
            padding=False,
        )
        with gr.Row():
            with gr.Sidebar(
                label="🚀 创作控制台",
                open=True,
                width=420,
                elem_classes="cf-sidebar-shell",
            ):
                with gr.Accordion(
                    "01 · 内容",
                    open=True,
                    elem_classes="cf-step-section",
                ):
                    theme = gr.Textbox(
                        label="✦ 漫画主题或暂定名称",
                        placeholder="例如：一只猫第一次坐地铁",
                        value="一只猫第一次坐地铁",
                    )
                    source_story = gr.Textbox(
                        label="📖 已有故事或剧本（可选）",
                        placeholder="粘贴已有故事；留空则由 AI 创作",
                        lines=4,
                    )
                    with gr.Row():
                        style = gr.Dropdown(
                            label="🎨 视觉风格",
                            choices=[
                                "清新治愈",
                                "热血日漫",
                                "复古像素",
                                "水彩童话",
                                "科幻霓虹",
                            ],
                            value="清新治愈",
                            allow_custom_value=True,
                        )
                        content_language = gr.Dropdown(
                            label="🌐 漫画内容语言",
                            choices=[
                                ("简体中文", "zh-CN"),
                                ("English", "en"),
                                ("日本語", "ja-JP"),
                            ],
                            value="zh-CN",
                        )
                    panel_count = gr.Number(
                        minimum=1,
                        maximum=20,
                        value=4,
                        step=1,
                        precision=0,
                        label="▦ 分镜数量（1–20）",
                    )
                with gr.Accordion(
                    "02 · 页面",
                    open=False,
                    elem_classes="cf-step-section",
                ):
                    layout_mode = gr.Dropdown(
                        label="▤ 页面形式",
                        choices=_LAYOUT_CHOICES,
                        value="adaptive_page",
                    )
                    layout_mode_note = gr.Markdown(
                        "4 格 · 每页最多 6 格",
                        elem_classes="cf-mini-status",
                    )
                    allow_multi_shot_panels = gr.Checkbox(
                        label="◫ 必要时允许单格包含插入特写/分割镜头",
                        value=True,
                    )
                    with gr.Accordion(
                        "✣ 自定义画框编辑器",
                        open=True,
                        visible=False,
                    ) as custom_layout_designer:
                        gr.Markdown(
                            "选中画框后更改、插入或删除；总数须与分镜一致。"
                        )
                        custom_frame_type = gr.Dropdown(
                            label="画框类型",
                            choices=_CUSTOM_FRAME_CHOICES,
                            value="square",
                        )
                        with gr.Row():
                            replace_custom_frame_button = gr.Button(
                                "↺ 更改选中类型",
                                variant="primary",
                            )
                            insert_custom_frame_button = gr.Button(
                                "＋ 在选中后补入",
                            )
                            delete_custom_frame_button = gr.Button("⌫ 删除选中")
                        reset_custom_layout_button = gr.Button(
                            "恢复适合当前分镜数的默认画框"
                        )
                        custom_layout_table = gr.Dataframe(
                            headers=["序号", "画框类型"],
                            datatype=["number", "str"],
                            value=[],
                            interactive=False,
                            label="当前画框顺序",
                            max_height=260,
                            elem_classes="cf-frame-table",
                        )
                        custom_layout_preview = gr.Image(
                            label="页面线框预览",
                            type="pil",
                            format="png",
                            interactive=False,
                            height=300,
                        )
                        custom_layout_status = gr.Markdown(
                            "选择自定义画框布局后，将按当前分镜数自动初始化。"
                        )

                with gr.Accordion(
                    "03 · 文本模型",
                    open=False,
                    elem_classes="cf-step-section",
                ):
                    provider = gr.Dropdown(
                        label="🧠 文本模型",
                        choices=active_registry.choices(),
                        value="mock",
                    )
                    check_button = gr.Button("↻ 检测文本模型")
                    model_status = gr.Markdown(
                        _model_status_markdown(service.check_provider("mock")),
                        elem_classes="cf-mini-status",
                    )

                with gr.Accordion(
                    "04 · 图片与排字",
                    open=False,
                    elem_classes="cf-step-section",
                ):
                    image_provider = gr.Dropdown(
                        label="◈ 图片模型与服务",
                        choices=active_image_registry.choices(),
                        value="mock-image",
                    )
                    check_image_button = gr.Button("↻ 检测图片模型")
                    image_model_status = gr.Markdown(
                        _image_model_status_markdown(
                            service.check_image_provider("mock-image")
                        ),
                        elem_classes="cf-mini-status",
                    )
                    initial_image_definition = (
                        active_image_registry.model_definitions("mock-image")[0]
                    )
                    with gr.Accordion("⚙ 专业设置（通常无需修改）", open=False):
                        image_model = gr.Dropdown(
                            label="具体图片模型",
                            choices=[
                                (
                                    initial_image_definition.display_name,
                                    initial_image_definition.model_id,
                                )
                            ],
                            value=initial_image_definition.model_id,
                        )
                        image_capabilities = gr.Markdown(
                            _capabilities_markdown(
                                active_image_registry,
                                "mock-image",
                            )
                        )
                        gr.Markdown("画面尺寸会根据你选择的页面与画框自动匹配。")
                        secondary_image_provider = gr.Dropdown(
                            label="失败时备用图片服务",
                            choices=[
                                ("无", ""),
                                *active_image_registry.provider_choices(),
                            ],
                            value="",
                        )
                        image_width = gr.State(value=None)
                        image_height = gr.State(value=None)
                        image_aspect_ratio = gr.State(value="")
                        image_quality = gr.Dropdown(
                            label="生成质量",
                            info="只有当前图片服务支持时才显示。",
                            choices=["auto", "low", "medium", "high", "hd"],
                            value="auto",
                            visible=False,
                            interactive=False,
                        )
                        image_seed = gr.Number(
                            label="固定随机结果",
                            info="填写相同数字可尝试复现相似画面；留空为随机。",
                            precision=0,
                            minimum=0,
                            value=None,
                            visible=False,
                            interactive=False,
                        )
                        negative_prompt = gr.Textbox(
                            label="不希望画面出现的内容",
                            info="例如：水印、乱码、模糊。留空即可。",
                            lines=2,
                            visible=False,
                            interactive=False,
                        )
                        image_output_format = gr.Dropdown(
                            label="图片服务内部格式",
                            choices=["png"],
                            value="png",
                            visible=False,
                        )
                        reference_images = gr.File(
                            label="角色或画风参考图（可多选）",
                            file_count="multiple",
                            file_types=["image"],
                            type="filepath",
                            height=140,
                            visible=False,
                            interactive=False,
                        )
                        mask_image = gr.Image(
                            label="局部修改范围图（白色区域会被修改）",
                            type="filepath",
                            height=180,
                            visible=False,
                            interactive=False,
                        )
                        strict_image_mode = gr.Checkbox(
                            label="真实图片失败时停止，不使用占位图",
                            value=False,
                        )
                        image_concurrency = gr.Slider(
                            label="同时生成几格（速度设置）",
                            info="数值越大通常越快，也会占用更多本机或服务资源。",
                            minimum=1,
                            maximum=8,
                            value=1,
                            step=1,
                        )
                    with gr.Accordion("💬 文字与气泡", open=False):
                        lettering_style = gr.Dropdown(
                            label="漫画排字方式",
                            choices=[
                                ("沉浸式漫画排字（推荐）", "immersive"),
                                ("经典规则气泡", "classic"),
                                ("极简无框文字", "minimal"),
                            ],
                            value="immersive",
                        )
                        bubble_theme = gr.Dropdown(
                            label="气泡配色",
                            choices=[
                                ("经典漫画", "classic"),
                                ("日式黑白", "manga"),
                                ("现代彩漫", "modern"),
                            ],
                            value="classic",
                        )
                        show_narration = gr.Checkbox(label="显示旁白", value=True)
                        show_panel_numbers = gr.Checkbox(
                            label="显示分格编号（调试）",
                            value=False,
                        )
                        auto_shorten_dialogue = gr.Checkbox(
                            label="自动缩短过长台词",
                            value=True,
                        )

            with gr.Column(scale=2, elem_classes="cf-main-column"):
                with gr.Group(elem_classes="cf-flow-hub"):
                    gr.HTML(
                        """
                        <div class="cf-flow-heading">
                          <h2>开始创作</h2>
                          <div class="cf-workflow-line">
                            <span>1 · 输入</span><i>›</i>
                            <span>2 · 分镜</span><i>›</i>
                            <span>3 · 成品</span>
                          </div>
                        </div>
                        """,
                        elem_id="cf-flow-heading",
                        padding=False,
                    )
                    generation_mode = gr.Radio(
                        label="生成方式",
                        choices=[
                            ("先看分镜", "manual"),
                            ("一键生成", "auto"),
                        ],
                        value="manual",
                    )
                    flow_note = gr.HTML(
                        '<div class="cf-flow-note"><strong>先看分镜</strong> · '
                        "确认内容后再生成图片</div>",
                        elem_id="cf-flow-note",
                        padding=False,
                    )
                    with gr.Group(
                        visible=True,
                        elem_classes="cf-primary-action",
                    ) as manual_flow_actions:
                        script_button = gr.Button(
                            "生成分镜",
                            variant="primary",
                        )
                    with gr.Group(
                        visible=False,
                        elem_classes="cf-primary-action",
                    ) as auto_flow_actions:
                        auto_generate_button = gr.Button(
                            "一键生成漫画",
                            variant="primary",
                        )
                generation_status = gr.Markdown(
                    "等待开始",
                    elem_classes="cf-status",
                )
                with gr.Group(elem_classes="cf-canvas-shell"):
                    gr.HTML(
                        '<div class="cf-canvas-heading"><strong>漫画画布</strong>'
                        "<span>整页或放大查看</span></div>",
                        elem_id="cf-canvas-heading",
                        padding=False,
                    )
                    preview_mode = gr.Radio(
                        label="预览方式",
                        choices=[
                            ("整页预览", "fit"),
                            ("放大阅读", "width"),
                        ],
                        value="fit",
                        container=False,
                        elem_id="cf-preview-mode",
                        elem_classes="cf-preview-mode",
                    )
                    preview = gr.Image(
                        label="漫画预览",
                        type="pil",
                        format="png",
                        interactive=False,
                        elem_id="comic-preview",
                        elem_classes="cf-preview-fit",
                    )
                    gr.Markdown(
                        "整页预览显示完整页面；放大阅读会铺满宽度并上下滚动。",
                        elem_id="cf-preview-help",
                        elem_classes="cf-preview-help",
                    )
                with gr.Tabs(elem_classes="cf-workspace-tabs"):
                    with gr.Tab("01 · ✍ 分镜与剧本"):
                        final_title = gr.Textbox(
                            label="漫画标题",
                            placeholder="生成分镜后可在这里修改",
                        )
                        storyboard_editor = gr.Dataframe(
                            headers=["序号", "画面描述", "对白", "旁白"],
                            datatype=["number", "str", "str", "str"],
                            type="array",
                            interactive=True,
                            label="逐格编辑",
                            max_height=460,
                        )
                        with gr.Group(elem_classes="cf-revision-card"):
                            gr.Markdown(
                                "#### 继续修改故事",
                                elem_id="cf-revision-heading",
                            )
                            story_guidance = gr.Textbox(
                                label="故事修改要求",
                                placeholder=(
                                    "补充事实、顺序、人物关系或禁止内容"
                                ),
                                lines=5,
                            )
                            redesign_button = gr.Button(
                                "↻ 重做分镜",
                            )
                        generate_button = gr.Button(
                            "生成漫画",
                            variant="primary",
                            elem_classes="cf-primary-action",
                        )
                        with gr.Accordion("📑 查看故事、角色与完整分镜", open=False):
                            details = gr.Markdown(
                                "生成后将在这里显示故事、角色和完整分镜。"
                            )
                    with gr.Tab("02 · 🌐 成品语言"), gr.Group(
                        elem_classes="cf-language-card"
                    ):
                            gr.Markdown(
                                "#### 复用图片，只替换漫画文字\n"
                                "AI 翻译或使用分镜表格中的人工译文。"
                            )
                            localized_language = gr.Dropdown(
                                label="目标漫画语言",
                                choices=[
                                    ("简体中文", "zh-CN"),
                                    ("English", "en"),
                                    ("日本語", "ja-JP"),
                                ],
                                value="en",
                            )
                            localization_mode = gr.Radio(
                                label="文字来源",
                                choices=[
                                    ("使用当前文本模型翻译", "model"),
                                    ("使用我在分镜表格中填写的译文", "manual"),
                                ],
                                value="model",
                            )
                            relocalize_button = gr.Button(
                                "应用语言",
                                variant="primary",
                            )
                    with gr.Tab("03 · 📁 项目与导出"):
                        gr.Markdown(
                            "### ↥ 继续项目"
                        )
                        with gr.Row():
                            project_upload = gr.File(
                                label="选择 project.json",
                                file_types=[".json"],
                                type="filepath",
                                elem_classes="cf-compact-upload",
                                scale=2,
                            )
                            load_project_button = gr.Button(
                                "↥ 载入并继续编辑",
                                scale=1,
                            )
                        gr.Markdown(
                            "### ↓ 导出"
                        )
                        with gr.Row(elem_classes="cf-download-row"):
                            download = gr.DownloadButton(
                                "↓ 导出 PNG",
                                size="md",
                                variant="primary",
                            )
                            pdf_download = gr.DownloadButton(
                                "↓ 导出 PDF",
                                size="md",
                            )
                            project_download = gr.DownloadButton(
                                "↓ 项目 JSON",
                                size="md",
                            )

        custom_layout_outputs = [
            custom_layout_state,
            custom_layout_table,
            custom_layout_preview,
            custom_layout_status,
            custom_selected_index,
        ]
        custom_layout_table.select(
            fn=select_custom_frame_for_ui,
            outputs=[custom_selected_index, custom_layout_status],
        )
        insert_custom_frame_button.click(
            fn=handle_insert_custom_frame,
            inputs=[
                custom_frame_type,
                custom_layout_state,
                custom_selected_index,
                panel_count,
            ],
            outputs=custom_layout_outputs,
        )
        replace_custom_frame_button.click(
            fn=handle_replace_custom_frame,
            inputs=[
                custom_frame_type,
                custom_layout_state,
                custom_selected_index,
                panel_count,
            ],
            outputs=custom_layout_outputs,
        )
        delete_custom_frame_button.click(
            fn=handle_delete_custom_frame,
            inputs=[
                custom_frame_type,
                custom_layout_state,
                custom_selected_index,
                panel_count,
            ],
            outputs=custom_layout_outputs,
        )
        reset_custom_layout_button.click(
            fn=handle_reset_custom_layout,
            inputs=[
                custom_frame_type,
                custom_layout_state,
                custom_selected_index,
                panel_count,
            ],
            outputs=custom_layout_outputs,
        )

        preview_mode.change(
            fn=None,
            inputs=[preview_mode],
            outputs=None,
            js="""
            (mode) => {
              const canvas = document.getElementById('comic-preview');
              if (!canvas) return;
              canvas.classList.toggle('cf-preview-fit', mode === 'fit');
              canvas.classList.toggle('cf-preview-width', mode === 'width');
              const scroller = canvas.querySelector('.image-container, .wrap');
              if (scroller) scroller.scrollTop = 0;
            }
            """,
        )

        generation_mode.change(
            fn=workflow_mode_updates,
            inputs=[generation_mode, layout_mode],
            outputs=[
                manual_flow_actions,
                auto_flow_actions,
                layout_mode,
                custom_layout_designer,
                flow_note,
            ],
        )
        layout_mode.change(
            fn=layout_mode_updates,
            inputs=[layout_mode, generation_mode, panel_count],
            outputs=[custom_layout_designer, layout_mode_note],
        )
        layout_mode.change(
            fn=sync_custom_layout_for_ui,
            inputs=[layout_mode, panel_count, custom_layout_state],
            outputs=custom_layout_outputs,
        )
        panel_count.change(
            fn=layout_mode_updates,
            inputs=[layout_mode, generation_mode, panel_count],
            outputs=[custom_layout_designer, layout_mode_note],
        )
        panel_count.change(
            fn=sync_custom_layout_for_ui,
            inputs=[layout_mode, panel_count, custom_layout_state],
            outputs=custom_layout_outputs,
        )

        check_button.click(
            fn=handle_status,
            inputs=[provider],
            outputs=[model_status],
        )
        provider.change(
            fn=handle_status,
            inputs=[provider],
            outputs=[model_status],
        )
        check_image_button.click(
            fn=handle_image_status,
            inputs=[image_provider],
            outputs=[image_model_status],
        )
        image_provider.change(
            fn=handle_image_provider_change,
            inputs=[image_provider],
            outputs=[
                image_model,
                image_model_status,
                image_capabilities,
                negative_prompt,
                image_seed,
                reference_images,
                mask_image,
                image_quality,
                image_output_format,
            ],
        )
        script_button.click(
            fn=handle_script_generation,
            inputs=[
                theme,
                source_story,
                style,
                panel_count,
                provider,
                content_language,
                layout_mode,
                allow_multi_shot_panels,
                custom_layout_state,
            ],
            outputs=[
                script_state,
                details,
                storyboard_editor,
                final_title,
                generation_status,
            ],
        )
        redesign_button.click(
            fn=handle_story_redesign,
            inputs=[script_state, storyboard_editor, story_guidance, provider],
            outputs=[
                script_state,
                details,
                storyboard_editor,
                final_title,
                generation_status,
            ],
        )
        load_project_button.click(
            fn=handle_project_load,
            inputs=[project_upload],
            outputs=[
                script_state,
                details,
                storyboard_editor,
                content_language,
                story_guidance,
                final_title,
                layout_mode,
                allow_multi_shot_panels,
                custom_layout_state,
                custom_layout_table,
                custom_layout_preview,
                panel_count,
                custom_layout_status,
                custom_selected_index,
                generation_status,
            ],
        )
        generate_button.click(
            fn=handle_confirmed_generation,
            inputs=[
                script_state,
                storyboard_editor,
                final_title,
                layout_mode,
                allow_multi_shot_panels,
                custom_layout_state,
                image_provider,
                image_model,
                negative_prompt,
                image_width,
                image_height,
                image_aspect_ratio,
                image_quality,
                image_seed,
                image_output_format,
                reference_images,
                mask_image,
                strict_image_mode,
                secondary_image_provider,
                image_concurrency,
                bubble_theme,
                lettering_style,
                show_narration,
                show_panel_numbers,
                auto_shorten_dialogue,
            ],
            outputs=[
                script_state,
                preview,
                details,
                download,
                pdf_download,
                project_download,
                generation_status,
            ],
        )
        auto_generate_button.click(
            fn=handle_auto_generation,
            inputs=[
                generation_mode,
                theme,
                source_story,
                style,
                panel_count,
                provider,
                content_language,
                layout_mode,
                allow_multi_shot_panels,
                image_provider,
                image_model,
                negative_prompt,
                image_width,
                image_height,
                image_aspect_ratio,
                image_quality,
                image_seed,
                image_output_format,
                reference_images,
                mask_image,
                strict_image_mode,
                secondary_image_provider,
                image_concurrency,
                bubble_theme,
                lettering_style,
                show_narration,
                show_panel_numbers,
                auto_shorten_dialogue,
            ],
            outputs=[
                script_state,
                details,
                storyboard_editor,
                final_title,
                preview,
                download,
                pdf_download,
                project_download,
                generation_status,
            ],
        )
        relocalize_button.click(
            fn=handle_relocalization,
            inputs=[
                script_state,
                storyboard_editor,
                final_title,
                localized_language,
                localization_mode,
                provider,
                layout_mode,
                bubble_theme,
                lettering_style,
                show_narration,
                show_panel_numbers,
                auto_shorten_dialogue,
            ],
            outputs=[
                script_state,
                details,
                storyboard_editor,
                final_title,
                content_language,
                preview,
                download,
                pdf_download,
                project_download,
                generation_status,
            ],
        )

    return demo


def launch() -> None:
    """Launch using optional environment settings."""
    server_name = os.getenv("COMICFORGE_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("COMICFORGE_SERVER_PORT", "7860"))
    create_demo().launch(server_name=server_name, server_port=server_port)


if __name__ == "__main__":
    launch()
