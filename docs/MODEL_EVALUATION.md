# ComicForge AI 模型调研与选型评估

> 调研更新日期：2026-08-09。

## 1. 调研目标与事实边界

ComicForge AI 需要在 1–20 格漫画中分别完成两类任务：

- 文本模型输出可校验的项目 JSON，包括故事、角色设定、分镜、动作、构图以及本地排版所需的可见文字；
- 图片模型根据单格绘图提示词生成场景，并在提供角色参考图时尽量保持身份、发型和服装，同时允许改变动作、镜头和背景。

本轮重点比较结构化输出稳定性、中文创作、长输出能力、角色参考、生成速度、成本、部署难度和当前项目改造成本。

本文严格区分四种结论：

1. **官方公开能力**：厂商网页声明模型或 API 支持某项能力；
2. **代码已适配**：ComicForge 中已经存在对应 Provider 和配置；
3. **真实调用成功**：已经获得真实模型响应或图片；
4. **项目闭环验收**：已在 ComicForge 前端完成文本、图片、保存、排版和错误记录的完整流程。

官方声明“支持参考图”不等于项目已经解决角色一致性；自动化测试通过也不等于真实收费 API 已验收。

## 2. 文本模型调研

### 2.1 候选模型对比


| 候选                    | 网页公开规格与能力                                                                                                                                                                                                             | 优点                                             | 局限与风险                                                                         | 对本项目的判断                                   |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| Ollama + Qwen3 4B     | Ollama 标签页列出的 `qwen3:4b` 默认包约 2.5 GB，页面标注 256K 上下文；不同量化标签的文件体积和上下文标注并不完全相同。[T1]                                                                                                                                       | 本地离线、无按次费用、隐私可控；现有代码和真实项目记录已经接通                | 4B 小模型在 8–20 格长 JSON、修订稿全字段复制、语言约束方面多次出现截断或结构漂移；还会与本地 ComfyUI 争用显存            | 保留为离线和备用路线，不再作为高稳定 Demo 的首选文本模型           |
| Ollama + Qwen3 8B/14B | Ollama 默认量化标签中，8B 约 5.2 GB、14B 约 9.3 GB，二者页面均标注 40K 上下文；8B/14B 的 Q8 和 FP16 版本体积更大。[T1]                                                                                                                                | 参数规模高于 4B，通常有更好的指令理解和长结构生成潜力                   | 推理更慢、内存或显存占用更高；“模型更大”不能直接证明项目 JSON 成功率更高                                      | 有足够硬件时值得做本地 A/B 测试，但必须用 1/4/8/20 格样本统计成功率 |
| DeepSeek V4 Flash     | 官方模型 ID 为 `deepseek-v4-flash`；OpenAI 格式 Base URL 为 `https://api.deepseek.com`；上下文 1M、最大输出 384K；支持 JSON Output、工具调用、思考与非思考模式。官方当前价格为缓存命中输入 $0.0028/百万 token、缓存未命中输入 $0.14/百万 token、输出 $0.28/百万 token，并标注并发上限 2500。[T2] | 输出空间大、价格低、OpenAI 兼容、适合长结构 JSON；当前项目已经真实跑通初稿和审查 | 依赖网络、余额和服务可用性；JSON Output 只能保证 JSON 字符串形式，不能保证完全符合 ComicForge 的 Pydantic 业务结构 | **当前首选文本模型**                              |
| DeepSeek V4 Pro       | 官方规格同样为 1M 上下文、最大输出 384K，并支持 JSON Output；当前价格为缓存命中输入 $0.003625/百万 token、缓存未命中输入 $0.435/百万 token、输出 $0.87/百万 token，并发上限 500。[T2]                                                                                       | 更适合作为复杂审查或质量对照模型                               | 成本高于 Flash、并发更低；对普通四格脚本未必带来成比例收益                                              | 作为审查质量档候选，不建议默认用于每次初稿                     |
| OpenAI GPT-5.6 系列     | 官方比较页列出 Sol、Terra、Luna 三档，均为 1.05M 上下文、最大输出 128K，并支持 Structured Outputs、函数调用和图像输入。页面当前列价：Sol 输入 $5/百万 token、输出 $30；Terra 输入 $2、输出 $12；Luna 输入 $0.20、输出 $1.20。[T5]                                                     | 结构化输出能力明确，适合复杂项目结构和高质量对照                       | 成本高于 DeepSeek；项目当前没有完成该系列的真实 Provider 验收                                      | 质量对照候选，不是当前默认组合                           |




