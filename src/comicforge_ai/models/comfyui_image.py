"""ComfyUI workflow submission, history polling, and image download Provider."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from comicforge_ai.models.http import HttpTimeout
from comicforge_ai.models.image_base import (
    ConfigurationError,
    ImageGenerationResult,
    ImageModelError,
    ImageModelStatus,
    ImageProvider,
    ImageProviderCapabilities,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comicforge_ai.models.image_provider_utils import (
    DownloadTransport,
    JsonObject,
    JsonTransport,
    RetryPolicy,
    Sleeper,
    download_image,
    normalized_result,
    request_json,
    with_retry,
)
from comicforge_ai.schemas import ImageGenerationRequest


class ComfyUIImageProvider(ImageProvider):
    model_id = "comfyui"
    display_name = "ComfyUI Workflow"
    provider_type = "local_async_http"

    def __init__(
        self,
        *,
        base_url: str,
        workflow: dict[str, Any] | None,
        prompt_node_id: str,
        model: str = "comfyui-workflow",
        width_node_id: str = "",
        height_node_id: str = "",
        seed_node_id: str = "",
        connect_timeout: float = 10,
        generation_timeout: float = 300,
        max_retries: int = 1,
        max_poll_seconds: float = 300,
        poll_interval: float = 1,
        max_download_bytes: int = 20 * 1024 * 1024,
        transport: JsonTransport | None = None,
        download_transport: DownloadTransport | None = None,
        sleeper: Sleeper = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.workflow = workflow
        self.prompt_node_id = prompt_node_id.strip()
        self.width_node_id = width_node_id.strip()
        self.height_node_id = height_node_id.strip()
        self.seed_node_id = seed_node_id.strip()
        self.model = model.strip() or "comfyui-workflow"
        self.timeout = HttpTimeout(
            connect=max(0.1, connect_timeout),
            read=max(0.1, generation_timeout),
        )
        self.retry_policy = RetryPolicy(max_retries=max(0, max_retries))
        self.max_poll_seconds = max(1, max_poll_seconds)
        self.poll_interval = max(0, poll_interval)
        self.max_download_bytes = max(1024, max_download_bytes)
        self.transport = transport or request_json
        self.download_transport = download_transport or download_image
        self.sleeper = sleeper
        self.clock = clock

    @property
    def model_name(self) -> str:
        return self.model

    def get_capabilities(self) -> ImageProviderCapabilities:
        return ImageProviderCapabilities(
            text_to_image=True,
            seed=bool(self.seed_node_id),
            async_task=True,
            arbitrary_size=bool(self.width_node_id and self.height_node_id),
        )

    def validate_config(self) -> ImageModelStatus:
        missing = tuple(
            name
            for name, value in (
                ("COMFYUI_BASE_URL", self.base_url),
                ("COMFYUI_WORKFLOW_PATH", self.workflow),
                ("COMFYUI_PROMPT_NODE_ID", self.prompt_node_id),
            )
            if not value
        )
        parsed = urlparse(self.base_url)
        problem = ""
        if self.base_url and (
            parsed.scheme not in {"http", "https"} or not parsed.netloc
        ):
            problem = "COMFYUI_BASE_URL 不是有效 HTTP(S) 地址"
        if self.workflow and self.prompt_node_id not in self.workflow:
            problem = "Prompt 节点不在 ComfyUI workflow 中"
        configured = not missing and not problem
        message = (
            "未配置：缺少 " + "、".join(missing)
            if missing
            else "配置无效：" + problem
            if problem
            else "配置完整；可检测本地 ComfyUI 服务"
        )
        return ImageModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=configured,
            available=configured,
            message=message,
            missing_settings=missing,
            connect_timeout=self.timeout.connect,
            generation_timeout=self.timeout.read,
        )

    def health_check(self) -> ImageModelStatus:
        status = self.validate_config()
        if not status.configured:
            return status
        try:
            self.transport(
                "GET",
                f"{self.base_url}/system_stats",
                {},
                None,
                HttpTimeout(self.timeout.connect, self.timeout.connect),
            )
        except (ImageModelError, OSError) as exc:
            return replace(
                status,
                available=False,
                message=f"ComfyUI 不可用：{type(exc).__name__}",
            )
        return status

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        status = self.validate_config()
        if not status.configured:
            raise ConfigurationError(status.message)
        self.validate_request(request, operation="text_to_image")
        workflow = self._build_workflow(request)
        started = time.perf_counter()
        submit, submit_retries = with_retry(
            lambda: self.transport(
                "POST",
                f"{self.base_url}/prompt",
                {"Content-Type": "application/json"},
                {"prompt": workflow, "client_id": str(uuid.uuid4())},
                self.timeout,
            ),
            self.retry_policy,
            sleeper=self.sleeper,
        )
        prompt_id = str(submit.get("prompt_id", ""))
        if not prompt_id:
            raise ProviderResponseError("ComfyUI 提交响应缺少 prompt_id")
        deadline = self.clock() + self.max_poll_seconds
        polls = 0
        while self.clock() < deadline:
            history, _ = with_retry(
                lambda: self.transport(
                    "GET",
                    f"{self.base_url}/history/{prompt_id}",
                    {},
                    None,
                    self.timeout,
                ),
                self.retry_policy,
                sleeper=self.sleeper,
            )
            polls += 1
            record = history.get(prompt_id)
            if isinstance(record, dict):
                entries = self._history_entries(record)
                payload: JsonObject = {
                    "images": entries,
                    "prompt_id": prompt_id,
                    "status": record.get("status", {}),
                }
                return normalized_result(
                    provider=self.model_id,
                    provider_name=self.display_name,
                    model=request.model or self.model,
                    operation="text_to_image",
                    payload=payload,
                    entries=entries,
                    duration=time.perf_counter() - started,
                    output_path=output_path,
                    downloader=self.download_transport,
                    timeout=self.timeout,
                    max_bytes=self.max_download_bytes,
                    actual_parameters={
                        "width": request.width,
                        "height": request.height,
                        "seed": request.seed,
                        "submit_retries": submit_retries,
                        "polls": polls,
                    },
                    seed=request.seed,
                    request_id=prompt_id,
                )
            self.sleeper(self.poll_interval)
        raise ProviderTimeoutError(
            f"ComfyUI 任务轮询超时（上限 {self.max_poll_seconds:g} 秒）"
        )

    def _build_workflow(self, request: ImageGenerationRequest) -> dict[str, Any]:
        assert self.workflow is not None
        workflow = copy.deepcopy(self.workflow)
        workflow[self.prompt_node_id].setdefault("inputs", {})["text"] = request.prompt
        for node_id, field, value in (
            (self.width_node_id, "width", request.width),
            (self.height_node_id, "height", request.height),
            (self.seed_node_id, "seed", request.seed),
        ):
            if node_id and value is not None:
                if node_id not in workflow:
                    raise ProviderResponseError(f"ComfyUI workflow 缺少节点 {node_id}")
                workflow[node_id].setdefault("inputs", {})[field] = value
        return workflow

    def _history_entries(self, record: dict[str, Any]) -> list[dict[str, object]]:
        outputs = record.get("outputs")
        if not isinstance(outputs, dict):
            raise ProviderResponseError("ComfyUI history 缺少 outputs")
        entries: list[dict[str, object]] = []
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            images = output.get("images")
            if not isinstance(images, list):
                continue
            for item in images:
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                query = urlencode(
                    {
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }
                )
                entries.append({"url": f"{self.base_url}/view?{query}"})
        if not entries:
            raise ProviderResponseError("ComfyUI history 中没有生成图片")
        return entries
