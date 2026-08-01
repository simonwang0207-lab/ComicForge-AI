"""Gradio user interface for provider-based comic generation."""

from __future__ import annotations

import os

import gradio as gr

from comicforge_ai.models import (
    TextModelRegistry,
    TextModelStatus,
    build_default_registry,
)
from comicforge_ai.models.base import TextModelError
from comicforge_ai.schemas import ComicProject
from comicforge_ai.service import ComicGenerationResult, ComicGenerator


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
    return (
        f"### {project.title}\n\n"
        f"**故事梗概：** {project.story}\n\n"
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


def _generation_status_markdown(result: ComicGenerationResult) -> str:
    provenance = (
        f"实际 Provider：`{result.actual_provider_name}`  \n"
        f"实际模型：`{result.actual_model_name}`"
    )
    if result.fallback_used:
        return (
            "### ⚠️ 已回退到 MockTextModel\n\n"
            f"请求的 Provider `{result.requested_provider_id}` 调用失败。  \n"
            f"失败请求耗时：`{result.requested_provider_seconds:.2f} 秒`  \n"
            f"失败原因：{result.fallback_reason}  \n"
            f"{provenance}  \n"
            f"Mock 回退耗时：`{result.actual_provider_seconds:.2f} 秒`"
        )
    thinking = (
        f"  \nThinking 控制：`{result.thinking_control}`"
        if result.thinking_control
        else ""
    )
    return (
        f"### ✅ 文本方案生成成功\n\n{provenance}  \n"
        f"文本生成耗时：`{result.requested_provider_seconds:.2f} 秒`"
        f"{thinking}  \n未发生 Mock 回退。"
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


def generate_for_ui(
    theme: str,
    style: str,
    panel_count: int,
    provider_id: str = "mock",
    generator: ComicGenerator | None = None,
) -> tuple[object, str, str, str]:
    """Thin UI adapter returning preview, details, file, and provenance."""
    service = generator or ComicGenerator()
    try:
        result = service.generate_with_status(
            theme=theme,
            style=style,
            panel_count=int(panel_count),
            provider_id=provider_id,
        )
    except (ValueError, TextModelError) as exc:
        raise gr.Error(str(exc)) from exc
    return (
        result.comic_page,
        _project_markdown(result.project),
        str(result.project.output_path),
        _generation_status_markdown(result),
    )


def create_demo(
    registry: TextModelRegistry | None = None,
    generator: ComicGenerator | None = None,
) -> gr.Blocks:
    """Build and return the Chinese Gradio interface."""
    active_registry = registry or build_default_registry()
    service = generator or ComicGenerator(registry=active_registry)

    def handle_status(provider_id: str) -> str:
        return check_model_for_ui(provider_id, service)

    def handle_generation(
        theme: str, style: str, panel_count: int, provider_id: str
    ) -> tuple[object, str, str, str]:
        return generate_for_ui(theme, style, panel_count, provider_id, service)

    with gr.Blocks(title="ComicForge AI · Text Provider Demo") as demo:
        gr.Markdown(
            """
            # 🎨 ComicForge AI
            ### 第二阶段：统一文本模型 Provider + Mock 图片闭环

            可以选择离线 Mock、Ollama 或任意 OpenAI-compatible 文本服务生成结构化漫画方案。
            图片阶段仍使用 MockImageModel，并自动排版、预览和导出 PNG。
            """
        )
        with gr.Row():
            with gr.Column(scale=1):
                theme = gr.Textbox(
                    label="漫画主题",
                    placeholder="例如：一只猫第一次坐地铁",
                    value="一只猫第一次坐地铁",
                )
                style = gr.Dropdown(
                    label="漫画风格",
                    choices=["清新治愈", "热血日漫", "复古像素", "水彩童话", "科幻霓虹"],
                    value="清新治愈",
                    allow_custom_value=True,
                )
                panel_count = gr.Number(
                    minimum=1,
                    maximum=20,
                    value=4,
                    step=1,
                    precision=0,
                    label="漫画格数（UI 暂定 1–20，底层不写死）",
                )
                provider = gr.Dropdown(
                    label="文本模型",
                    choices=active_registry.choices(),
                    value="mock",
                )
                check_button = gr.Button("检测模型状态")
                model_status = gr.Markdown(
                    _model_status_markdown(service.check_provider("mock"))
                )
                generate_button = gr.Button("生成漫画", variant="primary")
                download = gr.File(label="导出 PNG")
            with gr.Column(scale=2):
                preview = gr.Image(
                    label="漫画预览",
                    type="pil",
                    format="png",
                    interactive=False,
                )
        generation_status = gr.Markdown("尚未生成。")
        details = gr.Markdown("生成后将在这里显示故事、角色和分镜。")

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
        generate_button.click(
            fn=handle_generation,
            inputs=[theme, style, panel_count, provider],
            outputs=[preview, details, download, generation_status],
        )

    return demo


def launch() -> None:
    """Launch using optional environment settings."""
    server_name = os.getenv("COMICFORGE_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("COMICFORGE_SERVER_PORT", "7860"))
    create_demo().launch(server_name=server_name, server_port=server_port)


if __name__ == "__main__":
    launch()
