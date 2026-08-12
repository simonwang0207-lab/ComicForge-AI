# ComicForge AI（README 归档，2026-08-12）

> 本文件保留 2026-08-12 整理前的根目录 README 内容；当前项目门面请查看仓库根目录的 `README.md`。

ComicForge AI 是一个基于 Python 3.11 和 Gradio 的多模型漫画制作平台。文本模型负责生成、审查和修订结构化故事与分镜，图片模型只生成单格无文字画面，程序再在本地绘制标题、对白、旁白和拟声词，组合并导出漫画。

项目同时支持离线 Mock、本地 Ollama/ComfyUI 和云端 API。真实 Provider 失败时不会被悄悄伪装成成功：界面和 `project.json` 会记录请求/实际 Provider、模型、耗时、request ID、seed、尺寸、错误和 fallback。

## 当前功能

- 输入主题、自然语言需求或完整故事，生成任意正整数格数的结构化分镜。
- 文本创作模型与剧本审查模型独立选择；审查稿只有通过 Pydantic 校验后才应用。
- 可见漫画文字语言不合格时使用低随机性的短补丁，只修复对应分格和文字索引；默认最多执行两次并仅重试仍错误的文字，保留已经正确的角色、场景、动作和英文 `image_prompt`。
- 支持故事、角色、Story Bible、标题候选、场景、动作、结构化对白/旁白/思想/拟声词和英文绘图提示词。
- 付费生图前可编辑分镜、修改标题或根据补充说明重做故事；也可使用一键模式。
- 文本和图片 Provider 独立切换，能力和配置状态由注册表驱动。
- 传统漫画页、规则网格、竖向条漫和自定义画框；四格传统页为等宽 2×2。
- 本地气泡排字、负空间规划、文字位置表格覆盖和生图后多语言重排。
- 单格重新生成、旧图归档与回退；项目 JSON 保存和重新载入。
- 整页预览；全屏后滚轮缩放、左键拖动、双击复位。
- 导出 PNG、PDF 和 `project.json`。

当前没有宣称完成：跨格角色一致性的彻底解决、直接拖拽气泡、完整多页 UI/整册闭环、公网部署和多人在线协作。

## Provider 状态

状态定义：

- **已实现/已注册**：代码入口存在并可被注册表选择。
- **已配置**：当前机器填写了运行所需设置或存在使用记录。
- **连通/鉴权**：服务或凭据验证成功。
- **真实生成**：真实服务/本地模型输出有效图片且没有 Mock 回退。

### 文本 Provider

| Provider | 已实现 | 已注册 | 当前真实记录 | 适合 Demo | 限制 |
|---|---:|---:|---|---|---|
| Mock | 是 | 是 | 确定性离线生成 | 是，备用 | 不是大模型真实输出 |
| Ollama | 是 | 是 | 本机 `qwen3:4b` 已真实生成 | 是，本地路线 | 小模型长 JSON/审查稳定性有限；可能与 ComfyUI 争显存 |
| OpenAI Compatible | 是 | 是 | 当前项目记录有 `qwen3:4b` 生成及审查应用 | 取决于后端 | 各兼容服务格式、thinking 和 token 上限不同 |
| DeepSeek API | 是 | 是 | 尚未配置或真实验收 | 待验收 | 默认 `deepseek-v4-flash`；使用独立 Key/配置并关闭 thinking 生成结构化 JSON |

### 图片 Provider

| Provider | 已实现/注册 | 连通或鉴权 | 真实生成验收 | 当前 Demo 建议 |
|---|---:|---|---|---|
| Mock | 是 | 不需要 | 离线占位图闭环 | 文本组合验证/备用 |
| Recraft | 是 | 已完成 | **已完成，多次手测及四格无回退记录** | 云端主 Demo |
| SiliconFlow | 是 | **国际站鉴权成功；`GET /v1/models` 200；目标模型存在** | **未完成：账户余额为 0** | 只展示接入状态 |
| ComfyUI | 是 | 本地健康和工作流验证完成 | **已完成：SD1.5 512×512 严格单图及无回退项目** | 本地主/备用路线 |
| Gemini Image | 是 | 官方与 `generateContent` 中转模式均已适配 | 中转协议已完成单图与单参考图直接调用验收；尚待在 ComicForge 前端完成端到端验收 | 候选云端主路线；第三方中转按次计费且稳定性由中转商决定 |
| OpenAI Images | 是 | 当前无配置证据 | 未验收 | 暂不用于 Demo |
| Together | 是 | 当前无配置证据 | 未验收 | 暂不用于 Demo |
| fal | 是 | 当前无配置证据 | 未验收 | 暂不用于 Demo |

