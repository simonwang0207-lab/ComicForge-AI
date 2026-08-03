"""fal queue-based asynchronous image Provider."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from comicforge_ai.models.image_base import (
    ConfigurationError,
    ImageGenerationResult,
    ImageProviderCapabilities,
    ProviderResponseError,
    ProviderTimeoutError,
)
from comicforge_ai.models.image_provider_utils import (
    JsonObject,
    normalized_result,
    with_retry,
)
from comicforge_ai.models.json_image_provider import JsonImageProvider
from comicforge_ai.schemas import ImageGenerationRequest


class FalImageProvider(JsonImageProvider):
    model_id = "fal"
    display_name = "fal Image Queue"
    provider_type = "async_remote_http"
    api_key_environment = "FAL_KEY"
    capabilities = ImageProviderCapabilities(
        text_to_image=True,
        seed=True,
        batch=True,
        async_task=True,
        cancellation=True,
        arbitrary_size=True,
    )
    supported_formats = ("png", "jpeg", "webp")

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://queue.fal.run",
        max_poll_seconds: float = 300,
        poll_interval: float = 1,
        clock: Callable[[], float] = time.monotonic,
        **kwargs: object,
    ) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.max_poll_seconds = max(1, max_poll_seconds)
        self.poll_interval = max(0, poll_interval)
        self.clock = clock
        super().__init__(
            api_key=api_key,
            model=model,
            endpoint=f"{self.base_url}/{model.strip()}",
            **kwargs,
        )

    def request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": "application/json",
        }

    def build_payload(self, request: ImageGenerationRequest) -> JsonObject:
        payload: JsonObject = {
            "prompt": request.prompt,
            "num_images": request.count,
            "output_format": request.output_format,
        }
        if request.width and request.height:
            payload["image_size"] = {
                "width": request.width,
                "height": request.height,
            }
        elif request.aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        if request.seed is not None:
            payload["seed"] = request.seed
        return payload

    def result_entries(self, payload: JsonObject) -> list[dict[str, object]]:
        images = payload.get("images")
        if not isinstance(images, list):
            raise ProviderResponseError("fal 结果缺少 images 图片列表")
        return images

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        status = self.validate_config()
        if not status.configured:
            raise ConfigurationError(status.message)
        self.validate_request(request, operation="text_to_image")
        started = time.perf_counter()
        submit, submit_retries = with_retry(
            lambda: self.transport(
                "POST",
                self.endpoint,
                self.request_headers(),
                self.build_payload(request),
                self.timeout,
            ),
            self.retry_policy,
            sleeper=self.sleeper,
        )
        request_id = str(submit.get("request_id", ""))
        status_url = str(submit.get("status_url", ""))
        response_url = str(submit.get("response_url", ""))
        if not request_id or not status_url or not response_url:
            raise ProviderResponseError("fal 提交响应缺少任务 URL 或 request_id")

        deadline = self.clock() + self.max_poll_seconds
        polls = 0
        while self.clock() < deadline:
            status_payload, _ = with_retry(
                lambda: self.transport(
                    "GET",
                    status_url,
                    self.request_headers(),
                    None,
                    self.timeout,
                ),
                self.retry_policy,
                sleeper=self.sleeper,
            )
            polls += 1
            state = str(status_payload.get("status", "")).upper()
            if state == "COMPLETED":
                if status_payload.get("error"):
                    raise ProviderResponseError("fal 异步任务执行失败")
                result_payload, result_retries = with_retry(
                    lambda: self.transport(
                        "GET",
                        response_url,
                        self.request_headers(),
                        None,
                        self.timeout,
                    ),
                    self.retry_policy,
                    sleeper=self.sleeper,
                )
                result = normalized_result(
                    provider=self.model_id,
                    provider_name=self.display_name,
                    model=request.model or self.model,
                    operation="text_to_image",
                    payload=result_payload,
                    entries=self.result_entries(result_payload),
                    duration=time.perf_counter() - started,
                    output_path=output_path,
                    downloader=self.download_transport,
                    timeout=self.timeout,
                    max_bytes=self.max_download_bytes,
                    actual_parameters={
                        **self.actual_parameters(request),
                        "submit_retries": submit_retries,
                        "result_retries": result_retries,
                        "polls": polls,
                    },
                    seed=self.result_seed(result_payload, request),
                    request_id=request_id,
                )
                return result
            if state not in {"IN_QUEUE", "IN_PROGRESS"}:
                raise ProviderResponseError(f"fal 返回未知任务状态：{state or '空'}")
            self.sleeper(self.poll_interval)
        raise ProviderTimeoutError(
            f"fal 异步任务轮询超时（上限 {self.max_poll_seconds:g} 秒）"
        )