### 2.2 DeepSeek JSON Output 的实际含义

DeepSeek 官方 JSON Output 指南给出了四项关键要求：[T3]

1. 请求中设置 `response_format={"type":"json_object"}`；
2. 系统或用户提示词中明确要求输出 JSON，并提供目标结构示例；
3. 合理设置 `max_tokens`，避免 JSON 在中途被截断；
4. 官方明确提示 JSON 模式偶尔可能返回空内容，需要通过提示词调整或重试处理。

因此，ComicForge 不能只依赖 `json_object`。项目仍需执行 JSON 代码块提取、安全解析、字段归一化、Pydantic 校验和有限次数修复。模型返回“合法 JSON”仍可能出现缺少 `panels`、位置枚举错误、分格数量不一致或子镜头字段缺失。

### 2.3 DeepSeek 思考模式与 Demo 延迟

DeepSeek 官方说明思考模式默认开启，OpenAI 格式使用 `thinking: {"type":"enabled"}` 或 `disabled` 切换；思考模式下还会返回 `reasoning_content`。官方同时说明，思考模式下 `temperature`、`top_p`、`presence_penalty` 和 `frequency_penalty` 不生效。[T4]

ComicForge 的脚本初稿和结构修复更重视稳定格式和响应时间，因此当前 DeepSeek Provider 显式发送：

```json
{
  "thinking": {
    "type": "disabled"
  }
}
```

关闭思考并不代表关闭结构校验；它只是减少不必要的推理等待，最终输出仍必须通过项目数据模型。

### 2.4 为什么当前选择 DeepSeek V4 Flash

此前主要瓶颈并不是模型不会写故事，而是 Qwen3 4B 在长 JSON 中频繁出现缺字段、字段类型错误、审查稿漏掉 `panels`、8 格以上被截断和审查超时。DeepSeek V4 Flash 提供更大的上下文和输出空间、官方 JSON 模式以及较低价格，且已经在真实项目中成功完成初稿和审查。

但这并不意味着 DeepSeek 输出永远正确。项目已经针对实际出现的枚举位置、子镜头结构和部分审查补丁做了兼容归一化，仍需保留错误可见性和初稿保护机制。

## 3. 图片模型调研



### 3.1 候选模型对比


