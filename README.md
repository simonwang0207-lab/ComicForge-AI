# ComicForge AI

ComicForge AI 是一个可接入多种文本与图像模型的漫画制作平台。当前版本分别提供文本 Provider 和图片 Provider：文本模型生成结构化故事、角色与分镜，图片模型只接收每格的视觉提示词，生成本地分镜图片后再进行漫画排字、页面排版和 PNG 导出。

即使没有真实模型或 API Key，项目仍可使用 `MockTextModel` 和 `MockImageModel` 完整演示。真实 Provider 失败并启用回退时，界面和 `project.json` 会明确记录失败原因、实际 Provider 和发生回退的分格，不会伪装成真实生成成功。

第二阶段已在本机用 Ollama `qwen3:4b` 完成真实文本生成验证：请求显式使用 `think=false`，约 15.04 秒生成结构化四格方案，实际使用 Ollama Provider 且未发生 Mock 回退。自动化测试仍全部使用 Mock HTTP，不依赖本机 Ollama 或真实 API。

- 第一天效果与截图：[`docs/DAY1_PROGRESS_REPORT.md`](docs/DAY1_PROGRESS_REPORT.md)
- 第二阶段架构与进度：[`docs/STAGE2_PROGRESS_REPORT.md`](docs/STAGE2_PROGRESS_REPORT.md)
- 图片 Provider 2.0 配置与能力矩阵：[`docs/IMAGE_PROVIDER_GUIDE.md`](docs/IMAGE_PROVIDER_GUIDE.md)
- 第三阶段漫画质量、困难与优化记录：[`docs/STAGE3_COMIC_QUALITY_PROGRESS_REPORT.md`](docs/STAGE3_COMIC_QUALITY_PROGRESS_REPORT.md)

## 当前功能

- 中文 Gradio 操作界面
- 两阶段生成：先生成/审查/编辑剧本，确认后才调用图片 Provider
- 人工审查与自动直出可选；自动模式会明确提示并立即调用图片 Provider
- 连续多轮故事修订会累积保存每轮约束和修订历史
- 标题生成 3 个候选，最终标题可在生图前直接编辑
- 页面支持传统漫画页、竖向滚动条漫、旧版规则网格和用户自定义画框；四格传统页保持等宽 2×2 并铺满画框
- 自定义画框可按“＋”顺序添加方形、竖幅、横向通栏或超宽通栏，页面无重叠、无残缺空行
- 可允许模型在必要时为单格设计插入特写、分割镜头或蒙太奇，仍保持一个清晰主画面
- Story Bible 自动审查人物时间线、身份、因果、连续性和静态动作可视化
- 结构化 speech/thought/narration/sfx 与沉浸式漫画排字，不再使用底部字幕条或 PPT 式旁白卡片
- 对白采用半透明手绘轮廓气泡，旁白默认无框描边，拟声词放大、双描边并轻微倾斜
- 排字位置参考底图边缘密度，优先选择低细节区域；成品默认不显示左上角分格编号
- 生图后可使用文本模型翻译或人工改写标题/对白/旁白/SFX，复用原始无字分格重新排版，0 图片 Units
- 已生成语言缓存在 `project.json`，再次切换无需翻译；图片 Provider 不会被重复调用
- 图片提示词提前规划角色位置和气泡负空间
- 漫画内容语言支持简体中文、English、日本語，UI 继续保持中文
- 可重新载入新旧 `project.json`，旧 dialogue/narration 自动迁移
- 输入漫画主题、视觉风格和分镜数量；也可以在第一次生成前直接粘贴已有故事、梗概或剧本
- 在 UI 中选择文本 Provider、检测可用状态
- 文本 Provider 和图片 Provider 独立选择，互不绑定
- `MockTextModel`：完全离线、始终可用
- `OllamaTextModel`：通过本地 Ollama HTTP API 调用模型
- `OpenAICompatibleTextModel`：通用 Chat Completions API，不绑定具体平台
- 统一生成标题、故事梗概、任意角色列表和任意分镜列表
- 每格包含场景、画面描述、角色、动作、对白、旁白和 `image_prompt`
- 自动提取 Markdown 代码块中的 JSON，并使用 Pydantic 校验
- JSON 失败时进行有限修复重试
- 真实模型失败时可显式回退到 Mock
- `MockImageModel`：完全离线的 Pillow 分镜占位图
- 统一 `ImageProvider` 2.0：请求、结果、能力、异常、注册表和回退链完全解耦
- P0 图片 Provider：Mock、OpenAI Images、Recraft、Together、SiliconFlow、fal、ComfyUI
- OpenAI Images 支持生成、编辑、多参考图和 Mask；fal/ComfyUI 支持异步任务轮询
- URL/base64/平台特有响应统一归一化并通过 Pillow 验证
- 429、5xx、连接与超时支持指数退避；鉴权、余额和内容审核错误不重试
- 图片专业设置按 Provider 能力动态显示；普通用户无需填写尺寸、Seed 或底层格式
- 最终漫画支持 PNG、PDF 和可继续编辑的 project.json 导出
- 远程图片下载/解码后保存为本地 `panel_01.png` 等文件
- 单格图片失败时可只回退该格，严格模式可禁止回退
- 本地叠加短尾自然气泡、无框旁白和漫画音效字，按所选页面形式导出最终 PNG
- 保存不含凭据的 `project.json`，记录图片来源、耗时和回退状态
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
│   │   ├── image_base.py
│   │   ├── image_registry.py
│   │   ├── parsing.py
│   │   ├── registry.py
│   │   ├── mock_text.py
│   │   ├── ollama_text.py
│   │   ├── openai_compatible_image.py
│   │   ├── openai_compatible_text.py
│   │   └── mock_image.py
│   ├── prompts/
│   │   ├── comic_generation.py
│   │   └── image_generation.py
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
Mock / Ollama / OpenAI-compatible Text Provider
    │ 统一返回经过校验的 ComicProject
    ▼
