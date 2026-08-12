# ComicForge AI

> 把故事创意、结构化分镜、多模型生图、本地排字与漫画导出组织成一条可检查、可编辑、可追溯的制作流程。

![ComicForge AI 工作区](docs/assets/project_delivery/01.png)

ComicForge AI 是一个基于 **Python 3.11 + Gradio** 的 AI 辅助漫画制作平台。用户输入主题、故事梗概或完整剧本后，可以分别选择文本创作模型、剧本审查模型和图片生成模型，完成从故事设计到漫画成品的单页制作闭环。

与直接调用一个模型相比，本项目不仅返回一段文本或一张图片，还负责结构化分镜、结果校验、角色参考图映射、逐格生成、本地绘制对白、页面排版、局部重生成、版本回退以及生成记录保存。

## 项目亮点

- **完整创作闭环**：故事输入 → 剧本初稿 → 独立审查 → 分镜确认 → 逐格生图 → 本地排字 → 页面组合 → PNG/PDF 导出。
- **模型自由组合**：文本创作、剧本审查和图片生成互相独立，可按质量、速度、成本和本机条件组合 Provider。
- **本地与云端并存**：支持离线 Mock、本地 Ollama、本地 ComfyUI，以及 DeepSeek、Gemini、Recraft 等云端路线。
- **1–20 格前端创作**：界面可选择 1–20 格，不把核心数据结构固定为四格或八格；支持传统漫画页、规则网格、竖向条漫和自定义画框。
- **漫画文字由程序绘制**：图片模型只负责无文字画面；对白、思考、旁白和拟声词由 Pillow 在本地绘制，减少乱码并允许重新排字。
- **角色参考图工作流**：参考图按 Story Bible 角色顺序映射；支持批量导入、粘贴和拖动排序，并针对单人镜头构造避免外貌冲突的图片 Prompt。
- **可恢复的局部修改**：可只重新生成不满意的一格，原图进入版本历史并可回退，不必重新支付整页生成成本。
- **失败不会被掩盖**：界面区分连接失败、超时、结构校验失败、审查未应用和 Mock 回退，并显示实际 Provider、模型和耗时。
- **结果可复现和审计**：`project.json` 保存分镜、最终 Prompt、参考图角色、Provider、模型、尺寸、耗时、request ID、seed、错误和 fallback 状态。
- **无密钥也能运行**：Mock Text + Mock Image 可离线演示完整流程，自动化测试不会访问真实外部 API。

## 最终效果

下面是项目生成并由程序本地添加漫画文字、完成页面组合的示例：

![ComicForge AI 漫画示例](docs/assets/project_delivery/22.png)

> 生成式模型存在随机性，示例效果不代表每次请求都能获得完全相同的角色一致性和构图质量。

## 工作流程

```mermaid
flowchart LR
    A[故事或创作要求] --> B[文本模型生成结构化初稿]
    B --> C[JSON 提取、归一化与 Pydantic 校验]
    C --> D[独立审查模型返回修订]
    D --> E[用户确认或编辑分镜]
    E --> F[图片 Provider 逐格生成无字画面]
    F --> G[本地绘制对白、旁白、思考和拟声词]
    G --> H[漫画页面自动排版]
    H --> I[预览、局部重生成与版本回退]
    I --> J[PNG / PDF / project.json]
```

付费图片生成与剧本生成是分开的。用户可以先检查分镜，再决定是否调用真实图片 Provider，避免因文本错误浪费生图费用。

## 已实现功能

### 剧本与分镜

- 输入主题、自然语言要求或已有故事。
- 生成标题候选、故事梗概、角色设定和 Story Bible。
- 生成场景、动作、出场角色、构图、子镜头和英文绘图提示词。
- 生成 `speech`、`thought`、`narration`、`sfx` 四类结构化漫画文字。
- 文本创作模型与审查模型独立选择。
- 审查稿支持完整项目、局部 patch 和部分 panels；安全合并失败时保留已验证初稿继续生图。
- JSON 代码块提取、常见字段归一化、有限修复重试和 Pydantic 边界校验。
- 可见文字语言检查与针对性修复，只有图片 Prompt 使用英文。
- 分镜确认后再生图，也可使用一键生成。

### 图片与角色参考

- 文本 Provider 与图片 Provider 独立切换。
- 单图、多格和严格无 fallback smoke test 路线。
- 本地 ComfyUI API Workflow 动态替换 prompt、negative prompt、宽、高、seed 和参考图。
- Gemini 生成与参考图编辑；参考图可按当前分格角色自动筛选和映射。
- 用户参考图批量上传、剪贴板导入、顺序展示和拖动排序。
- 有参考图时避免在最终 Prompt 中重复冲突的发型、服装和配色描述。
- 单格重生成、旧图归档和历史版本回退。
- 每格独立记录真实 Provider、模型、请求参数、耗时、错误和 fallback。

### 排字、布局与项目管理

