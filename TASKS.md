# ComicForge AI 任务与验收状态

> 本文件只维护当前能力、验收事实和后续优先级。完整开发过程与问题复盘见 [`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md)。

## 状态说明

- `[x]`：代码或文档工作已经完成，并经过与风险相称的检查。
- `[ ]`：尚未完成或仍需人工/真实平台验收。
- Provider 的“已实现、已注册、已配置、已连通、已真实生成”是不同状态，不能互相替代。
- 自动化测试不会访问真实收费 API，通过测试不等于真实 Provider 已验收。

## 当前已完成能力

### 工程与统一架构

- [x] 建立 Python 3.11 `src/` 工程、依赖声明和 Gradio 应用入口。
- [x] 使用 Pydantic 定义故事、角色、分镜、漫画文字、图片记录、页面和项目数据。
- [x] 建立 `TextModelProvider`、`ImageProvider` 及各自注册表。
- [x] 文本创作、独立审查和图片生成可分别选择 Provider。
- [x] Provider 专用 URL、鉴权、请求体、响应解析和轮询逻辑与 UI/主流程隔离。
- [x] 环境变量构建 Provider；`.env.example` 不包含真实密钥和私密绝对路径。
- [x] Mock 文本与图片保持确定性，可在无外部服务时完成离线演示。
- [x] 建立安全错误类型、凭据脱敏、下载限制、Pillow 解码验证和显式 fallback 记录。

### 文本、审查与结构化分镜

- [x] 接入 Mock、Ollama、OpenAI-compatible 和 DeepSeek 文本 Provider。
- [x] 支持纯 JSON/Markdown 代码块提取、有限字段归一化和 Pydantic 校验。
- [x] 识别输出截断、缺字段、枚举错误、语言错误和格数不一致。
- [x] 支持有上限的 JSON 修复和可见漫画文字专项修复。
- [x] 支持独立审查模型；准确区分 `script_reviewed` 与 `review_applied`。
- [x] 审查稿可返回完整项目、项目 patch 或部分 panels；按 sequence 安全合并。
- [x] 审查无法安全合并时保留已验证初稿，不阻断后续生图。
- [x] 审查使用紧凑叙事快照和独立超时，避免重复传输纯视觉字段。
- [x] 支持标题候选、故事梗概、Story Bible、角色、动作、构图、子镜头和结构化文字项。
- [x] 前端支持 1–20 格；核心 schema/service 不硬编码四格或八格。

### 图片生成与角色参考

- [x] 接入 Mock、OpenAI Images、Recraft、Together、SiliconFlow、fal、ComfyUI 和 Gemini 图片 Provider。
- [x] 定义 Provider 能力，显式处理 seed、尺寸、比例、参考图、mask、negative prompt 和异步轮询差异。
- [x] 支持 URL、Base64、Gemini inlineData 和 ComfyUI 输出的本地安全保存。
- [x] 支持逐格生成、每格独立失败与 fallback、实际 Provider/模型/耗时/request ID/seed 记录。
- [x] 支持批量上传、剪贴板导入、顺序展示和拖动排序角色参考图。
- [x] 参考图按 Story Bible 角色顺序映射，并按当前分格出场角色筛选。
- [x] 启用参考图时，以参考身份为最高优先级，过滤冲突的发型、服装和配色描述。
- [x] ComfyUI 对远景、环境、群像和多人同框旁路当前单图 IPAdapter，避免人物特征污染。
- [x] 在 `project.json` 记录 `reference_count`、`reference_character_names` 和最终 Prompt。
- [x] 支持单格重生成、旧图归档和可逆版本回退。

### 漫画制作与前端

- [x] 图片 Provider 只生成无字分格，本地绘制对白、思考、旁白和拟声词。
- [x] 支持中文/英文/日文换行、字体回退、角色锚点、预留区和边缘密度位置评分。
- [x] 支持分镜表格编辑、故事补充重做、文字位置覆盖和生图后语言重排。
- [x] 支持传统漫画页、规则网格、竖向条漫、自定义画框和有限插入镜头。
- [x] 支持项目 JSON 保存与重载、PNG/PDF 导出和相对路径溯源。
- [x] 全屏预览支持滚轮缩放、左键拖动和双击复位。
- [x] 前端展示配置状态、请求/实际 Provider、模型、耗时、错误、审查状态和 fallback。

### 测试、文档与交付

- [x] 自动化测试使用假 HTTP transport，不调用真实外部 API。
- [x] 提供严格无 Mock fallback 的单图 Provider smoke test。
- [x] 提供气泡和页面布局离线预览脚本。
- [x] 建立面向使用者的 README 和无密钥配置模板。
- [x] 将零散日期/阶段记录合并为统一开发演进文档。
- [x] 建立项目报告、技术指南、Provider 指南、模型评估和 Demo 指南。

## Provider 验收矩阵

### 文本 Provider

| Provider | 已实现/注册 | 真实调用记录 | 当前结论 |
|---|:---:|:---:|---|
| Mock Text | ✅ | 离线确定性 | 可用于无配置演示与测试 |
| Ollama | ✅ | ✅ | 本机 `qwen3:4b` 有真实生成记录；长 JSON 稳定性有限 |
| OpenAI-compatible | ✅ | ✅ | 有真实生成和审查记录；具体表现取决于兼容后端 |
| DeepSeek | ✅ | ✅ | 有初稿与审查真实项目记录；仍需统计 8–20 格多轮成功率 |

### 图片 Provider

| Provider | 已实现/注册 | 连通/鉴权 | 真实生成 | 当前结论 |
|---|:---:|:---:|:---:|---|
| Mock Image | ✅ | 不需要 | 离线确定性 | 可用于文本组合与无配置演示 |
| Gemini Image | ✅ | ✅ | ✅ | 无参考、单参考及四格真实项目已有记录；第三方网关兼容性仍需逐项验收 |
| Recraft | ✅ | ✅ | ✅ | 多次真实手测和四格无回退记录 |
| ComfyUI | ✅ | ✅（本地） | ✅ | 严格单图及多格无回退记录；依赖本机工作流和模型 |
| SiliconFlow | ✅ | ✅ | ❌ | 已验证模型列表与目标模型，余额为 0，未完成收费生图验收 |
| OpenAI Images | ✅ | 未验收 | ❌ | 已适配和离线测试，尚未项目级真实验收 |
| Together | ✅ | 未验收 | ❌ | 已适配和离线测试，尚未项目级真实验收 |
| fal | ✅ | 未验收 | ❌ | 已适配和离线队列测试，尚未项目级真实验收 |

## 后续任务

### P0：运行与 Demo 稳定性

- [ ] 增加逐格图片任务进度，区分排队、生成、下载、排字和超时。
- [ ] 增加失败分格续跑，复用已成功图片而不是重新生成整页。
- [ ] 建立可重复的文本组合、Recraft、Gemini 和 ComfyUI 严格验收清单。
- [ ] 对 1、4、8、20 格分别统计 DeepSeek 与已验证文本模型的结构成功率和耗时。
- [ ] 持续归一化 Provider 间安全可恢复的结构差异，但不放松初稿必要字段。

### P1：角色一致性与编辑质量

- [ ] 升级 ComfyUI 多 IPAdapter、区域条件、角色 LoRA 或图片编辑工作流。
- [ ] 建立同一组角色参考的 A/B 测试和可量化一致性评价。
- [ ] 增加主体/人脸感知的气泡避让。
- [ ] 支持画布内直接拖拽、缩放和调整气泡样式。
- [ ] 增加透视拟声词和可选漫画字体包。
- [ ] 完成多页编辑、逐页重生成和整册导出的 UI 验收。

### P2：部署与 Provider 扩展

- [ ] 增加任务队列、用户身份、项目隔离、远程存储和受控部署。
- [ ] 在用户明确授权预算后，逐一真实验收 OpenAI Images、Together、fal 和 SiliconFlow。
- [ ] 逐一评估 DashScope、Volcengine Ark、Replicate 和 xAI，避免同时接入未验收 Provider。

## 免费验证基线

从项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -c "import app; assert app.demo"
git diff --check
```

如已安装 Ruff：

```powershell
.\.venv\Scripts\python.exe -m ruff check app.py src tests scripts
```

真实 Provider 验收必须由使用者主动执行，并在记录中同时标明模型、耗时、request ID、输出文件和 fallback 状态。