自动化 Mock HTTP 测试通过不等于真实 API 验收。完整矩阵与证据见[第三阶段及后续改进报告](docs/STAGE4_PROGRESS_REPORT.md)。

## 快速启动

```powershell
Set-Location F:\ZJU_intership\task\2\ComicForge-AI
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```

访问 `http://127.0.0.1:7860`。如果还没有任何本地模型或 API Key，直接选择 Mock Text 和 Mock Image 即可完成离线流程。

首次创建虚拟环境时：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Ruff 若未安装，可单独安装到开发环境；项目运行依赖以 `pyproject.toml` 为准。

## 推荐 Demo 方式

1. 提前在本机 `.env` 配置已验证的文本 Provider 和 Recraft。
2. 用 Mock Image 快速确认文本生成与审查，检查 `review_applied=true`。
3. 在界面选择四格、Recraft 和严格模式，点击一键生成或先确认分镜再生图。
4. 展示状态中的实际 Provider、耗时和无回退结果。
5. 全屏查看漫画并导出 PNG/PDF/项目 JSON。
6. Recraft 网络异常时切换已接通的本地 ComfyUI，或明确展示提前生成的同流程结果。

完整时间轴见 [Demo 功能清单与录制脚本](docs/DEMO_RECORDING_SCRIPT.md)。

## Ollama 本地文本模型

```powershell
ollama serve
ollama pull qwen3:4b
ollama list
```

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_GENERATION_TIMEOUT=300
OLLAMA_NUM_PREDICT=4096
OLLAMA_NUM_CTX=8192
```

项目发送顶层 `think=false`，并保留 `/no_think` 兼容提示。连接、状态检查、普通生成和审查超时分别配置；审查默认使用更短的 90 秒上限，避免可选审查拖住整个 Demo。

## ComfyUI 本地接入

1. 启动 ComfyUI 并确认 `http://127.0.0.1:8188/system_stats` 可访问。
2. 安装工作流所需 checkpoint、自定义节点、IPAdapter 和 CLIP Vision；大型权重不包含在仓库中。
3. 使用 ComfyUI 的 **API Format** Workflow JSON，不要直接使用普通 UI Workflow JSON。
4. 配置 `.env`：

```dotenv
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_PATH=workflows/comfyui_text2img_api.json
COMFYUI_MODEL=animagine-xl-4.0-ipadapter
COMFYUI_PROMPT_NODE_ID=6
COMFYUI_WIDTH_NODE_ID=5
COMFYUI_HEIGHT_NODE_ID=5
COMFYUI_SEED_NODE_ID=3
COMFYUI_NEGATIVE_PROMPT_NODE_ID=
COMFYUI_REFERENCE_IMAGE_NODE_ID=
```

程序复制工作流后动态替换 prompt、negative prompt、宽、高、seed 和可选参考图，然后调用 `/prompt`、轮询 `/history/{prompt_id}`，最后从 `/view` 下载图片。留空的 negative/reference 节点可按连线自动检测；更换 workflow 后必须重新核对节点 ID。

ComfyUI 不再把第一格剧情图自动用作后续角色参考，因为整张剧情图会把原有姿势、背景和特写构图一并带入 IPAdapter。需要角色一致性时，请上传单人、背景简单的标准参考图；前端会显示 Story Bible 的角色顺序，批量导入、拖动排序或从剪贴板逐张加入后，第 1 张对应第 1 个角色，以此类推，不要求修改文件名。文件列表提供固定高度和内部滚动，可拖动后面的条目调整顺序。参考图生效时，图片 Prompt 不再重复对应角色的模型生成外观设定，避免“文字写红发、参考图是黑发”等冲突；当前 API Workflow 的 IPAdapter 默认采用中等约束。当前整图参考只用于对应角色的单人近景或中景，远景、建立镜头、鸟瞰、环境镜头、群像和多人镜头会自动旁路 IPAdapter，优先保留剧情场景构图。该 Workflow 每格只有一个 IPAdapter 图片入口，多角色同格的独立身份锁定仍需升级为多 IPAdapter/区域约束工作流。