| 候选                             | 网页公开规格与能力                                                                                                                                                                            | 优点                            | 局限与风险                                                   | 对本项目的判断                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------- | ------------------------------------------------------- | -------------------------------------- |
| Gemini 3.1 Flash Image         | 官方模型 ID 为 `gemini-3.1-flash-image`，支持文本和图片输入、图片和文本输出；支持 0.5K/1K/2K/4K、多种横竖比例、中文，单次工作流最多维持 4 个角色的相似性和最多 10 个物体的高保真。[I1][I2]                                                           | 原生生成与编辑、多参考图、速度导向、适合高吞吐漫画逐格生图 | 无免费图片层；不能保证严格输出指定数量；生成图带 SynthID；第三方中转可能忽略官方参数或采用不同计费   | **当前首选云端图片模型**；官方模式和中转模式均已实现，中转已完成真实闭环 |
| GPT Image 2                    | 官方模型 ID 为 `gpt-image-2`，支持文本输入以及图片输入/输出，支持高保真图片输入和灵活尺寸；生成和编辑端点分别为 `/v1/images/generations` 与 `/v1/images/edits`。官方模型页标注免费层不支持，并按账户等级限制 IPM。[I3]                                      | 高质量生成和编辑，接口清晰，适合做角色参考质量对照     | 项目尚未配置或真实验收；角色一致性必须用同一组漫画样本验证，不能只依据官方定位                 | 强云端对照候选，本阶段不宣称已接通                      |
| FLUX.2                         | 官方编辑文档说明 API 最多接收 8 张参考图，Playground 最多 10 张，最高 4MP；提供 Max、Pro、Flex、Klein 等不同精度、吞吐和成本档位；API 创建任务后返回请求 ID 和轮询地址。[I4]                                                                   | 多参考图和编辑控制更适合多角色、道具、场景素材组合     | 需要新增 Provider、异步轮询、下载、计费和失败分类；多参考图能力不等于人物身份必然稳定         | 下一阶段多角色同格的重要候选                         |
| Recraft V4/V4.1                | Recraft 官方说明没有专用角色追踪功能，建议组合详细角色提示词、统一风格、参考图、Frame 局部编辑和外部模型；API 使用 Bearer Token，基础地址为 `https://external.api.recraft.ai/v1`，部分编辑接口允许 1–6 张输出并提供 strength、negative_prompt 等参数。[I5][I6] | 项目已经完成真实生图验收；插画质量和云端速度适合 Demo | 现有接入不能彻底解决跨格身份一致性；参考能力与 Studio 功能、具体 API 端点有关           | 保留为已验证云端 Demo 路线，不作为角色一致性的最终方案         |
| ComfyUI + Animagine/IP-Adapter | IP-Adapter 官方项目将其描述为轻量图像提示适配器，核心适配器约 22M 参数；可与文字提示和 ControlNet 组合。官方建议仅用图片提示时 scale 可设 1.0，多模态提示通常可从 0.5 附近调试；scale 越低越自由，但与参考图一致性可能下降。CLIP 默认中心裁切使其更适合方形参考图。[I7]                    | 本地免费、工作流可控，现有项目已真实接通          | 当前整图参考会在身份相似和构图自由之间冲突；多角色容易特征污染；参考图非方形时中心外信息可能丢失        | 保留为本地路线，需要升级工作流而不只是改提示词                |
| ComfyUI + Qwen-Image-Edit      | Qwen 官方模型卡说明它建立在 20B Qwen-Image 上，同时将输入图送入 Qwen2.5-VL 做语义控制、送入 VAE Encoder 做外观控制，支持中英文文字编辑和高低层次图像编辑。ComfyUI 官方工作流需要 diffusion model、Lightning LoRA、Qwen2.5-VL 7B 文本编码器和 VAE。[I8][I9] | 更适合“保留人物外观，只改变动作和场景”的编辑路线     | 模型、编码器和 VAE 的磁盘与显存要求显著高于当前工作流；需要重新建立 API Workflow 并测试耗时 | 最值得尝试的本地角色一致性升级方案，但尚未安装或验收             |




### 3.2 Gemini 3.1 Flash Image 网页规格展开

Gemini 官方图片文档给出的能力边界如下：[I1][I2]

- 默认输出 1K；可请求 0.5K、1K、2K、4K，尺寸参数中的 `K` 必须大写；
- 支持 `1:1`、`2:3`、`3:2`、`3:4`、`4:3`、`4:5`、`5:4`、`9:16`、`16:9`、`21:9`，并增加 `1:4`、`4:1`、`1:8`、`8:1`；
- 没有输入图且未指定画幅时，模型默认生成 `1:1` 方图；有输入图时默认尝试匹配输入图尺寸；
- 支持最多 4 个角色的相似性控制和最多 10 个物体的高保真输入，但这是单次工作流上限，不是跨 20 格绝对一致性保证；
- 适用语言包含 `zh-CN`；
- 模型不保证每次严格遵守要求的图片数量；
- 所有生成图片包含 SynthID 水印；
- Gemini 3 图片模型会进行不可关闭的内部图像推理，并可能产生用于构图测试的中间思考图，最后一张才是最终渲染图。

与 ComicForge 当前常用画幅直接相关的官方尺寸如下：


| 目标画幅 | 1K 官方像素   | 2K 官方像素   | 适合的漫画框     |
| ---- | --------- | --------- | ---------- |
| 3:4  | 896×1200  | 1792×2400 | 竖幅人物、半行竖框  |
| 4:3  | 1200×896  | 2400×1792 | 常规横框       |
| 16:9 | 1376×768  | 2752×1536 | 宽幅场景、动作大景  |
| 9:16 | 768×1376  | 1536×2752 | 极竖幅人物或手机画面 |
| 1:1  | 1024×1024 | 2048×2048 | 方形分格       |




