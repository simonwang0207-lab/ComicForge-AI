# ComicForge AI Codex 会话交接说明（2026-08-04）

> 用途：将当前项目状态、尚未提交的本地工作、真实验证结果、已知问题、用户要求和
> 推荐继续顺序完整交给下一个 Codex 会话。
>
> 本文反映的是 **2026-08-04 当前工作区**，不是只反映 GitHub 上已经提交的版本。

## 1. 首要安全规则

下一会话开始后，应先完整阅读仓库根目录的 `AGENTS.md`，并遵守以下约束：

1. 项目目录为 `F:\ZJU_intership\task\2\ComicForge-AI`。
2. 当前工作区存在大量有价值的未提交修改，禁止使用 `git reset --hard`、
   `git checkout --` 或其他会覆盖工作区的命令。
3. 不要删除、重建或覆盖现有 `workflows/`、源码、测试、报告及用户生成结果。
4. 不要读取、打印、复制或提交 `.env` 和任何真实 API Key。
5. 不要在自动测试中调用真实 Ollama、ComfyUI 或付费 API。
6. 未经用户明确要求，不执行 `git commit` 或 `git push`。
7. 修改应逐步进行，每一步都要保留现有 Mock、Ollama、Recraft、ComfyUI、排版、
   翻译和导出功能。
8. 用户非常在意响应速度和过程透明度。执行较长任务时应先简短说明正在做什么，
   不要长时间无反馈。

## 2. Git 与仓库状态

### 2.1 仓库信息

- 当前分支：`main`
- 远程：`origin https://github.com/simonwang0207-lab/ComicForge-AI.git`
- GitHub 仓库：<https://github.com/simonwang0207-lab/ComicForge-AI>
- 当前 HEAD：`2c8c3437ee65ef1cbf4771f35bbd792bdc232dca`
- 当前 HEAD 提交：`feat: complete stage 3 comic quality workflow`
- 远程 `origin/main` 与当前 HEAD 一致。
- 当前未提交工作位于上述提交之后，尚未推送到 GitHub。

最近三次提交：

```text
2c8c343 feat: complete stage 3 comic quality workflow
b535d89 feat: integrate and validate Ollama text provider
cada0b4 feat: complete mock comic demo
```

### 2.2 当前工作区规模

审计时 `git diff --stat` 显示：

```text
31 个已跟踪文件有修改
约 2732 行新增、163 行删除
workflows/ 目录包含 3 个未跟踪 JSON 工作流
```

当前已修改文件：

```text
.env.example
README.md
TASKS.md
src/comicforge_ai/layout.py
src/comicforge_ai/models/base.py
src/comicforge_ai/models/comfyui_image.py
src/comicforge_ai/models/image_base.py
src/comicforge_ai/models/image_registry.py
src/comicforge_ai/models/mock_text.py
src/comicforge_ai/models/ollama_text.py
src/comicforge_ai/models/openai_compatible_text.py
src/comicforge_ai/models/parsing.py
src/comicforge_ai/models/recraft_image.py
src/comicforge_ai/models/registry.py
src/comicforge_ai/prompts/__init__.py
src/comicforge_ai/prompts/comic_generation.py
src/comicforge_ai/prompts/image_generation.py
src/comicforge_ai/schemas.py
src/comicforge_ai/service.py
src/comicforge_ai/ui.py
tests/test_custom_layout.py
tests/test_image_prompts.py
tests/test_image_provider_v2.py
tests/test_image_service.py
tests/test_layout.py
tests/test_mock_text.py
tests/test_parsing.py
tests/test_script_review.py
tests/test_text_providers.py
tests/test_two_stage_flow.py
tests/test_ui_workspace.py
```

当前未跟踪文件：

```text
workflows/comfyui_text2img_api.json
workflows/comfyui_text2img_sd15_backup.json
workflows/comfyui_text2img_without_ipadapter_backup.json
docs/CODEX_SESSION_HANDOFF_2026-08-04.md   # 本交接文档
```

