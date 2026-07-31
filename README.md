# ComicForge AI

ComicForge AI 是一个计划集成多种文本与图像大模型的漫画制作平台。当前版本是第一天的
Mock Demo：不调用真实模型、不需要 API Key，即可跑通“主题输入 → 故事/角色/分镜生成
→ 分镜占位图 → 漫画排版 → PNG 预览与导出”的完整流程。

阶段效果、关键代码思路、测试记录和汇报截图见
[`docs/DAY1_PROGRESS_REPORT.md`](docs/DAY1_PROGRESS_REPORT.md)。

## 当前功能

- 中文 Gradio 操作界面
- 输入漫画主题、视觉风格和 1–8 格漫画格数
- `MockTextModel` 生成结构化故事、角色和分镜
- `MockImageModel` 使用 Pillow 生成带编号、场景与对白的占位图
- 四格漫画自动采用 2×2 排版，其他格数自动流式排版
- 页面内预览，并将成品保存、导出为 PNG
- 使用 Pydantic 定义 `ComicProject`、`CharacterProfile`、`PanelSpec`
- pytest 基础测试覆盖文本、图片、排版和完整生成流程

## 项目结构

```text
ComicForge-AI/
├── app.py
├── pyproject.toml
├── src/comicforge_ai/
│   ├── models/
│   │   ├── mock_text.py
│   │   └── mock_image.py
│   ├── layout.py
│   ├── schemas.py
│   ├── service.py
│   └── ui.py
├── tests/
├── requirements.txt
├── AGENTS.md
├── TASKS.md
└── .env.example
```

## 环境与安装

要求 Python 3.11。建议在项目根目录创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

本项目不下载大型模型，也不会读取或要求任何 API Key。

## 启动 Demo

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe app.py
```

然后访问 <http://127.0.0.1:7860>。

生成的漫画默认保存在 `outputs/`。可参考 `.env.example` 设置输出目录、监听地址和端口。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 后续接入真实模型

后续模型适配器可沿用 Mock 模型的职责边界：文本模型返回 Pydantic 结构，图像模型接收
`PanelSpec` 并返回 Pillow 图片。这样可以在不改动排版和界面的情况下逐步替换实现。