- 本地绘制对白气泡、思想气泡、旁白框和拟声词。
- 中文换行、气泡尾巴、文字锚点、预留区域与基础避让。
- 传统漫画页、规则网格、竖向条漫和自定义画框。
- 整页预览；全屏后支持滚轮缩放、左键拖动和双击复位。
- 导出 PNG、单页 PDF 和完整 `project.json`。
- 重新载入项目 JSON，继续修改和局部生成。
- 生图后切换内容语言并重新渲染本地文字。

## Provider 状态

状态说明：

- **实现/注册**：代码入口存在，并已加入注册表和前端选项。
- **真实验收**：真实 API 或本地模型返回了可解码结果，且没有发生 Mock 回退。
- 自动化假 transport 测试通过不等于真实 Provider 验收。

### 文本 Provider

| Provider | 实现/注册 | 当前验收状态 | 主要用途与限制 |
|---|:---:|---|---|
| Mock Text | ✅ | 离线闭环已验证 | 确定性测试和无密钥演示；不代表真实大模型质量 |
| Ollama | ✅ | 本机 `qwen3:4b` 已真实生成 | 本地免费；小模型生成长 JSON 和审查时稳定性有限 |
| OpenAI-compatible | ✅ | 已有真实生成和审查应用记录 | 可连接兼容 Chat Completions 的服务；不同后端格式和 token 上限有差异 |
| DeepSeek | ✅ | `deepseek-v4-flash` 已完成四格初稿与审查闭环 | 当前高质量文本候选；仍需继续统计 8–20 格多轮成功率 |

### 图片 Provider

| Provider | 实现/注册 | 当前验收状态 | 主要用途与限制 |
|---|:---:|---|---|
| Mock Image | ✅ | 离线闭环已验证 | 文本组合测试和备用展示；不是实际生图质量 |
| Gemini Image | ✅ | 中转协议无参考图、单参考图及 ComicForge 四格真实生成已完成，四格无 Mock 回退 | 当前云端候选路线；第三方中转的费用和稳定性由中转服务决定 |
| Recraft | ✅ | 多次真实手测及四格无回退记录 | 已验证云端 Demo 路线；跨格角色身份仍可能漂移 |
| ComfyUI | ✅ | 本地严格单图及多格无回退记录 | 本地免费、工作流可控；依赖模型文件、自定义节点、显存和队列状态 |
| SiliconFlow | ✅ | 国际站鉴权、模型列表和目标模型存在性已验证；未完成收费生图 | 账户余额为 0 时不能把鉴权成功写成真实生图验收 |
| OpenAI Images | ✅ | 尚未真实验收 | 已预留生成、参考图编辑、多参考图和蒙版接口 |
| Together | ✅ | 尚未真实验收 | 已完成代码适配和离线协议测试 |
| fal | ✅ | 尚未真实验收 | 已完成异步队列适配和离线协议测试 |

完整证据和限制见[阶段进度报告](docs/STAGE4_PROGRESS_REPORT.md)与[模型调研及选型](docs/MODEL_RESEARCH_AND_SELECTION.md)。

## 快速开始

### 1. 环境要求

- Windows PowerShell（文档命令以 Windows 为例）
- Python `>=3.11,<3.12`
- 可选：Ollama、ComfyUI 或云端 Provider API Key

### 2. 创建环境并安装

```powershell
git clone https://github.com/simonwang0207-lab/ComicForge-AI.git
Set-Location ComicForge-AI
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item .env.example .env
```

`.env` 已被 Git 忽略。请只把真实 API Key 写入本机 `.env`，不要写入代码、README、截图或终端记录。

### 3. 启动应用

```powershell
.\.venv\Scripts\python.exe app.py
```

浏览器访问：<http://127.0.0.1:7860>

如果没有 API Key 或本地模型，在前端选择 **Mock Text** 和 **Mock Image** 即可完成离线流程。

## 常用 Provider 配置

这里只展示变量名称和安全示例；完整配置见 [`.env.example`](.env.example)。修改 `.env` 后需要重新启动前端。

### Ollama 本地文本模型

```powershell
ollama serve
ollama pull qwen3:4b
```

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
```

### DeepSeek 文本模型

```dotenv
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
```

### Gemini 图片模型

官方与第三方兼容服务的协议、模型名和计费方式可能不同，请以实际服务为准：

```dotenv
GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GEMINI_API_MODE=interactions
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
GEMINI_IMAGE_SIZE=1K
GEMINI_MAX_RETRIES=0
```

按次计费的图片服务默认不自动重试，避免超时后产生重复扣费。

### ComfyUI 本地工作流

1. 启动 ComfyUI，确认 <http://127.0.0.1:8188/system_stats> 可访问。
2. 安装工作流需要的 checkpoint、IPAdapter 自定义节点和 CLIP Vision 权重。
3. 使用 **API Format** Workflow JSON，不要直接使用普通 UI Workflow JSON。
4. 配置：

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

仓库不包含大型模型权重。更换 Workflow 后必须重新核对节点 ID 和模型依赖。

## 输出文件

每次完整生成通常会创建：

```text
outputs/<时间_主题>/
├── panel_01.png
├── panel_02.png
├── ...
├── panel_versions/       # 单格重生成历史
├── comic.png             # 最终漫画
├── comic.pdf             # 单页 PDF
└── project.json          # 项目结构与生成溯源
```

`outputs/` 属于运行产物并已被 Git 忽略。`project.json` 不保存 API Key，也不会保存完整图片 Base64。

## 无费用测试

以下命令使用 Mock 或注入的假 HTTP transport，不会调用真实收费 API：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -c "import app; assert app.demo"
git diff --check
```