### 3.3 官方 Gemini 与当前第三方中转的区别

Google 官方模型 ID 是 `gemini-3.1-flash-image`，官方接口和美元价格由 Google 规定。当前项目实际使用的中转模型名为：

```text
[30额度]gemini-3.1-flash-image-preview
```

该名称、`30额度/次` 的内部计费和 `https://bboluo.com` 网关均属于第三方中转，不是 Google 官方模型命名或官方计价单位。因此本文分别记录：

- **官方能力依据**：以 Google 官方 Gemini 文档为准；
- **项目真实调用依据**：以中转返回、账户扣费和 `project.json` 为准；
- **不能直接推导的结论**：中转声称是 Gemini，并不能保证完整支持 Google 官方全部请求字段、画幅和分辨率。

2026-08-09 的四格项目记录显示，ComicForge 分别请求了 `3:4` 和 `16:9`、图片档位为 `1K`，但中转返回的四张源图均为 2048×2048 方图。这说明当时中转没有按预期执行画幅和档位。项目随后增加了 `generationConfig.imageConfig` 与 `responseFormat.image` 两种可切换封装，并在 `actual_parameters` 中记录模式；修改已经通过离线测试，但仍需再用一张付费 `16:9` 图片确认该中转是否真正接受新字段。

### 3.4 Gemini 官方成本与 1–20 格估算

Google 官方标准价格中，Gemini 3.1 Flash Image 无免费图片层；文本/图片输入为 $0.50/百万 token，文本与思考输出为 $3/百万 token，图片输出为 $60/百万 token。官方折算的单张输出价格为：[I10]

- 0.5K：约 $0.045/张；
- 1K：约 $0.067/张；
- 2K：约 $0.101/张；
- 4K：约 $0.151/张。

以下只计算官方标准模式的输出图，不包含输入、税费、失败重试和第三方中转溢价：


| 漫画格数 | 1K     | 2K     | 4K     |
| ---- | ------ | ------ | ------ |
| 1    | $0.067 | $0.101 | $0.151 |
| 4    | $0.268 | $0.404 | $0.604 |
| 8    | $0.536 | $0.808 | $1.208 |
| 12   | $0.804 | $1.212 | $1.812 |
| 20   | $1.340 | $2.020 | $3.020 |


当前第三方中转按“内部额度”扣费，不能用上表直接换算。中转实测一次成功调用扣除 30 额度，失败、超时和重试是否扣费应以中转账单为准。因此项目将 Gemini 自动重试默认设为 0，避免同一分格在不明确计费规则下重复扣费。

### 3.5 本地角色一致性为什么仍然困难

IP-Adapter 官方说明揭示了当前工作流的核心权衡：[I7]

- 图片条件权重较高时更接近参考图，但动作、镜头和场景自由度下降，容易变成人物特写；
- 权重降低时构图更自由，但身份、服装和发型容易漂移；
- 文本提示与参考图外貌描述冲突时，两种条件会竞争；
- 非方形参考图会被 CLIP 中心裁切，中心外服装、道具或身体信息可能丢失；
- 多角色共同进入同一个全局条件时，容易发生服装、发色和面部特征污染。

因此，代码侧已经实施“使用参考图时删除冲突外貌描述，只改变动作、表情、场景和镜头”的规则，但彻底改善仍需要工作流能力：FaceID、区域遮罩、ControlNet、角色 LoRA，或切换到 Qwen-Image-Edit 这种原生编辑模型。

## 4. 选定组合与验证计划

当前推荐组合为：

- 剧本初稿：DeepSeek V4 Flash，关闭 thinking，使用 JSON Output；
- 剧本审查：先使用 DeepSeek V4 Flash，若审查质量不足再单独比较 V4 Pro；
- 图片生成：Gemini 3.1 Flash Image 中转，默认 1K；
- 本地备选图片路线：ComfyUI；
- 角色参考：按 Story Bible 角色顺序上传，只给实际出场并需要锁定身份的分格传图；
- 漫画文字：由 ComicForge 本地绘制，图片模型不得负责对白、旁白和气泡。