ImageProviderRegistry → Mock / OpenAI / Recraft / Together / SiliconFlow / fal / ComfyUI
    │ 每格返回经过验证并保存到本地的图片
    ▼
本地对白与旁白 → compose_comic → PNG + project.json
```

Provider 不依赖 Gradio；UI 和业务层不包含 Ollama、API 地址判断或 HTTP 请求。文本和图片 Provider 分别注册、分别选择，因此文本使用 Ollama 时图片不会被错误地交给 Ollama。提示词位于独立的 `prompts/` 模块，图片 Provider 每次只接收当前分格的视觉提示词，不接收整段漫画 JSON。

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

访问 <http://127.0.0.1:7860>。每次生成会在 `outputs/时间戳_主题/` 中保存：

新版界面使用高对比的轻科技/果冻玻璃主题。左侧“创作控制台”只保留基础创意、页面布局、
文本模型、图片与排字设置；右侧按“开始创作 → 当前状态 → 漫画画布 → 后续编辑”组织，首次
使用时可直接跟随三步提示。漫画画布独立于浏览器页面缩放：“整页预览”会在固定视口内总览
整页，“放大阅读”会让漫画铺满画布宽度并在画布内部上下滚动，全屏按钮用于细节检查；这些预览方式
不会改变最终 PNG 分辨率。右侧顶部选择“先检查分镜”或“一键自动生成”后只显示对应主操作。
漫画预览下方使用常驻标签页组织分镜编辑与故事修订、成品语言、导出与项目，
避免把关键功能藏在多层折叠栏中。自定义画框只在手动检查模式且选择自定义布局时出现，
不会与普通页面模式同时生效。分镜数量是故事和布局共同使用的唯一数量来源：自定义布局会按
该数量初始化画框，禁止额外增加画框；删除后必须补足才能生成，修改分镜数量会重新初始化
同等数量的默认画框。

```text
panel_01.png
panel_02.png
...
comic.png
comic.pdf
project.json
```

如果没有任何真实模型配置，文本选择“Mock 文本模型（离线）”、图片选择“Mock Image（Pillow 占位图）”即可完成全部演示。

检查模式先点击“生成故事与可编辑分镜”；确认并可编辑画面描述、对白和旁白后，再点击
“使用当前分镜生成漫画图片”。一键模式则连续完成故事、图片和排版。成品生成后可在
“切换成品语言”标签页复用现有图片，只重新翻译和排版标题、对白与旁白。“项目文件与导出”
先提供 `project.json` 载入入口以恢复旧项目，再提供 PNG 和项目 JSON 下载，分别用于分享成品和
以后继续编辑。

如果已有完整故事，不需要先让模型自由创作：在“已有故事或剧本（可选）”中直接粘贴原文，
模型会把它作为最高优先级内容依据设计第一版分镜，并将原文保存到 `project.json`。如果首版仍不
符合预期，不必在逐格表格里重新讲完整故事；可在“故事不符合预期？补充事实并重做分镜”中，
用自然语言说明正确事件、人物关系、必须保留和禁止加入的内容，再点击“基于当前版本继续修正
完整分镜”。每次提交都会以最新版本为基础，累积保留
此前约束和修订历史；该步骤仍只调用文本模型，不消耗图片 Units。逐格表格继续用于最后的
画面、对白和旁白微调，最终标题也可直接编辑。

“漫画页面形式”可选择传统自由页、竖向条漫或兼容旧版的规则网格。开启“必要时允许单格
包含插入特写/分割镜头”后，文本模型可为确有需要的故事节点规划 `inset`、横/纵分割或
montage；图像 Provider 仍只收到一次该格请求，因此实际遵循程度取决于模型能力。

四格传统页面使用等宽等高 2×2，生成图会轻微居中裁切后铺满格框，不再因 importance
改变左右格宽，也不再使用模糊背景补齐比例。图片提示词会为每格重复完全相同的项目级
风格锚点、调色板、线条和自然肤色约束。由于 Recraft 仍是四次独立随机采样且不支持 Seed/
参考图，此方式只能提高一致性，不能替代支持角色参考图的图像 Provider。

需要大小格混排时，将“漫画页面形式”改为“用户自定义画框”，展开“自定义画框设计器”：

1. 选择下一个画框类型；未选择已有画框时会追加到末尾，点击表格中的任意画框后则在其后插入。
2. 点击任意画框后可直接删除该格，不需要从末尾逐格删除；方形和竖幅属于半行画框，必须同类成对，横向通栏和超宽通栏各占一整行。
3. 画框数量会同步到分镜数量。布局完整后再生成并审查分镜，确认后才调用图片 Provider。
4. 自定义模式优先按每格画幅直接生图：任意尺寸 Provider 使用 `1:1/3:4/16:9/2:1`；
   只有 Provider 不支持目标比例时才选择最接近比例并少量 cover 裁切。Recraft 原生支持
   `1:1/3:4/3:2`，不支持 `16:9/2:1`，因此两类宽幅会请求 `3:2`。界面会显示每格实际请求画幅。

自动直出模式始终使用现有安全自动排版；即使下拉框暂时停留在自定义画框，也不会采用
未经人工确认的自定义布局。自定义布局会保存到 `project.json`，重新载入后可继续使用。

完成图片生成后，可打开“切换成品语言”。模型翻译会同时参考故事梗概、人物性格、说话人和
每格场景/动作，并以漫画本地化方式保持专名、因果和语气一致。翻译后仍可在分镜表格人工润色，
再选择“使用我在分镜表格中填写的译文”重新排版。该流程读取同一输出目录中的原始 `panel_*.png`，
只用 Pillow 重绘标题和漫画文字，不调用 Recraft 等图片 Provider。目标语言版本输出为
`comic_en.png`、`comic_ja_JP.png` 或 `comic_zh_CN.png`，译文保存在对应 project JSON 中。

完全离线检查气泡和三种语言：

```powershell
.\.venv\Scripts\python.exe scripts\preview_bubbles.py
```

“文字与气泡设置”默认选择“沉浸式漫画排字”：对白使用自然气泡，旁白融入画面，
拟声词使用无框漫画字。也可切换到经典兼容样式或全无框极简样式。左上角分格编号默认
关闭，只在需要调试分镜顺序时手动开启。

完全离线生成四种页面形式预览（包含“四方格＋两超宽幅”自定义长页）：

```powershell
.\.venv\Scripts\python.exe scripts\preview_layout_modes.py
```

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
$env:OLLAMA_NUM_PREDICT="4096"
$env:OLLAMA_NUM_CTX="8192"
.\.venv\Scripts\python.exe app.py
```