三个工作流文件都很小，分别约 3.1 KB、1.8 KB 和 2.3 KB，不包含模型权重。
不得把 ComfyUI checkpoint、IPAdapter、CLIP Vision 或其他大型模型复制到本仓库。

## 3. 当前架构

项目仍为 Python 3.11 + Gradio 单体应用，没有前后端分离。

```text
app.py
└── src/comicforge_ai/ui.py                  Gradio 组件、回调与展示格式
    └── src/comicforge_ai/service.py         生成编排、回退、保存、翻译、排版
        ├── models/base.py                   统一文本 Provider 接口
        ├── models/registry.py               文本 Provider 注册表
        ├── models/image_base.py             统一图片 Provider、能力和异常
        ├── models/image_registry.py         图片 Provider 注册表
        ├── prompts/comic_generation.py      漫画文本与结构化 JSON 提示词
        ├── prompts/image_generation.py      按 Provider profile 构造生图提示词
        ├── bubble_renderer.py               本地气泡、旁白、拟声词排字
        ├── layout.py                        网格、条漫、传统页、自定义画框排版
        └── schemas.py                       所有跨层 Pydantic 数据结构
```

核心约束仍是：UI 不应写 Provider 请求逻辑；HTTP、鉴权、协议和 payload 必须留在
具体 Provider 模块；Provider 之间通过统一接口和 Pydantic 模型协作。

## 4. 当前可用功能

### 4.1 文本模型

已注册并使用统一 `TextModelProvider`：

- `MockTextModel`：离线、确定性、始终可用。
- `OllamaTextModel`：本地 `/api/chat`，支持状态检测、`think=false`、`/no_think`
  兼容回退、独立连接/生成超时、长度截断识别和一次结构修复。
- `OpenAICompatibleTextModel`：标准 `/models` 和 `/chat/completions`，支持 Qwen3
  关闭 thinking、`reasoning_effort` 可选配置、结构化输出修复和长度截断提示。

文本结果可生成并验证：标题候选、故事梗概、角色设定、Story Bible、任意数量分镜、
画面描述、动作、对白、旁白、图像提示词、分镜重要度、内部多镜头结构和文字锚点。

已经针对模型常见缺失字段进行了有限安全归一化/修复，例如：

- `sequence` 可从 `number` / `index` 兼容迁移；
- 对修订稿中缺失但可以从当前项目可靠继承的角色字段进行补齐；
- 对 `title`、`story`、`characters`、`panels`、`image_prompt` 等核心结构继续严格校验；
- 不使用 `eval`，只使用 JSON 和 Pydantic。

### 4.2 两种创作流程

1. **先看分镜**：只调用文本模型；用户可修改标题、逐格画面/对白/旁白，也可用自然
   语言连续重做完整故事。确认后才调用图片 Provider。
2. **一键生成**：文本方案和图片生成连续执行，适合用户明确接受直接消耗图片资源时使用。

可在第一次调用前粘贴完整故事或剧本；不必先让模型自由创作一个版本。
修订历史通过 `RevisionTurn` 和 `revision_history` 保存，可连续多轮修订。

### 4.3 图片 Provider 2.0

统一图片请求支持提示词、负面提示词、宽高、画幅、质量、数量、Seed、风格、格式、
参考图、Mask、强度、元数据和模型选择。统一结果保存 Provider、模型、operation、
request ID、Seed、耗时、实际参数、回退和安全错误信息。

当前注册的 P0 Provider：

- Mock Image
- OpenAI-compatible Images（generations / edits、URL / base64）
- Recraft
- Together
- SiliconFlow
- fal queue
- ComfyUI

错误类型、指数退避、最大轮询时间、URL 下载限制、Pillow 图片验证、严格模式、
主 Provider → 次级 Provider → Mock 的逐格回退链均已实现并有离线测试。

尚未实现/注册的 P1 Provider：Gemini、DashScope、Volcengine、Replicate、xAI。
其预期环境变量、协议和验收条件已写入 `TASKS.md`，不要在完成测试前放入前端选择器。