后续验收顺序：

1. 无费用的配置检查和假 transport 自动化测试；
2. DeepSeek 1/4/8/20 格结构化文本成功率统计；
3. DeepSeek 初稿与审查的独立组合测试；
4. Gemini 单张 `16:9` 画幅参数复验；
5. Gemini 单角色参考图 A/B 测试；
6. Gemini 多角色同格的参考图映射测试；
7. 四格完整闭环；
8. 在用户明确预算后再测试 8–20 格。



## 5. 当前实现与真实验收状态



### 5.1 Provider 状态


| 项目                   | 已实现 | 已注册 | 已配置 | 当前真实证据                                                                                              | 尚未完成                                          |
| -------------------- | --- | --- | --- | --------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| DeepSeek 文本 Provider | 是   | 是   | 是   | 2026-08-09 项目中，初稿和审查实际 Provider 均为 `deepseek-v4-flash`，`review_applied=true`、`script_reviewed=true` | 仍需统计 8–20 格多轮成功率                              |
| Gemini 图片 Provider   | 是   | 是   | 是   | 中转已完成无参考图、单参考图直接调用；ComicForge 四格项目完成 4 张真实图，无 Mock fallback                                         | 官方 Google API 未验收；中转画幅新封装尚待一张付费复验；多角色参考闭环尚待验收 |
| 前端动态选项               | 是   | 是   | 是   | DeepSeek 与 Gemini 已能由注册表出现在前端并用于真实项目                                                                | 需要继续改善配置状态说明和参考图操作体验                          |




### 5.2 最近一次完整项目证据

记录文件：`outputs/20260809_134318_596879_哪吒闹海/project.json`


| 证据项            | 实际记录                                              |
| -------------- | ------------------------------------------------- |
| 文本 Provider/模型 | `deepseek` / `deepseek-v4-flash`                  |
| 审查 Provider/模型 | `deepseek` / `deepseek-v4-flash`                  |
| 审查状态           | `review_applied=true`，`script_reviewed=true`      |
| 图片 Provider/模型 | `gemini` / `[30额度]gemini-3.1-flash-image-preview` |
| 图片格数           | 4                                                 |
| 单格耗时           | 23.82 秒、38.37 秒、34.46 秒、41.12 秒                   |
| 图片总耗时          | 约 137.77 秒                                        |
| fallback       | 四格均为 `false`                                      |
| 请求画幅           | 第 1–2 格 `3:4`，第 3–4 格 `16:9`                      |
| 当时返回源图         | 四张均为 2048×2048；中转画幅未按请求生效                         |


该项目能够证明 DeepSeek + Gemini 中转组合已经完成真实四格闭环，但不能证明：Google 官方 API 已验收、第三方中转完整兼容官方协议、多角色参考图已经稳定、角色一致性已经彻底解决。

## 6. 综合结论

1. **文本侧**：DeepSeek V4 Flash 相比本地 Qwen3 4B 更适合作为 1–20 格结构化漫画项目的当前主路线，优势主要来自输出空间、JSON 模式、速度和成本；业务结构仍必须由项目校验。
2. **云端图片侧**：Gemini 3.1 Flash Image 的官方多参考和编辑能力最符合角色一致性目标，当前中转也已经完成真实四格生成，但中转协议兼容性和画幅执行仍需单图复验。
3. **本地图片侧**：现有 IP-Adapter 工作流能够证明本地参考图路线可运行，但全局图像条件难以同时满足身份、动作和多人构图。Qwen-Image-Edit 是更合理的下一阶段升级方向。
4. **成本侧**：Demo 应优先跑单图、再跑四格；8–20 格必须在预算明确后执行。任何自动重试都可能产生额外费用。
5. **工程侧**：Provider 能独立切换、错误和 fallback 可追溯，比单次生成效果更重要；模型升级不应绕过统一请求、记录和校验边界。



## 7. 网页来源与读取要点

下列网址用于追溯。正文已经写明各页面的关键内容，阅读 Word 版本时无需打开网页才能理解结论。

### 7.1 文本模型来源

