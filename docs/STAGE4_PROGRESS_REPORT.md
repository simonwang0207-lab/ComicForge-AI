# ComicForge AI 第三阶段及后续改进进度报告

> 归档日期：2026-08-06  
> 本文以当前工作区代码、测试、既有阶段记录和 `outputs/` 中的项目记录为依据。文中的“已实现”“已注册”“已配置”“连通/鉴权验证”和“真实生成验收”是不同状态。

## 1. 阶段背景和目标

第三阶段开始时，项目已经具备 Python `src/` 工程、Pydantic 漫画数据模型、Mock 完整闭环，以及 Ollama/OpenAI-compatible 文本 Provider 的统一接口。真实图片能力、付费前剧本确认、图片错误分级、真实输出溯源和漫画质量控制仍不完整。

本阶段的核心目标是把项目从“可演示的 Mock 原型”推进到“文本和图片 Provider 可独立替换、真实图片能够落盘并排版、失败原因可追踪”的集成平台。相比前一阶段，新增目标包括：统一图片 Provider 2.0、Recraft/ComfyUI 真实链路、剧本审查与修订、付费生图前确认、参考图与角色一致性探索、单格重生成和回退、PNG/PDF 导出以及更完整的前端任务流。

## 2. 本阶段完成的功能

### 2.1 文本模型 Provider

- `MockTextModel`、`OllamaTextModel`、`OpenAICompatibleTextModel` 均实现 `TextModelProvider` 并由 `TextModelRegistry` 注册。
- 文本创作模型与剧本审查模型可以独立选择；审查稿经过归一化、修复和 Pydantic 校验后才会应用。
- 支持 Markdown JSON 代码块提取、字段别名归一化、一次干净修复重试、截断识别、Qwen3 `think=false` 与 `/no_think` 兼容。
- `script_reviewed` 表示审查流程状态；`review_applied` 表示修订稿是否实际应用。审查失败时保留已经通过校验的真实初稿，不冒充审查成功。

### 2.2 图片模型 Provider

- 统一 `ImageProvider`、`ImageGenerationRequest`、`ImageGenerationResult`、`ImageProviderCapabilities` 和错误类型。
- 已实现并注册 Mock、OpenAI Images、Recraft、Together、SiliconFlow、fal、ComfyUI。
- Provider 负责协议、鉴权、网络、响应归一化；UI 只读取注册表、模型定义和能力，不包含平台专用请求代码。
- URL/base64 图片在本地保存前经过大小、Content-Type 和 Pillow 解码校验；项目记录不保存凭据或完整 base64。
- 429、5xx、连接和超时类错误可做有上限的退避重试；配置、鉴权、余额、内容策略等错误分类展示。

### 2.3 真实图片闭环与 ComfyUI

- Recraft 已有多次手动真实生成记录；当前工作区保存有四格无 Mock 回退项目。
- ComfyUI Provider 实现 `/system_stats` 健康检查、`POST /prompt`、`/history/{prompt_id}` 轮询、`/view` 下载，以及可选 `/upload/image` 参考图上传。
- 加载 API Workflow JSON 的副本，动态替换 prompt、negative prompt、width、height、seed 和参考图节点，不修改源工作流。
- 已用本地 SD1.5 checkpoint 与 API Workflow 完成 512×512 严格单图 smoke test；后续又形成无回退的多格项目记录。当前主工作流为 Animagine XL + IPAdapter，使用前仍要求本机安装对应 checkpoint、IPAdapter 和 CLIP Vision。

### 2.4 前端、测试与工程化

- 文本生成/审查与真实图片生成分为两个阶段，也提供一键自动模式。
- 支持任意正整数格数、传统页/网格/竖向条漫/自定义画框、结构化对白/旁白/思想/拟声词、本地气泡排字、PNG/PDF 导出。
- 支持项目 JSON 载入、分镜编辑、故事重做、成品语言切换、单格重生成、历史图片归档和回退。
- 全屏预览支持滚轮缩放、按住左键拖动和双击复位。
- `scripts/smoke_test_image_provider.py` 提供严格单图验收；自动化测试使用假 HTTP transport 和内存图片，不产生外部费用。
- `.env.example`、README、阶段报告和工作流文件已纳入工程说明；真实 `.env`、模型权重和 `outputs/` 不提交。