### 4.4 Recraft 的重要行为

- Recraft 能力声明仍正确地表示“不支持 Seed”。
- UI 的 Seed `0` / 空值会归一化成 `None`。
- 只有 Provider 明确支持 Seed 时，服务才生成基础 Seed 并按分格递增。
- Recraft 请求不会携带 Seed；支持 Seed 的 Provider 仍会收到逐格 Seed。
- 这是为了修复“单图 smoke test 成功，但完整四格在本地能力校验阶段全部失败”的问题。

### 4.5 ComfyUI + Animagine XL + IPAdapter

当前主工作流：`workflows/comfyui_text2img_api.json`。

工作流已知节点：

| 作用 | 节点 ID |
|---|---:|
| KSampler | `3` |
| Checkpoint loader | `4` |
| Empty latent / width / height | `5` |
| Positive prompt | `6` |
| Negative prompt | `7` |
| Save image | `9` |
| IPAdapter Unified Loader | `12` |
| IPAdapter Advanced | `13` |
| LoadImage reference | `14` |

`ComfyUIImageProvider` 当前具备：

- `/prompt` 提交；
- `/history/{prompt_id}` 轮询；
- `/view` 下载；
- 自动识别 KSampler 负面提示词所连接的 CLIP 节点；
- 自动识别 IPAdapter 所连接的 `LoadImage` 参考图节点；
- 参考图经 `/upload/image` 上传，并把返回文件名写入 workflow；
- 记录 `reference_count`、Seed、轮询次数和 request ID；
- 根据 checkpoint 名称自动选择 `animagine_xl` 提示词 profile；
- 根据目标画框比例选择适合 SDXL/Animagine 的安全尺寸；
- 没有上传参考图时，自动绕过 IPAdapter，把 KSampler 模型重新连接到基础 checkpoint，
  避免工作流里保存的示例猫图污染其他主题。

当前工作流需要用户本机 ComfyUI 已安装：

- `ComfyUI_IPAdapter_plus`；
- Animagine XL 4.0 checkpoint；
- 与 SDXL 匹配的 IPAdapter 权重；
- 与工作流匹配的 CLIP Vision 模型。

### 4.6 Provider 专用提示词隔离

`prompts/image_generation.py` 已建立 profile：

- `neutral`
- `rich_localized`
- `sd_comfyui`
- `animagine_xl`

Animagine 的英文 tag、质量词、风格映射、主体结构约束、单场景约束和负面提示只作用于
Animagine/ComfyUI profile，不会全局污染 Recraft。Recraft 继续使用适合远程丰富语义模型的
本地化提示词。用户明确要求不能把任何故事主体（例如“猫”）写死；当前实现使用通用
`CharacterProfile` 的实体类型、类别、身体结构、身份特征和禁用特征构造锚点。

### 4.7 漫画数据、排版和导出

当前 Pydantic 模型支持：

- 任意角色、任意分镜列表和预留的多页 `ComicPage`；
- `grid`、`webtoon`、`adaptive_page`、`custom_page`；
- 自定义 `square`、`portrait`、`landscape`、`wide` 画框；
- 单镜头、横/纵分割、inset、montage 和最多 3 个辅助镜头；
- 对白、思考、旁白和拟声词；
- 三种排字风格和多语言文字；
- PNG、PDF 和 `project.json`。

四格传统页默认使用等宽 2×2，不再用无必要的大小格和模糊边缘补白。自定义布局会按
各格目标比例请求图片；只有 Provider 不支持时才选最接近比例并有限裁切。

### 4.8 漫画文字与翻译

- 图片模型负责生成无文字画面；Pillow 在本地绘制漫画气泡、旁白和拟声词。
- 默认不显示左上角分格编号。
- 翻译会参考故事、人物、说话人、场景和动作，而不是只逐句直译。
- 已生成项目可使用原始 `panel_*.png` 重新排字成中文、英文或日文，不重新调用图片模型。
- 翻译后的本地化版本保存在 `localizations`，可重复切换。
- 对模型返回的翻译项数量不一致有结构校验和修复逻辑。