`OLLAMA_NUM_PREDICT` 控制一次结构化方案允许生成的最大 token 数，`OLLAMA_NUM_CTX`
控制输入与输出共享的上下文窗口。系统默认使用经 qwen3:4b 四格流程实测的 4096/8192，
避免普通生成因过大的输出预算和上下文非线性变慢。若 Ollama 明确返回长度截断，系统会从
干净上下文自动重做一次，并仅对该次请求临时提高到最多 8192/16384；不会续写残缺 JSON。
如果扩大预算后仍然截断，界面才会提示在显存允许的前提下提高环境变量或缩短故事说明。

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

配置项名称也列在 `.env.example` 中。`.env` 已被 `.gitignore` 忽略；`app.py` 会在创建 Provider 前加载本机 `.env`，且不会覆盖已经存在的进程环境变量。

## 配置真实图片 Provider

完整能力矩阵、每个平台环境变量、官方申请入口和严格单图验收命令见
[`docs/IMAGE_PROVIDER_GUIDE.md`](docs/IMAGE_PROVIDER_GUIDE.md)。以下是 OpenAI
Images 的最小示例；其他平台使用各自独立的 Key，不再共用一个通用变量。

OpenAI Provider 调用 `/v1/images/generations`，编辑时调用 `/v1/images/edits`。
`OPENAI_IMAGE_BASE_URL` 可以填写服务根地址、以 `/v1` 结尾的地址，或完整生成端点。

在被 Git 忽略的本机 `.env` 中填写：