## 3. 关键问题、原因和解决方案

| 问题 | 问题表现 | 根本原因 | 排查过程 | 最终解决方法 | 后续预防措施 |
|---|---|---|---|---|---|
| SiliconFlow 站点地址 | 请求返回非预期错误或无法鉴权 | 中国站与国际站 API 域名/账户体系不同 | 分别核对 endpoint、`GET /v1/models` 和状态码 | 使用与 Key 所属站点一致的 base URL；当前国际站 Key 鉴权成功 | 配置时记录站点，不混用 Key 和域名 |
| API Key 鉴权失败 | 401/403 | Key 无效、站点错误或环境变量未生效 | 只做安全状态检查，不打印 Key | 修正本地 `.env` 并重启进程 | `.env.example` 只留空值；UI 显示配置状态 |
| SiliconFlow 余额为 0 | 鉴权和模型列表正常，收费生图不能验收 | 账户无可用余额 | `GET /v1/models` 返回 200，目标模型存在；生成前核对余额 | 不继续产生收费请求，明确标记“未真实生成验收” | 验收矩阵分开记录鉴权与真实生成 |
| 模型列表与目标模型 | 服务可连但指定模型可能不存在 | Provider 可用不等于模型名有效 | 调用模型列表并查找 `Tongyi-MAI/Z-Image-Turbo` | 已确认该模型存在 | 每次更换模型先做列表/状态验证 |
| ComfyUI 初次启动 | 连接失败、节点报错或模型加载失败 | 服务未启动、checkpoint/自定义节点/工作流缺失 | 依次检查 8188、`/system_stats`、节点和模型文件 | 启动本地服务并安装匹配依赖 | 录制前健康检查；模型权重不放入仓库 |
| Workflow JSON 类型 | 网页能打开工作流，但 API 提交失败 | 普通 UI Workflow 与 API Format JSON 结构不同 | 对照节点 `class_type` 和 `inputs` | 从 ComfyUI 导出 API Format 文件 | 新工作流先离线解析，再严格 smoke test |
| ComfyUI 节点 ID | prompt/尺寸/seed 没有生效 | 节点 ID 配错或工作流变更 | 检查 JSON 中节点类型与连线，不依据画布位置猜测 | 用环境变量指定节点；部分节点支持自动检测 | 每个工作流记录节点表和版本 |
| checkpoint 安装与加载 | `CheckpointLoaderSimple` 报缺失 | JSON 引用的模型未安装或名称不同 | 查看工作流节点和 ComfyUI 模型目录 | 安装本地 SD1.5 checkpoint并使用匹配工作流 | 提供可迁移配置，不提交大权重 |
| ComfyUI 严格 smoke test | 普通流程可能因 Mock 回退看似成功 | 回退会掩盖真实 Provider 失败 | 用单图脚本检查输出、尺寸、耗时、request ID 和 fallback | 严格模式无回退完成 512×512 本地生成 | Provider 改动后先单图再多格 |
| Ollama 截断与 JSON 不完整 | 缺字段、JSON 尾部中断、反复修复失败 | 小模型输出预算不足或结构服从性不稳 | 检查 `done_reason=length`、原始结构和校验错误 | 增加 token/context 配置、明确 schema、有限归一化和一次干净修复 | Mock 验证文本组合；真实小模型保留显式失败 |
| Codex 会话异常 | 网络中断、模型不可用、`thread not found` | 开发工具或会话状态异常，不是项目运行错误 | 重新读取 AGENTS/TASKS/README/git diff 和交接记录 | 使用阶段报告与 handoff 恢复上下文 | 记录只增补；关键验证写入文档和项目 JSON |
| Ruff、pytest 与真实验收 | 静态/自动测试通过但真实平台仍失败 | 检查对象不同 | 分别运行 Ruff、pytest、smoke test 和手动 UI | 建立分层验收矩阵 | 禁止用自动化测试替代真实 API 结论 |

