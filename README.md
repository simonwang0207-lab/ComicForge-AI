# ComicForge AI

ComicForge AI 是一个可接入多种文本与图像模型的漫画制作平台。当前第二阶段已经建立统一文本模型 Provider 架构，可使用离线 Mock、Ollama 本地模型或任意 OpenAI-compatible Chat Completions API 生成结构化漫画方案，再沿用 Pillow Mock 图片、自动排版、页面预览和 PNG 导出完成整条漫画流水线。

即使未安装 Ollama、没有 API Key 或远程调用失败，项目仍可使用 `MockTextModel` 完整演示。真实 Provider 失败并启用回退时，界面会明确显示失败原因和实际使用的 Mock 模型，不会伪装成真实模型成功。

第二阶段已在本机用 Ollama `qwen3:4b` 完成真实文本生成验证：请求显式使用 `think=false`，约 15.04 秒生成结构化四格方案，实际使用 Ollama Provider 且未发生 Mock 回退。自动化测试仍全部使用 Mock HTTP，不依赖本机 Ollama 或真实 API。

- 第一天效果与截图：[`docs/DAY1_PROGRESS_REPORT.md`](docs/DAY1_PROGRESS_REPORT.md)
- 第二阶段架构与进度：[`docs/STAGE2_PROGRESS_REPORT.md`](docs/STAGE2_PROGRESS_REPORT.md)

## 当前功能

- 中文 Gradio 操作界面
- 输入漫画主题、视觉风格和分镜数量
- 在 UI 中选择文本 Provider、检测可用状态
- `MockTextModel`：完全离线、始终可用
- `OllamaTextModel`：通过本地 Ollama HTTP API 调用模型
- `OpenAICompatibleTextModel`：通用 Chat Completions API，不绑定具体平台
- 统一生成标题、故事梗概、任意角色列表和任意分镜列表
- 每格包含场景、画面描述、角色、动作、对白、旁白和 `image_prompt`
- 自动提取 Markdown 代码块中的 JSON，并使用 Pydantic 校验
- JSON 失败时进行有限修复重试
- 真实模型失败时可显式回退到 Mock
- Pillow 分镜占位图、双列自动排版、PNG 预览与下载
- 无真实 API、无真实 API Key 的自动化测试

## 项目结构

```text
ComicForge-AI/
├── app.py
├── pyproject.toml
├── src/comicforge_ai/
│   ├── models/
│   │   ├── base.py
│   │   ├── http.py
│   │   ├── parsing.py
│   │   ├── registry.py
│   │   ├── mock_text.py
│   │   ├── ollama_text.py
│   │   ├── openai_compatible_text.py
│   │   └── mock_image.py
│   ├── prompts/
│   │   └── comic_generation.py
│   ├── layout.py
│   ├── schemas.py
│   ├── service.py
│   └── ui.py
├── tests/
├── docs/
├── requirements.txt
├── AGENTS.md
├── TASKS.md
└── .env.example
```

## 架构边界

```text
Gradio UI
    │ 只收集输入、显示状态与结果
    ▼
ComicGenerator service
    │ 只依赖 TextModelProvider 接口与注册表
    ▼
Mock / Ollama / OpenAI-compatible Provider
    │ 统一返回经过校验的 ComicProject
    ▼
MockImageModel → compose_comic → PNG
```

Provider 不依赖 Gradio；UI 和业务层不包含 Ollama、API 地址判断或 HTTP 请求。提示词位于独立的 `prompts/` 模块，JSON 提取与 Pydantic 校验也由统一解析模块负责。

## 环境与安装

要求 Python 3.11。项目依赖安装在仓库内 `.venv`：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

项目不安装或下载任何大模型。真实模型服务由用户在本机单独准备。