## 5. 已解决的重要问题及解决思路

更完整的时间线位于 `docs/STAGE3_COMIC_QUALITY_PROGRESS_REPORT.md`。以下为下一会话
最需要了解的工程原因：

### 5.1 Ollama 状态可用但生成超时

根因包括：状态请求和长生成共用短超时、Qwen3 thinking 增加耗时、本机 loopback 请求
误走系统代理，以及过大的默认上下文/输出预算。解决方法是：

- 分离连接、状态和生成超时；
- 生成默认 300 秒；
- Qwen3 请求顶层 `think=false`，旧接口使用 `/no_think`；
- localhost/loopback 不继承代理；
- 普通默认 `4096/8192`，确实截断时单次临时扩到 `8192/16384`；
- 区分连接、HTTP、模型不存在、截断和生成超时。

### 5.2 模型 JSON 缺字段或被截断

症状曾包括缺少 `characters/story/title/sequence/image_prompt`、非法 JSON、修订稿缺少角色
字段和翻译项数量不一致。解决方向：

- 独立严格 Schema 提示词；
- 从 Markdown 代码块提取 JSON；
- 低温度结构化生成；
- 不把残缺 JSON 反复塞回模型强化错误；
- 使用干净上下文做有限修复；
- 对可可靠推断的别名/继承字段归一化；
- 核心结构仍严格失败，不伪造真实成功；
- 长修订检测 `finish_reason/done_reason=length` 后用扩大预算重做一次。

### 5.3 Recraft 四格全部报 Seed 不支持

根因是 UI 默认 `0` 被当作明确 Seed，服务又无条件计算 `seed + panel_index`。现在 `0/空值`
表示自动，且只有支持 Seed 的 Provider 才会得到 Seed。

### 5.4 ComfyUI 输出像照片、人群、梦境或一张漫画页套在一格里

根因依次包括：使用不合适的 SD 1.5 checkpoint、中文/冗长提示不适合本地 diffusion、
把 `comic page / multiple panels` 等词写入单格提示、Animagine profile 不够隔离，以及角色
结构约束不足。已改为 Animagine XL 专用英文 tag profile、单场景负面约束、实体身份锚点、
风格映射和工作流专用尺寸。效果较旧 checkpoint 明显改善，但单靠 prompt 仍无法保证角色
跨格一致，因此加入了 IPAdapter 工作流。

### 5.5 一格出现独眼、眼球或怪物主体

根因并非固定为“猫”，而是 diffusion 在近景、夸张大眼、重复提示和身份约束弱时把局部
视觉特征重解释为主体。当前已增加通用实体类型、物种/类别、身体结构、身份特征和
`avoid_features`，并避免把主体写死。IPAdapter 是后续保持同一角色外观的更可靠手段，
但仍依赖合适参考图和匹配模型。

### 5.6 漫画左右大空白、模糊补边和错误大小格

根因是等比例图片被强制塞入不必要的异形画框，或用 contain + 模糊背景补边。现在普通
四格固定等宽 2×2，并按目标框比例直接请求图；自定义画幅才采用用户明确选择的大小格。

### 5.7 Recraft 连接超时

曾错误设置 `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:7890`，但本机该端口没有代理服务，
导致 Gradio 自身和 Recraft 都连接失败。若再次出现，应先检查代理是否真的监听，不要盲目
复制代理变量。分镜阶段不调用图片 Provider，所以“分镜成功、确认生图失败”并不矛盾。

## 6. 当前配置参考（不包含真实密钥）

真实值只放在被 Git 忽略的 `.env`。安全模板在 `.env.example`。

### 6.1 启动应用

```powershell
cd F:\ZJU_intership\task\2\ComicForge-AI
.\.venv\Scripts\python.exe app.py
```

默认地址：<http://127.0.0.1:7860>。