## 4. Provider 当前验收矩阵

“已配置”指当前项目有安全配置入口，或已有本机使用记录；它不代表其他电脑无需重新配置。

### 4.1 文本 Provider

| Provider | 已实现 | 已注册 | 已配置/可用记录 | 连通或鉴权 | 真实生成 | Demo 建议 | 当前限制 |
|---|---:|---:|---|---|---|---|---|
| Mock | 是 | 是 | 默认可用 | 不需要网络 | 是（确定性离线） | 最稳定备用 | 不是大模型真实内容 |
| Ollama | 是 | 是 | 本机 `qwen3:4b` 有记录 | 本地状态验证完成 | 已完成真实文本生成 | 可作本地 Demo | 小模型 JSON/长输出稳定性有限；与 ComfyUI 可能争显存 |
| OpenAI Compatible | 是 | 是 | 当前输出记录显示 `qwen3:4b` | 已有实际调用记录 | 已生成并成功应用审查的项目 | 可用，但依赖后端稳定性 | 不同兼容服务响应格式和 token 上限不同 |

### 4.2 图片 Provider

| Provider | 已实现 | 已注册 | 已配置 | 网络/鉴权验证 | 真实生成 | Demo 建议 | 当前限制 |
|---|---:|---:|---|---|---|---|---|
| Mock | 是 | 是 | 默认可用 | 不需要 | 是（离线占位图） | 文本链路和备用演示 | 不代表真实生图质量 |
| Recraft | 是 | 是 | 本机已有配置/记录 | 是 | **是，多次手测；四格无回退记录** | 当前云端主 Demo | 收费、依赖网络；不支持 seed；跨格角色仍可能漂移 |
| SiliconFlow | 是 | 是 | 曾配置国际站 Key | **鉴权成功；`GET /v1/models` 200；目标模型存在** | **否，余额为 0** | 只展示接入与状态，不现场收费生成 | 未完成真实收费生图验收 |
| OpenAI Images | 是 | 是 | 当前无配置证据 | 未验收 | 未验收 | 不建议现场使用 | 需用户 Key、模型和真实费用验收 |
| Together | 是 | 是 | 当前无配置证据 | 未验收 | 未验收 | 不建议现场使用 | 仅代码适配和离线协议测试 |
| fal | 是 | 是 | 当前无配置证据 | 未验收 | 未验收 | 不建议现场使用 | 仅代码适配和离线队列测试 |
| ComfyUI | 是 | 是 | 本机 8188 + workflow 有使用记录 | 本地健康/工作流验证完成 | **是；SD1.5 512×512 严格单图及后续无回退项目** | 当前本地备用/演示路线 | 依赖本机模型、自定义节点、显存；多格可能超时 |

## 5. 测试和验收证据

| 层级 | 检查内容 | 是否外部付费 | 当前证据 |
|---|---|---:|---|
| Ruff | Python 静态质量 | 否 | 本次发现 3 项现有源码问题，未通过；详见下方记录 |
| pytest | schema、解析、Provider 协议、回退、布局、UI 回调 | 否 | 本次追加内容语言校验后 `207 passed`，10 条 Gradio 弃用警告 |
| compile/import | 语法和应用构建 | 否 | 本次 `compileall` 与 `import app; assert app.demo` 通过 |
| Provider smoke | 单图、严格无 fallback、输出可解码 | ComfyUI 否；云端可能收费 | `outputs/provider_smoke/` 保存图片；ComfyUI 有 512×512 记录 |
| 手动前端 | 两阶段流程、状态、预览、导出、回退 | 取决于选择 | `outputs/` 中保存真实项目与成品 |
| 真实平台 | 网络、鉴权、模型、真实响应 | 可能 | Recraft、ComfyUI 已完成；SiliconFlow 仅鉴权/模型列表 |

可复核的当前工作区证据：

