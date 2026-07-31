"""Gradio user interface for the local Mock Demo."""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr

from comicforge_ai.schemas import ComicProject
from comicforge_ai.service import ComicGenerator


def _project_markdown(project: ComicProject) -> str:
    characters = "\n".join(
        f"- **{character.name}**：{character.appearance}；{character.personality}"
        for character in project.characters
    )
    panels = "\n".join(
        (
            f"{panel.number}. **{panel.scene}**  \n"
            f"   对白：{panel.dialogue or '（无）'}"
        )
        for panel in project.panels
    )
    return (
        f"### {project.title}\n\n"
        f"**故事梗概：** {project.story}\n\n"
        f"#### 角色\n{characters}\n\n"
        f"#### 分镜\n{panels}"
    )


def generate_for_ui(
    theme: str,
    style: str,
    panel_count: int,
) -> tuple[object, str, str]:
    """Gradio event handler returning preview, story text, and download path."""
    try:
        project, comic_page = ComicGenerator().generate(
            theme=theme,
            style=style,
            panel_count=int(panel_count),
        )
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    return comic_page, _project_markdown(project), str(project.output_path)


def create_demo() -> gr.Blocks:
    """Build and return the Chinese Gradio interface."""
    with gr.Blocks(title="ComicForge AI · Mock Demo") as demo:
        gr.Markdown(
            """
            # 🎨 ComicForge AI
            ### 第一天 Mock Demo：从主题到完整漫画，全流程无需 API Key

            输入创意后，MockTextModel 会生成故事、角色和分镜，
            MockImageModel 会制作带文字的占位画面并自动排版。
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
                panel_count = gr.Slider(
                    minimum=1,
                    maximum=8,
                    value=4,
                    step=1,
                    label="漫画格数（默认四格）",
                )
                generate_button = gr.Button("生成 Mock 漫画", variant="primary")
                download = gr.File(label="导出 PNG")
            with gr.Column(scale=2):
                preview = gr.Image(
                    label="漫画预览",
                    type="pil",
                    format="png",
                    interactive=False,
                )
        details = gr.Markdown("生成后将在这里显示故事、角色和分镜。")

        generate_button.click(
            fn=generate_for_ui,
            inputs=[theme, style, panel_count],
            outputs=[preview, details, download],
        )

    return demo


def launch() -> None:
    """Launch using optional environment settings."""
    server_name = os.getenv("COMICFORGE_SERVER_NAME", "127.0.0.1")
    server_port = int(os.getenv("COMICFORGE_SERVER_PORT", "7860"))
    create_demo().launch(server_name=server_name, server_port=server_port)


if __name__ == "__main__":
    launch()