若 7860 被占用，应先关闭旧进程，或临时指定新端口：

```powershell
$env:COMICFORGE_SERVER_PORT="7861"
.\.venv\Scripts\python.exe app.py
```

### 6.2 Ollama 常用安全配置

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_CONNECT_TIMEOUT=10
OLLAMA_GENERATION_TIMEOUT=300
OLLAMA_NUM_PREDICT=4096
OLLAMA_NUM_CTX=8192
```

### 6.3 ComfyUI 当前工作流配置

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

后两个节点留空时自动检测。更换工作流后必须重新确认节点连接和 API 格式，不要只依据
ComfyUI 画布上的视觉位置猜节点 ID。

### 6.4 严格图片验收

```dotenv
IMAGE_MODEL_FALLBACK_TO_MOCK=false
IMAGE_PANEL_CONCURRENCY=1
```

严格模式可防止真实 Provider 失败后产生看似成功的占位漫画。ComfyUI + IPAdapter 调试阶段
建议并发数先保持 1，便于显存管理和错误定位。

## 7. 2026-08-04 最新自动验证结果

执行命令：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app.py src tests scripts
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
.\.venv\Scripts\python.exe -c "import app; assert app.demo; print('app_import_ok')"
```

结果：

- pytest：`162 passed`，`0 failed`，耗时约 `10.28s`；
- Ruff：通过；
- compileall：通过；
- pip check：`No broken requirements found`；
- `git diff --check`：通过；
- 应用导入：`app_import_ok`；
- 警告：4 条 Gradio 弃用警告，不影响当前运行；
- Git 另有 LF 将转为 CRLF 的提示，不是测试失败。

自动测试全部使用 Mock transport 和内存图片，没有调用真实外部服务。

本轮没有运行真实付费 API，也没有执行真实完整漫画生成。因此在提交这些未提交改动前，
仍建议用户用本机 ComfyUI 进行一次带参考图和一次不带参考图的端到端人工验收。

## 8. 当前前端实际状态

当前 `create_demo()` 仍使用：

- 左侧 `gr.Sidebar(width=420)`；
- 4 个向下展开的 Accordion：内容、页面、文本模型、图片与排字；
- 右侧开始创作区域、统一状态 Markdown、漫画预览；
- 右侧 Tabs：分镜与剧本、成品语言、项目与导出；
- 浅色统一主题；此前效果不佳的深浅色切换实验已移除；
- 预览模式为“整页预览 / 放大阅读”，并有全屏按钮；
- PNG、PDF 和 JSON 下载。

这套 UI 能工作且自动测试通过，但用户认为它仍然显得堆叠、廉价、功能发现困难。

## 9. 用户最新提出、但尚未实现的需求

以下内容只完成了分析和执行计划，**尚未修改代码**。下一会话不能误报为已完成。

### 9.1 只显示已配置 Provider

用户希望前端隐藏未配置的 Provider，配置后重启应用自动出现。

当前情况：

- `TextModelRegistry.choices()` 返回全部已注册文本 Provider；
- `ImageProviderRegistry.provider_choices()/choices()` 返回全部已注册图片 Provider；
- UI 直接使用这些方法，因此未配置项仍可见。

推荐做法：

1. 保留现有 `choices()` 语义，避免破坏测试和程序化注册表访问。
2. 新增 `configured_choices()` / `configured_provider_choices()` 专供 UI。
3. 图片使用 `validate_config().configured`，不要在启动时联网。
4. 文本 Provider 增加公开的配置状态方法；Ollama/OpenAI-compatible 可复用现有私有配置
   检查，Mock 始终显示。
5. 默认仍选 Mock，避免启动后自动选中付费 Provider 并意外消耗额度。
6. 为新行为补注册表和 UI 测试。

### 9.2 设置改为侧向抽屉，不再层层向下展开

用户希望：左侧只保留项目摘要和少量入口；点击“内容 / 页面 / 模型 / 排字”后在侧面打开
设置抽屉；完成设置后，必要信息以简短摘要留在侧栏。