- `outputs/20260805_220329_304300_哪吒/project.json`：ComfyUI，两格记录，约 29.40s/28.15s，request ID 分别为 `1a90c651-...`、`28f00801-...`，无回退。
- `outputs/20260805_224941_915906_哪吒/project.json`：Recraft 四格，单格约 16.13–23.84s，无回退；另有第 4 格历史版本记录。
- `outputs/provider_smoke/20260804_125634.png`：本地 ComfyUI 严格 smoke 输出记录。项目文件中的 `request_id` 是否为空取决于平台响应，空值不能被虚构。

自动化测试证明代码行为；真实平台验收还必须同时满足真实服务、真实模型、无回退和有效图片落盘，两者不可互相替代。

本次归档执行的免费检查结果：

```text
pytest：207 passed，10 warnings
compileall：通过
应用导入：app_import_ok
git diff --check：通过（仅有 LF/CRLF 提示）
Ruff：未通过，3 项现有源码问题
  - service.py:877 未使用的 output_path
  - service.py:939 datetime.now() 未显式传入时区
  - ui.py:1514 集合内未加括号的隐式字符串拼接
```

这 3 项不影响本次 pytest、编译和应用导入，但说明“历史阶段 Ruff 通过”不能作为当前工作树的结论。本轮任务以文档归档为主，没有借机改动业务代码；应列入后续代码整理。

归档后针对真实 Demo 暴露的审查耗时又完成一项改进：审查请求不再重复发送完整项目中的
长 `image_prompt`、图片记录和纯视觉布局字段，而只发送事实、故事、角色、分镜动作与文字的
紧凑快照；Ollama 和 OpenAI-compatible 审查使用独立的
`TEXT_MODEL_REVIEW_TIMEOUT`（默认 90 秒），不再复用普通生成的 300 秒上限。审查超时仍会
保留已经通过校验的真实初稿，但最多只占用独立审查预算。

## 6. 当前最终效果

当前可完成：故事/自然语言输入 → 结构化故事、角色、Story Bible 和任意格数分镜 → 独立审查与修订 → 用户编辑确认 → 逐格真实或 Mock 生图 → 本地气泡排字和页面组合 → 全屏预览 → PNG/PDF/JSON 输出。文本模型和图片模型可独立切换；界面及项目记录展示请求/实际 Provider、模型、耗时、request ID、seed、尺寸、错误和 fallback。

## 7. 当前仍存在的问题

- 独立采样的图片模型仍不能彻底保证跨格角色一致性；IPAdapter 只是改善手段。
- 多格 ComfyUI 生成受显存、队列和 300 秒轮询上限影响，耗时可能明显增长。
- Recraft 等云端 API 有网络、额度和成本约束。
- 本地 checkpoint 的画质、语义理解与硬件显存存在上限。
- Ollama `qwen3:4b` 等小模型的长 JSON 和审查修订仍可能不稳定。
- OpenAI Images、Together、fal 只完成代码适配和离线测试；SiliconFlow 尚未真实收费生成。
- `ComicPage/page_number` 和页面布局已有数据结构，但尚无“多页创作、逐页编辑、整册导出”的完整 UI 验收，因此不能称为多页完整可用。
- 当前仅本机 Gradio 运行；没有公网部署或多人在线服务证据。
- 手动气泡拖拽尚未实现；当前是自动定位和表格位置覆盖。

## 8. 下一阶段建议

### P0：演示稳定性

- 固化 Recraft 四格和 ComfyUI 单图/四格验收清单，增加失败分格续跑与成功图片复用。
- 在 UI 中提供明确的单图连通性测试、队列进度和当前分格状态，避免长时间只显示 processing。
- 继续加强文本审查响应归一化，但保持首次生成的必填字段边界和失败可见性。

### P1：质量与可编辑性

- 多角色参考图、区域条件或角色 LoRA 工作流；增加可量化角色一致性对比。
- 实现气泡拖拽、主体/人脸避让和更细粒度的文字样式控制。
- 完成多页 UI、逐页重生成与整册 PDF 验收。

### P2：部署与生态

- 在获得凭据和预算后分别验收 OpenAI Images、Together、fal、SiliconFlow 真实生成。
- 增加任务队列、用户隔离、远程对象存储和受控公网部署。
- 扩展新的文本/图片 Provider，但每个都沿用“实现→注册→配置→连通→真实生成”的验收层级。
