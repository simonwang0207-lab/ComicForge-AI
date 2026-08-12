"""ComfyUI workflow submission, history polling, and image download Provider."""

from __future__ import annotations

import copy
import mimetypes
import secrets
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
    MultipartTransport,
    RetryPolicy,
    Sleeper,
    download_image,
    normalized_result,
    request_json,
    request_multipart,
    with_retry,
)
from comicforge_ai.schemas import ImageGenerationRequest


class ComfyUIImageProvider(ImageProvider):
    model_id = "comfyui"
    display_name = "ComfyUI Workflow"
    uses_local_accelerator = True
    # A finished story panel is not a safe identity reference: its pose,
    # framing and background are all encoded by a whole-image IPAdapter. In
    # particular, using a close-up first panel tends to turn every later scene
    # into another close-up. ComfyUI therefore only uses explicit character
    # references supplied by the caller.
    auto_reference_from_first_panel = False
    restrict_reference_to_portrait_panels = True
    provider_type = "local_async_http"
    prompt_profile = "sd_comfyui"

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
        negative_prompt_node_id: str = "",
        reference_image_node_id: str = "",
        connect_timeout: float = 10,
        generation_timeout: float = 300,
        max_retries: int = 1,
        max_poll_seconds: float = 300,
        poll_interval: float = 1,
        max_download_bytes: int = 20 * 1024 * 1024,
        transport: JsonTransport | None = None,
        upload_transport: MultipartTransport | None = None,
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
        self.negative_prompt_node_id = (
            negative_prompt_node_id.strip()
            or self._detect_negative_prompt_node(workflow)
        )
        self.reference_image_node_id = (
            reference_image_node_id.strip()
            or self._detect_reference_image_node(workflow)
        )
        self.model = model.strip() or "comfyui-workflow"
        self.checkpoint_name = self._detect_checkpoint_name(workflow)
        if "animagine" in (self.checkpoint_name or self.model).lower():
            self.prompt_profile = "animagine_xl"
        self.timeout = HttpTimeout(
            connect=max(0.1, connect_timeout),
            read=max(0.1, generation_timeout),
        )
        self.retry_policy = RetryPolicy(max_retries=max(0, max_retries))
        self.max_poll_seconds = max(1, max_poll_seconds)
        self.poll_interval = max(0, poll_interval)
        self.max_download_bytes = max(1024, max_download_bytes)
        self.transport = transport or request_json
        self.upload_transport = upload_transport or request_multipart
        self.download_transport = download_transport or download_image
        self.sleeper = sleeper
        self.clock = clock

    @property
    def model_name(self) -> str:
        return self.model

    def get_capabilities(self) -> ImageProviderCapabilities:
        return ImageProviderCapabilities(
            text_to_image=True,
            image_to_image=bool(self.reference_image_node_id),
            negative_prompt=bool(self.negative_prompt_node_id),
            seed=bool(self.seed_node_id),
            async_task=True,
            arbitrary_size=bool(self.width_node_id and self.height_node_id),
        )

    def preferred_generation_size(
        self,
        target_aspect_ratio: float,
    ) -> tuple[int, int] | None:
        """Choose model-family-safe dimensions close to the final panel ratio."""
        if not self.width_node_id or not self.height_node_id:
            return None
        ratio = min(3.0, max(0.5, float(target_aspect_ratio)))
        if self.prompt_profile == "animagine_xl":
            if ratio >= 2.0:
                return 1536, 640
            if ratio >= 1.35:
                return 1216, 832
            if ratio >= 1.1:
                return 1152, 896
            if ratio > 0.9:
                return 1024, 1024
            if ratio > 0.7:
                return 896, 1152
            return 832, 1216
        target_pixels = 512 * 512
        if ratio >= 1:
            width = min(768, _nearest_multiple((target_pixels * ratio) ** 0.5, 64))
            height = _nearest_multiple(width / ratio, 64)
        else:
            height = min(768, _nearest_multiple((target_pixels / ratio) ** 0.5, 64))
            width = _nearest_multiple(height * ratio, 64)
        return max(256, width), max(256, height)

    @staticmethod
    def _detect_checkpoint_name(
        workflow: dict[str, Any] | None,
    ) -> str:
        """Read the checkpoint filename from a basic ComfyUI API workflow."""
        if not workflow:
            return ""
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") not in {
                "CheckpointLoaderSimple",
                "CheckpointLoader",
            }:
                continue
            inputs = node.get("inputs")
            if isinstance(inputs, dict):
                return str(inputs.get("ckpt_name", "")).strip()
        return ""

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
        if (
            self.workflow
            and self.negative_prompt_node_id
            and self.negative_prompt_node_id not in self.workflow
        ):
            problem = "Negative prompt 节点不在 ComfyUI workflow 中"
        if (
            self.workflow
            and self.reference_image_node_id
            and self.reference_image_node_id not in self.workflow
        ):
            problem = "Reference image node is missing from the ComfyUI workflow"
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
        return self._run_generation(request, output_path, operation="text_to_image")

    def edit(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        """Generate with a character or style reference image."""
        status = self.validate_config()
        if not status.configured:
            raise ConfigurationError(status.message)
        self.validate_request(request, operation="edit")
        if not request.reference_images:
            raise ProviderResponseError(
                "ComfyUI reference generation requires one reference image"
            )
        return self._run_generation(request, output_path, operation="edit")

    def _run_generation(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None,
        *,
        operation: str,
    ) -> ImageGenerationResult:
        if request.seed is None and self.seed_node_id:
            request = request.model_copy(
                update={"seed": secrets.randbelow(2_147_000_000) + 1}
            )
        workflow = self._build_workflow(
            request,
            reference_image_name=self._upload_reference_image(request),
        )
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
                    operation=operation,
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
                        "reference_count": len(request.reference_images),
                    },
                    seed=request.seed,
                    request_id=prompt_id,
                )
            self.sleeper(self.poll_interval)
        raise ProviderTimeoutError(
            f"ComfyUI 任务轮询超时（上限 {self.max_poll_seconds:g} 秒）"
        )

    def _build_workflow(
        self,
        request: ImageGenerationRequest,
        *,
        reference_image_name: str = "",
    ) -> dict[str, Any]:
        assert self.workflow is not None
        workflow = copy.deepcopy(self.workflow)
        workflow[self.prompt_node_id].setdefault("inputs", {})["text"] = request.prompt
        for node_id, field, value in (
            (self.width_node_id, "width", request.width),
            (self.height_node_id, "height", request.height),
            (self.seed_node_id, "seed", request.seed),
            (
                self.negative_prompt_node_id,
                "text",
                request.negative_prompt,
            ),
        ):
            if node_id and value is not None:
                if node_id not in workflow:
                    raise ProviderResponseError(f"ComfyUI workflow 缺少节点 {node_id}")
                workflow[node_id].setdefault("inputs", {})[field] = value
        if reference_image_name:
            node_id = self.reference_image_node_id
            if not node_id or node_id not in workflow:
                raise ProviderResponseError(
                    "ComfyUI workflow is missing its reference image node"
                )
            workflow[node_id].setdefault("inputs", {})["image"] = (
                reference_image_name
            )
        elif self.reference_image_node_id:
            self._bypass_reference_adapter(workflow)
        return workflow

    def _bypass_reference_adapter(self, workflow: dict[str, Any]) -> None:
        """Use the checkpoint directly when this request has no reference image."""
        reference_node_id = self.reference_image_node_id
        for adapter_id, adapter in workflow.items():
            if not isinstance(adapter, dict):
                continue
            inputs = adapter.get("inputs")
            if not isinstance(inputs, dict):
                continue
            image_ref = inputs.get("image")
            if (
                "IPAdapter" not in str(adapter.get("class_type", ""))
                or not isinstance(image_ref, (list, tuple))
                or not image_ref
                or str(image_ref[0]) != reference_node_id
            ):
                continue
            loader_ref = inputs.get("model")
            if not isinstance(loader_ref, (list, tuple)) or not loader_ref:
                continue
            loader = workflow.get(str(loader_ref[0]))
            loader_inputs = loader.get("inputs") if isinstance(loader, dict) else None
            base_model_ref = (
                loader_inputs.get("model")
                if isinstance(loader_inputs, dict)
                else None
            )
            if not isinstance(base_model_ref, (list, tuple)) or not base_model_ref:
                continue
            for node in workflow.values():
                node_inputs = node.get("inputs") if isinstance(node, dict) else None
                model_ref = (
                    node_inputs.get("model")
                    if isinstance(node_inputs, dict)
                    else None
                )
                if (
                    isinstance(model_ref, (list, tuple))
                    and model_ref
                    and str(model_ref[0]) == str(adapter_id)
                ):
                    node_inputs["model"] = list(base_model_ref)

    def _upload_reference_image(
        self,
        request: ImageGenerationRequest,
    ) -> str:
        """Upload the first reference to ComfyUI and return its input name."""
        if not request.reference_images:
            return ""
        source = request.reference_images[0]
        try:
            image_bytes = source.read_bytes()
        except OSError as exc:
            raise ProviderResponseError(
                f"Unable to read ComfyUI reference image: {source.name}"
            ) from exc
        if not image_bytes:
            raise ProviderResponseError("The ComfyUI reference image is empty")
        if len(image_bytes) > self.max_download_bytes:
            raise ProviderResponseError(
                "The ComfyUI reference image exceeds the safety size limit"
            )
        content_type = mimetypes.guess_type(source.name)[0] or "image/png"
        upload_name = f"comicforge_{uuid.uuid4().hex}_{source.name}"
        payload, _ = with_retry(
            lambda: self.upload_transport(
                f"{self.base_url}/upload/image",
                {},
                {"type": "input", "overwrite": "false"},
                [("image", (upload_name, image_bytes, content_type))],
                self.timeout,
            ),
            self.retry_policy,
            sleeper=self.sleeper,
        )
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ProviderResponseError(
                "The ComfyUI reference upload response has no filename"
            )
        subfolder = str(payload.get("subfolder", "")).strip().strip("/\\")
        return f"{subfolder}/{name}" if subfolder else name

    @staticmethod
    def _detect_negative_prompt_node(
        workflow: dict[str, Any] | None,
    ) -> str:
        """Find the CLIP text node connected to a sampler's negative input."""
        if not workflow:
            return ""
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            reference = inputs.get("negative")
            if not isinstance(reference, (list, tuple)) or not reference:
                continue
            node_id = str(reference[0])
            candidate = workflow.get(node_id)
            if (
                isinstance(candidate, dict)
                and candidate.get("class_type") == "CLIPTextEncode"
            ):
                return node_id
        return ""

    @staticmethod
    def _detect_reference_image_node(
        workflow: dict[str, Any] | None,
    ) -> str:
        """Find a LoadImage node connected to an IPAdapter image input."""
        if not workflow:
            return ""
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            if "IPAdapter" not in str(node.get("class_type", "")):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            reference = inputs.get("image")
            if not isinstance(reference, (list, tuple)) or not reference:
                continue
            node_id = str(reference[0])
            candidate = workflow.get(node_id)
            if (
                isinstance(candidate, dict)
                and candidate.get("class_type") == "LoadImage"
            ):
                return node_id
        return ""

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


def _nearest_multiple(value: float, multiple: int) -> int:
    return max(multiple, round(value / multiple) * multiple)