如果开发环境已经安装 Ruff，还可以运行：

```powershell
.\.venv\Scripts\python.exe -m ruff check app.py src tests scripts
```

真实 Provider 只能通过单独的 smoke test 或前端手动测试验收，可能产生费用：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_image_provider.py `
  --provider comfyui `
  --model animagine-xl-4.0-ipadapter `
  --prompt "single comic scene, no text" `
  --width 512 --height 512
```

## 项目结构

```text
ComicForge-AI/
├── app.py                         # 应用入口
├── src/comicforge_ai/
│   ├── ui.py                      # Gradio 界面和回调编排
│   ├── service.py                 # 漫画生成、审查、生图、保存和局部重生成服务
│   ├── schemas.py                 # Pydantic 核心数据模型
│   ├── models/                    # 文本/图片 Provider、注册表、HTTP 与错误类型
│   ├── prompts/                   # 剧本、审查、语言修复和图片 Prompt
│   ├── bubble_renderer.py         # 本地漫画文字与气泡绘制
│   └── layout.py                  # 页面布局、组合与导出
├── workflows/                     # ComfyUI API Workflow
├── scripts/                       # 预览与 Provider smoke test
├── tests/                         # 不访问真实 API 的自动化测试
├── docs/                          # 技术文档、阶段报告和 Demo 材料
├── .env.example                   # 可迁移的配置模板
└── TASKS.md                       # 已完成任务与后续优先级
```

## 架构原则

- 文本模型实现统一 `TextModelProvider`，通过 `TextModelRegistry` 注册。
- 图片模型实现统一 `ImageProvider`，通过 `ImageProviderRegistry` 注册。
- Provider 的 URL、鉴权、请求体和响应解析只存在于对应适配器中。
- Gradio 只收集输入、调用服务和格式化结果，不承载 Provider 协议逻辑。
- 模型输出只用安全 JSON 工具和 Pydantic 解析，绝不执行模型输出。
- 每次只向图片 Provider 发送一格的视觉 Prompt；漫画文字和整页排版在本地完成。
- 不支持的 Provider 参数必须显式拒绝，不能静默忽略。
- Mock fallback 只有在配置允许时发生，并始终暴露实际 Provider 和失败原因。

## 文档导航

- [项目成果与技术说明](docs/PROJECT_DELIVERY_REPORT.md)
- [完整技术文档](docs/TECHNICAL_DOCUMENTATION.md)
- [第三阶段及后续改进进度报告](docs/STAGE4_PROGRESS_REPORT.md)
- [Demo 功能清单与录制脚本](docs/DEMO_RECORDING_SCRIPT.md)
- [文本与图片模型调研及选型](docs/MODEL_RESEARCH_AND_SELECTION.md)
- [模型调研 Word 版本](docs/MODEL_RESEARCH_AND_SELECTION.docx)
- [图片 Provider 配置与验收指南](docs/IMAGE_PROVIDER_GUIDE.md)
- [漫画质量改进记录](docs/STAGE3_COMIC_QUALITY_PROGRESS_REPORT.md)
- [第二阶段进度报告](docs/STAGE2_PROGRESS_REPORT.md)
- [第一天进度报告](docs/DAY1_PROGRESS_REPORT.md)
- [任务状态与后续优先级](TASKS.md)
- [旧版 README 归档](docs/README_ARCHIVE_2026-08-12.md)

## 当前限制

- 角色参考图和 IPAdapter/Gemini 编辑可以改善一致性，但不能保证跨格身份、服装和比例完全一致。
- 当前 ComfyUI Workflow 每格只有一个 IPAdapter 图片入口；多人同框的独立身份锁定需要多 IPAdapter 或区域约束工作流。
- 本地模型受显存、模型加载和 ComfyUI 队列影响；云端模型受网络、余额、速率限制和费用影响。
- 小型文本模型仍可能输出截断或结构不完整的 JSON；系统会修复或明确失败，但不能保证每次成功。
- 多页数据结构已经预留，但尚未形成完整的多页编辑、整册管理和整册导出 UI 闭环。
- 当前是单机 Gradio 应用，尚未完成用户系统、公网部署和多人实时协作。
- OpenAI Images、Together、fal 尚未完成真实生成验收；SiliconFlow 尚未完成收费生图验收。

## 后续方向

- 提升 8–20 格长项目的文本结构稳定性和审查成功率。
- 升级 ComfyUI 多角色参考、区域约束或 Qwen-Image-Edit 工作流。
- 完整实现多页编辑和整册导出。
- 增加可视化气泡拖拽、缩放和样式编辑。
- 增加部署、用户权限、配额和任务队列能力。

---

ComicForge AI 当前定位是一个可运行、可扩展、可追溯的多模型漫画制作平台原型。README 中的“已实现”“已配置”和“真实验收”均按不同状态记录，不以自动化测试代替真实 API 验收。