- **[T1] Ollama：Qwen3 标签与模型体积**
页面信息：列出 Qwen3 各参数规模、默认量化包体积、上下文标注和不同量化版本。
[https://ollama.com/library/qwen3/tags](https://ollama.com/library/qwen3/tags)
- **[T2] DeepSeek：模型与价格**
页面信息：列出 V4 Flash/Pro 的模型 ID、Base URL、上下文、最大输出、JSON Output、价格和并发限制。
[https://api-docs.deepseek.com/quick_start/pricing](https://api-docs.deepseek.com/quick_start/pricing)
- **[T3] DeepSeek：JSON Output**
页面信息：说明 `response_format=json_object`、提示词要求、`max_tokens` 防截断以及偶发空内容风险。
[https://api-docs.deepseek.com/guides/json_mode/](https://api-docs.deepseek.com/guides/json_mode/)
- **[T4] DeepSeek：Thinking Mode**
页面信息：说明 thinking 默认开启、开关字段、reasoning effort 和思考模式下不生效的采样参数。
[https://api-docs.deepseek.com/guides/thinking_mode](https://api-docs.deepseek.com/guides/thinking_mode)
- **[T5] OpenAI：模型比较**
页面信息：列出 GPT-5.6 Sol/Terra/Luna 的价格、上下文、最大输出、端点和 Structured Outputs 等能力。
[https://developers.openai.com/api/docs/models/compare](https://developers.openai.com/api/docs/models/compare)



### 7.2 图片模型来源

- **[I1] Google：Gemini 图片生成与编辑**
页面信息：说明生成/编辑方式、多参考图数量、语言、画幅、分辨率、限制和 SynthID。
[https://ai.google.dev/gemini-api/docs/image-generation](https://ai.google.dev/gemini-api/docs/image-generation)
- **[I2] Google：Gemini 3.1 Flash Image 模型卡**
页面信息：给出模型 ID、输入输出模态、Thinking、图片生成、搜索 grounding 和画幅改进。
[https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image)
- **[I3] OpenAI：GPT Image 2 模型页**
页面信息：给出模型 ID、输入输出模态、生成/编辑端点、免费层和分级速率限制。
[https://developers.openai.com/api/docs/models/gpt-image-2](https://developers.openai.com/api/docs/models/gpt-image-2)
- **[I4] Black Forest Labs：FLUX.2 图片编辑**
页面信息：说明 API/Playground 多参考图上限、4MP 输出、不同模型档位和异步轮询。
[https://docs.bfl.ai/flux_2/flux2_image_editing](https://docs.bfl.ai/flux_2/flux2_image_editing)
- **[I5] Recraft：角色一致性建议**
页面信息：明确没有专用角色追踪功能，并列出提示词、统一风格、参考图、Frame 和外部模型组合方法。
[https://www.recraft.ai/docs/best-practices/character-consistency](https://www.recraft.ai/docs/best-practices/character-consistency)
- **[I6] Recraft：API 端点**
页面信息：说明 Bearer 鉴权、Base URL、图片生成/编辑字段、返回格式和约束。
[https://www.recraft.ai/docs/api-reference/endpoints](https://www.recraft.ai/docs/api-reference/endpoints)
- **[I7] 腾讯 AI Lab：IP-Adapter**
页面信息：说明轻量图像提示适配器、FaceID 版本、scale 权衡、ControlNet 组合以及非方图中心裁切限制。
[https://github.com/tencent-ailab/IP-Adapter](https://github.com/tencent-ailab/IP-Adapter)
- **[I8] ComfyUI：Qwen-Image-Edit 官方工作流**
页面信息：列出工作流、模型文件、文本编码器、VAE、输入缩放和 Lightning LoRA 加速步骤。
[https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit](https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit)
- **[I9] Qwen：Qwen-Image-Edit 模型卡**
页面信息：说明 20B 基座、语义/外观双控制、中英文文字编辑和 Diffusers 调用方式。
[https://huggingface.co/Qwen/Qwen-Image-Edit](https://huggingface.co/Qwen/Qwen-Image-Edit)
- **[I10] Google：Gemini Developer API 价格**
页面信息：列出 Gemini 3.1 Flash Image 的标准/Batch 输入输出价格及不同分辨率的单图折算。
[https://ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)