```dotenv
IMAGE_MODEL_CONNECT_TIMEOUT=10
IMAGE_MODEL_GENERATION_TIMEOUT=300
IMAGE_MODEL_MAX_RETRIES=1
IMAGE_PANEL_CONCURRENCY=1
IMAGE_MODEL_FALLBACK_TO_MOCK=true

OPENAI_IMAGE_BASE_URL=https://你的图片服务地址
OPENAI_IMAGE_API_KEY=在本机填写
OPENAI_IMAGE_MODEL=你的图片模型名称
OPENAI_IMAGE_SIZE=1024x1024
```

兼容以下两种响应：

- `data[0].url`：程序下载图片到当前项目目录。
- `data[0].b64_json`：程序解码并保存为 PNG。

远程内容必须经过 Pillow 验证并落盘后才能进入排版，不会只在项目中保存远程 URL。API Key 不会显示在 UI、日志或 `project.json` 中。

### 严格验收与回退链

如果需要确认所有图片确实来自真实 Provider，将下面配置设为 `false`：

```dotenv
IMAGE_MODEL_FALLBACK_TO_MOCK=false
```

此时任何一格调用失败都会向前端返回明确错误，不会生成 Mock 图片伪装成功。启用回退时，仅失败分格使用 Mock，其余成功分格仍保留真实图片。
也可使用 `IMAGE_PROVIDER_FALLBACK_CHAIN=together,siliconflow` 配置真实次级
Provider；实际顺序为主 Provider → 次级链 → Mock。页面勾选“严格验收模式”时，
所有回退都会被禁止。

### 如何确认图片来自真实 Provider

1. 在页面中分别选择文本 Provider 和“OpenAI-compatible Image API”。
2. 图片状态应显示“已配置”、实际模型和 `remote_http`。
3. 生成完成后查看“实际图片 Provider”“实际图片模型”和“发生回退的分格”。
4. 确认状态显示未发生图片 Mock 回退。
5. 打开输出目录中的 `project.json`，检查每格的 `provider_id`、`model_name`、`local_path` 和 `fallback_used`。
6. 严格验收时同时设置 `IMAGE_MODEL_FALLBACK_TO_MOCK=false`。

## 回退与重试配置

```text
TEXT_MODEL_CONNECT_TIMEOUT=10
TEXT_MODEL_GENERATION_TIMEOUT=300
TEXT_MODEL_STATUS_TIMEOUT=10
TEXT_MODEL_MAX_RETRIES=1
TEXT_MODEL_FALLBACK_TO_MOCK=true
IMAGE_MODEL_FALLBACK_TO_MOCK=true
```

- `TEXT_MODEL_CONNECT_TIMEOUT` 只限制建立连接；默认 10 秒。
- `TEXT_MODEL_GENERATION_TIMEOUT` 限制等待模型生成和读取响应；默认 300 秒。
- Ollama 可使用 `OLLAMA_CONNECT_TIMEOUT`、`OLLAMA_GENERATION_TIMEOUT` 单独覆盖。
- `TEXT_MODEL_MAX_RETRIES=1` 表示第一次 JSON 校验失败后，最多请求一次完整 JSON 修复。
- `TEXT_MODEL_FALLBACK_TO_MOCK=true` 表示真实 Provider 最终失败后继续生成 Mock 方案。
- 回退不是静默行为；UI 会显示请求 Provider、失败原因、实际 Provider 和实际模型。
- 图片回退以单格为单位，UI 和 `project.json` 会列出具体分格与原因。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试使用注入的 Mock HTTP transport、下载函数和内存 PNG，不会访问 Ollama、图片服务、互联网或真实 API，也不需要真实凭据。

## 当前限制

- P0 图片协议和自动化 Mock HTTP 已完成；真实付费 API 仍需用户本机 Key 验收。
- `qwen3:4b` 只负责文本方案，图片必须由独立图片 Provider 生成。
- 真实 Provider 的最终效果依赖具体模型对中文指令和严格 JSON 的遵循能力。
- UI 暂定允许 1–20 格以防误操作；底层 Pydantic 模型和业务层没有写死四格、八格或 20 格上限。
- 多页数据结构已经预留，当前排版仍把所有分镜合成为一张双列长图。
- 项目会保存 `project.json`，但尚未支持重新加载、可视化编辑和单格重新生成。

## 下一阶段

- 使用用户选定的真实 Images API 做本机验收。
- 增加项目重新加载、分镜编辑和单格重新生成。
- 改进角色一致性、风格一致性和可配置漫画版式。
- Gemini、DashScope、Volcengine、Replicate 和 xAI 为 P1，尚未注册；详细验收边界见 `TASKS.md`。