本地严格单图测试：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_image_provider.py `
  --provider comfyui `
  --model animagine-xl-4.0-ipadapter `
  --prompt "single anime comic scene, one hero, no text" `
  --width 512 --height 512
```

## 云端 Provider 配置

所有 Key 只填写到被 Git 忽略的 `.env`。完整变量见 [`.env.example`](.env.example) 和 [Image Provider 配置指南](docs/IMAGE_PROVIDER_GUIDE.md)。不要把真实 Key 写入代码、文档、截图或终端命令。

DeepSeek 与 Gemini 已作为独立 Provider 注册。填写配置并重新启动前端后，它们会由注册表自动出现在文本/审查模型和图片模型选项中：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash

GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GEMINI_API_MODE=interactions
GEMINI_GENERATE_CONTENT_CONFIG_MODE=image-config
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
GEMINI_IMAGE_SIZE=1K
GEMINI_MAX_RETRIES=0
```

Gemini Provider 同时支持官方 `interactions` 和兼容中转的 `generate-content` 两种协议。后者使用 `GET /v1/models` 做无生图状态检查，并使用 `/v1beta/models/{model}:generateContent` 生成或编辑图片；由于按次计费，默认不自动重试。当前中转协议已在项目外完成一次无参考图和一次单参考图真实请求，两次均返回 PNG；仍需在 ComicForge 前端完成严格单图端到端验收。DeepSeek 尚未完成真实鉴权或生成验收。验收前先阅读[文本与图片模型调研及选型](docs/MODEL_RESEARCH_AND_SELECTION.md)，并按单文本、单图、参考图、四格、8–20 格的顺序逐步进行，避免一次长任务产生不可控费用。

## 测试

以下检查不调用真实外部 API，也不产生费用：

```powershell
.\.venv\Scripts\python.exe -m ruff check app.py src tests scripts
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -c "import app; assert app.demo"
git diff --check
```

Ruff 是静态检查，pytest 是使用假 transport 的自动化行为测试，smoke test 才用于真实 Provider 单图验收。三者结论不能互相替代。

## 输出目录

每次运行通常创建：

```text
outputs/<时间_主题>/
├── panel_01.png ...
├── panel_versions/        # 单格重生成历史
├── comic.png
├── comic.pdf
└── project.json
```

`project.json` 保存相对路径和 Provider 溯源，不保存凭据或完整图片 base64。`outputs/` 是运行产物，不应提交 Git。

## 文档入口

- [项目成果与技术说明（提交主文档）](docs/PROJECT_DELIVERY_REPORT.md)
- [完整技术文档](docs/TECHNICAL_DOCUMENTATION.md)
- [第三阶段及后续改进进度报告](docs/STAGE4_PROGRESS_REPORT.md)
- [Demo 功能清单与录制脚本](docs/DEMO_RECORDING_SCRIPT.md)
- [图片 Provider 配置与验收指南](docs/IMAGE_PROVIDER_GUIDE.md)
- [文本与图片模型调研及选型](docs/MODEL_RESEARCH_AND_SELECTION.md)
- [第三阶段漫画质量记录](docs/STAGE3_COMIC_QUALITY_PROGRESS_REPORT.md)
- [第二阶段进度报告](docs/STAGE2_PROGRESS_REPORT.md)
- [第一天进度报告](docs/DAY1_PROGRESS_REPORT.md)
- [任务与后续优先级](TASKS.md)

## 当前限制

- Recraft 等云端服务依赖网络、余额和费用；ComfyUI 依赖本机模型、工作流、显存和队列。
- 参考图和 IPAdapter 能改善一致性，但无法保证不同分格角色完全一致。
- Ollama 小模型可能产生截断或结构不完整的 JSON；系统会修复或显式失败，但不能保证每次成功。
- OpenAI Images、Together、fal 尚未真实验收；SiliconFlow 尚未完成收费生图验收。
- 多页数据结构已经预留，但完整 UI 和整册导出尚未验收。
- 当前是本机 Gradio 应用，没有公网部署和多人在线访问证据。