推荐低风险结构：

- 左侧窄导航：项目摘要 + 4 个设置入口 + 当前主要动作；
- 中间设置抽屉：4 个 `gr.Group`，一次只显示一个；
- 右侧主工作区：创作、角色、项目三个页面或 Tabs；
- 复用现有组件变量和回调，仅改变容器与显隐，避免重写业务流程；
- 新增汇总函数，监听主题、风格、格数、布局、文本/图片 Provider，输出一张紧凑摘要卡。

### 9.3 按钮视觉层级

用户不希望所有按钮长得一样。应区分：

- 主动作：生成分镜 / 确认生成漫画；
- 次动作：检测模型 / 继续修订；
- 轻量操作：打开设置 / 查看详情；
- 危险操作：删除画框 / 删除角色资产。

建议使用 CSS class，而不是依赖全部 `variant="primary"`。

### 9.4 错误只在一个显眼区域显示

当前多个 helper 会 `raise gr.Error`，同时页面的 `generation_status` 也会显示状态，造成重复、
位置漂移或巨大红色错误框。

推荐做法：

1. 在主工作区顶部增加单一 `global_notice`。
2. UI 顶层 handler 捕获业务异常，返回不破坏现有状态的组件更新和一条友好通知。
3. 逐个迁移回调，避免一次性修改全部输出元组导致 Gradio arity 错误。
4. Provider/service 继续抛明确异常；只由 UI 最外层决定展示。
5. 为成功、提示、警告、错误定义统一样式。

### 9.5 无参考图时自动使用第一格主体

用户希望：如果没有主动上传角色参考图，先生成第一个出现主体的分格，再把该原始无字图片
作为后续分格参考。

当前并未实现。当前行为是：没有用户参考图时直接绕过 IPAdapter，所有分格仍独立生成。

推荐实现边界：

1. 仅对声明 `image_to_image=True` 的 Provider 启用。
2. 若用户已上传参考图，始终优先使用用户参考图。
3. 没有用户参考图时，先串行生成第一格原始图；将其路径加入后续请求的
   `reference_images`。
4. 后续分格仍可按配置并发，但调试初期建议并发 1。
5. 必须使用未绘制气泡的 `panel_XX.png`，不能使用已排字的 composition image。
6. 在 `project.json` 记录参考来源和实际使用分格，不保存 base64。
7. 若首格没有清晰主体，不应假装获得角色一致性；状态中显示“自动参考效果有限”。
8. 为无参考、用户参考、首格自动参考、首格失败、Provider 不支持参考图补离线测试。

### 9.6 多角色一致性的真实边界

当前工作流只有一个 IPAdapter `LoadImage` 输入，且 `ComfyUIImageProvider` 只上传
`reference_images[0]`。因此：

- 当前可以较好地约束一个主角或整体画风；
- 不等于支持多个角色分别保持身份；
- 如果一张参考图里有多个角色，模型可能混合身份、服装和特征；
- UI 目前允许多选文件，但 ComfyUI 当前实现实际只使用第一张，这是必须在后续 UI 中明确
  或改为单文件，不能误导用户。

真正的多角色一致性需要：

- 每个角色独立参考图；
- 分镜到角色参考图的映射；
- 支持多个 IPAdapter 或区域/Mask conditioning 的 ComfyUI workflow；
- 必要时 ControlNet、InstantID/FaceID 等与具体角色类型匹配的控制；
- 对动物、人物、机器人分别使用合适身份约束，不能只做人脸一致性。

### 9.7 可选角色形象库

用户希望保存角色名称、设定和图片，后续漫画可直接调用。当前尚未实现。

推荐最小可靠版本：

