# Image Provider 2.0 配置与验收指南

## 架构与安全边界

图片层统一使用 `ImageGenerationRequest`、`ImageGenerationResult`、
`ImageProviderCapabilities` 和 `ImageProvider`。Gradio 只读取注册表与能力，
不会判断平台协议；HTTP 地址、鉴权头、请求体、响应归一化和异步轮询均位于
各 Provider 模块。未实现的 Provider 不注册、不出现在页面中。

API Key 只能放在本机进程环境变量或被 Git 忽略的 `.env` 中。程序不会把 Key、
请求头或大段 base64 写入日志和 `project.json`。下载 URL 必须返回 `image/*`，
受到超时和最大字节数限制，并在进入排版前由 Pillow 完整解码验证。

## 当前能力矩阵

| Provider | 文生图 | 图片编辑/参考图 | 多参考图 | Mask | Negative prompt | Seed | 批量 | 异步轮询 | 任意尺寸 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Mock | 是 | 否 | 否 | 否 | 否 | 是 | 否 | 否 | 是 |
| OpenAI Images | 是 | 是 | 是 | 是 | 否 | 否 | 是 | 否 | 否 |
| Recraft | 是 | 否 | 否 | 否 | 是 | 否 | 是 | 否 | 限平台尺寸/比例 |
| Together | 是 | 否 | 否 | 否 | 是 | 是 | 是 | 否 | 是 |
| SiliconFlow | 是 | 是 | 最多 3 张 | 否 | 是 | 是 | 是 | 否 | 是 |
| fal | 是 | 否 | 否 | 否 | 否 | 是 | 是 | 是 | 是 |
| ComfyUI | 是 | 取决于 workflow；当前支持单参考图上传/IPAdapter 替换 | 否 | 否 | 取决于节点映射 | 取决于节点映射 | 否 | 是 | 取决于节点映射 |

能力由 Provider 返回，页面据此启用或禁用参数。不支持的参数在服务请求前抛出
`UnsupportedCapabilityError`，不会被静默丢弃。

## 通用稳定性配置

```dotenv
IMAGE_MODEL_CONNECT_TIMEOUT=10
IMAGE_MODEL_GENERATION_TIMEOUT=300
IMAGE_MODEL_MAX_RETRIES=1
IMAGE_MODEL_RETRY_BASE_DELAY=0.5
IMAGE_MODEL_MAX_POLL_SECONDS=300
IMAGE_MODEL_POLL_INTERVAL=1
IMAGE_DOWNLOAD_MAX_BYTES=20971520
IMAGE_PANEL_CONCURRENCY=1
IMAGE_MODEL_FALLBACK_TO_MOCK=true
IMAGE_PROVIDER_FALLBACK_CHAIN=
```

429、5xx、连接错误和超时使用有上限的指数退避。400、401、402、403 和内容
审核错误不会重试。`IMAGE_PROVIDER_FALLBACK_CHAIN` 使用逗号分隔 Provider ID，
例如 `together,mock-image`；服务会自动去重。页面的严格模式或
`IMAGE_MODEL_FALLBACK_TO_MOCK=false` 可禁止 Mock 回退。严格模式优先级更高，
真实 Provider 失败时直接报错。

## Provider 配置

### OpenAI Images

```dotenv
OPENAI_IMAGE_BASE_URL=https://api.openai.com
OPENAI_IMAGE_API_KEY=
OPENAI_IMAGE_MODEL=
OPENAI_IMAGE_SIZE=1024x1024
```

实现 `/v1/images/generations` 和 `/v1/images/edits`，支持 URL、`b64_json`、
多 `image[]` 与可选 `mask`。申请与接口说明：
[OpenAI API Keys](https://platform.openai.com/api-keys)、
[OpenAI Images API](https://platform.openai.com/docs/api-reference/images)。

### Recraft

```dotenv
RECRAFT_API_KEY=
RECRAFT_MODEL=recraftv4_1
RECRAFT_IMAGE_ENDPOINT=https://external.api.recraft.ai/v1/images/generations
```

实现 `data[].url`/`data[].b64_json`、`n`、`size`、`negative_prompt`。
申请和协议：[Recraft API 文档](https://www.recraft.ai/docs/api-reference/endpoints)。

### Together AI

```dotenv
TOGETHER_API_KEY=
TOGETHER_MODEL=
TOGETHER_IMAGE_ENDPOINT=https://api.together.xyz/v1/images/generations
```

实现 `width`、`height`、`aspect_ratio`、`negative_prompt`、`seed`、`n` 和
base64/URL 归一化。申请和协议：
[Together Images API](https://docs.together.ai/reference/post-images-generations)。

### SiliconFlow

```dotenv
SILICONFLOW_API_KEY=
SILICONFLOW_MODEL=
SILICONFLOW_IMAGE_ENDPOINT=https://api.siliconflow.cn/v1/images/generations
```

实现平台原生 `image_size`、`batch_size`、`images`、`seed` 结构，并支持最多
三张参考图的 `image`/`image2`/`image3` 数据 URL。申请和协议：
[SiliconFlow 图片生成](https://docs.siliconflow.cn/cn/api-reference/images/images-generations)。

### fal

```dotenv
FAL_KEY=
FAL_MODEL=
FAL_BASE_URL=https://queue.fal.run
```

向 `/{model}` 提交队列任务，读取 `request_id`、`status_url`、`response_url`，
轮询 `IN_QUEUE`/`IN_PROGRESS`/`COMPLETED` 后下载结果。申请和协议：
[fal Queue API](https://fal.ai/docs/documentation/model-apis/inference/queue)。

### ComfyUI

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

workflow 必须是 ComfyUI “API format” JSON。程序复制 workflow 后写入配置的
提示词/尺寸/Seed 节点；可上传一张参考图并替换 IPAdapter 的 `LoadImage` 输入；
随后 `POST /prompt`，轮询 `/history/{prompt_id}`，再通过 `/view` 下载输出，
不会修改源 workflow。当前工作区已有 SD1.5 512×512 严格单图和后续无回退项目记录；
更换 checkpoint 或 workflow 后仍需重新验收。协议：
[ComfyUI Server Routes](https://docs.comfy.org/development/comfyui-server/comms_routes)。

## 单图真实验收

先在本机 `.env` 配置对应 Provider，然后执行：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test_image_provider.py `
  --provider recraft `
  --model recraftv4_1 `
  --prompt "a cute orange cat, four-panel comic style, no text"
```

脚本默认严格模式，不会回退 Mock。成功时只输出 Provider、模型、耗时、
`request_id`、本地图片路径、尺寸和回退状态，绝不输出 Key。自动化测试全部
使用注入的 HTTP Mock；真实付费请求只应由用户主动运行该脚本或在页面生成。

当前真实验收边界：Recraft 已完成多次真实生图；ComfyUI 已完成严格本地生图；
SiliconFlow 已完成国际站鉴权和模型列表验证，但因余额为 0 尚未真实收费生图；
OpenAI Images、Together 和 fal 尚未配置或真实验收。实现或自动化测试通过不等于
真实平台验收。

## P1 边界

Gemini、DashScope、Volcengine、Replicate 和 xAI 尚未实现，也不会出现在注册表。
协议入口、变量和验收标准记录在 `TASKS.md`。正式接入前必须重新核对平台官方
文档，并增加完全离线的请求/响应和异步轮询测试。