## 启动 Demo

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe app.py
```

访问 <http://127.0.0.1:7860>。生成的 PNG 默认保存在项目内 `outputs/`。

如果没有任何真实模型配置，直接在“文本模型”中选择“Mock 文本模型（离线）”即可完成全部演示。

## 配置 Ollama

先在本机安装并启动 Ollama，再准备一个支持中文和 JSON 输出的文本模型。例如：

```powershell
ollama pull qwen3:4b
ollama serve
```

在启动 ComicForge AI 的终端中设置：

```powershell
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:OLLAMA_MODEL="qwen3:4b"
$env:OLLAMA_CONNECT_TIMEOUT="10"
$env:OLLAMA_GENERATION_TIMEOUT="300"
.\.venv\Scripts\python.exe app.py
```

对 Qwen3 等 thinking 模型，Ollama `/api/chat` 请求会发送顶层 `think=false`。旧接口若明确拒绝该字段，会自动改用 `/no_think` 提示词重试。连接失败、HTTP 错误、模型不存在和生成超时会分别显示，界面同时记录失败请求耗时和原始异常；生成时若允许回退，仍会明确显示原因并使用 Mock。

## 配置 OpenAI-compatible API

该 Provider 使用标准 `/models` 和 `/chat/completions` 接口。`base_url` 应包含服务要求的 API 前缀，通常以 `/v1` 结尾。

在本机终端设置以下环境变量；凭据只填写在本机，不要写入代码、README、日志或 Git：

```powershell
$env:OPENAI_COMPATIBLE_BASE_URL="https://你的服务地址/v1"
$env:OPENAI_COMPATIBLE_API_KEY="在本机填写"
$env:OPENAI_COMPATIBLE_MODEL="你的模型名称"
$env:TEXT_MODEL_CONNECT_TIMEOUT="10"
$env:TEXT_MODEL_GENERATION_TIMEOUT="300"
.\.venv\Scripts\python.exe app.py
```

配置项名称也列在 `.env.example` 中。`.env` 已被 `.gitignore` 忽略；当前应用直接读取进程环境变量，不会自动加载 `.env` 文件。

## 回退与重试配置

```text
TEXT_MODEL_CONNECT_TIMEOUT=10
TEXT_MODEL_GENERATION_TIMEOUT=300
TEXT_MODEL_STATUS_TIMEOUT=10
TEXT_MODEL_MAX_RETRIES=1
TEXT_MODEL_FALLBACK_TO_MOCK=true
```

- `TEXT_MODEL_CONNECT_TIMEOUT` 只限制建立连接；默认 10 秒。
- `TEXT_MODEL_GENERATION_TIMEOUT` 限制等待模型生成和读取响应；默认 300 秒。
- Ollama 可使用 `OLLAMA_CONNECT_TIMEOUT`、`OLLAMA_GENERATION_TIMEOUT` 单独覆盖。
- `TEXT_MODEL_MAX_RETRIES=1` 表示第一次 JSON 校验失败后，最多请求一次完整 JSON 修复。
- `TEXT_MODEL_FALLBACK_TO_MOCK=true` 表示真实 Provider 最终失败后继续生成 Mock 方案。
- 回退不是静默行为；UI 会显示请求 Provider、失败原因、实际 Provider 和实际模型。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试使用注入的 Mock HTTP transport，不会访问 Ollama、互联网或真实 API，也不需要真实凭据。

## 当前限制

- 本阶段仍使用 `MockImageModel`，没有接入真实图像模型。
- `qwen3:4b` 负责文本方案，不能直接生成漫画图片；当前 PNG 中的分镜仍是 Pillow 文字占位图。
- 真实 Provider 的最终效果依赖具体模型对中文指令和严格 JSON 的遵循能力。
- UI 暂定允许 1–20 格以防误操作；底层 Pydantic 模型和业务层没有写死四格、八格或 20 格上限。
- 多页数据结构已经预留，当前排版仍把所有分镜合成为一张双列长图。
- 项目尚未支持保存后重新编辑、单格重生成和项目 JSON 导出。

## 下一阶段

- 设计统一的图片 Provider 接口，并保留 Mock 图片回退。
- 接入 ComfyUI + Stable Diffusion/FLUX 或兼容图像生成 API。
- 把逐格 `image_prompt` 转换为真实图片，支持单格重新生成。
- 改进角色一致性、风格一致性、错误提示和漫画排版。