- 本地目录：例如 `data/character_library/`；
- `CharacterAsset`：ID、名称、实体类型、描述、标签/风格、参考图相对路径、创建时间；
- 元数据使用 JSON，图片复制到该目录；
- 将目录加入 `.gitignore`，避免个人角色图误提交；
- 新增独立“角色库”页面，不继续塞进图片高级设置；
- 支持保存、选择、查看、删除；删除必须二次确认或至少清晰标注；
- 初版一次只把一个选中角色传给当前单参考 IPAdapter；
- 多角色映射作为下一小阶段，不应在不支持时伪装完成。

## 10. 推荐下一会话执行顺序

用户明确要求“逐步完成，不要破坏主体功能”。建议按以下顺序，每步单独测试：

### 步骤 1：Provider 前端过滤

- 新增 config-only choices；
- UI 只显示已配置 Provider；
- 不修改旧注册表 choices 行为；
- 跑注册表与 UI 测试，再跑完整 pytest。

### 步骤 2：侧向设置抽屉与摘要

- 只移动容器和增加显隐回调；
- 保持所有现有组件变量、输入输出顺序和功能；
- 补 UI 结构测试；
- 人工打开页面检查布局。

### 步骤 3：统一错误通知和按钮层级

- 先迁移一个生成流程验证展示方式；
- 再逐个迁移其余 handler；
- 不在同一改动里混入 Provider 业务变化。

### 步骤 4：单主角“首格自动参考”

- 只对 ComfyUI/支持 image-to-image 的 Provider 启用；
- 用户参考图优先；
- 明确记录自动参考来源；
- 用 Mock HTTP 验证 `/upload/image` 与后续 workflow 节点替换；
- 完整流程失败时仍遵守严格模式和显式回退。

### 步骤 5：角色库最小版本

- 先完成本地存储、单角色选择和复用；
- 再设计多角色 workflow，不要一次完成所有高级能力。

## 11. 下一会话建议首先执行的命令

```powershell
cd F:\ZJU_intership\task\2\ComicForge-AI
Get-Content -Encoding UTF8 AGENTS.md
Get-Content -Encoding UTF8 docs\CODEX_SESSION_HANDOFF_2026-08-04.md
git status -sb
git diff --stat
git diff -- src/comicforge_ai/models/comfyui_image.py
git diff -- src/comicforge_ai/prompts/image_generation.py
git diff -- src/comicforge_ai/service.py
git diff -- src/comicforge_ai/ui.py
.\.venv\Scripts\python.exe -m pytest
```

PowerShell 查看中文文件时应显式指定 UTF-8，避免把正常中文误判为乱码：

```powershell
$OutputEncoding = [System.Text.Encoding]::UTF8
Get-Content -Encoding UTF8 <文件路径>
```

## 12. 提交前最终验收清单

在用户明确要求提交前，至少完成：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app.py src tests scripts
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git status -sb
```

并人工确认：

1. Mock 离线闭环仍可生成、预览、导出 PNG/PDF/JSON；
2. 先看分镜模式不会调用图片 Provider；
3. 一键生成与确认生成仍各自走正确流程；
4. Recraft 不携带 Seed；
5. ComfyUI 无参考图时不会使用 workflow 内示例图；
6. ComfyUI 用户参考图确实上传并替换 `LoadImage`；
7. 严格模式下真实 Provider 失败不会产生 Mock 成品；
8. 翻译重排不会再次调用图片 Provider；
9. 自定义画框数量与分镜数量保持一致；
10. `git diff` 中没有 `.env`、Key、输出图片、base64、大模型或无关文件。

## 13. 当前结论

项目当前不是“无法运行的半成品”：所有 162 项自动测试和静态/导入检查均通过，文本、
图片、排字、布局、翻译、导出以及 ComfyUI IPAdapter 接口都已有可运行骨架和离线覆盖。

但当前工作区也不是已完成并已上传的最终状态：大约 2700 行增强仍未提交；最新用户提出的
Provider 隐藏、侧向设置抽屉、单一错误区域、首格自动参考和角色库都尚未实现。下一会话的
首要任务应是保护当前工作区，从 Provider 过滤和 UI 信息架构开始逐步实现，而不是重写现有
生成闭环。
