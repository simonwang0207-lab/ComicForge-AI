"""Unified image-provider interfaces, results, statuses, and safe errors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from comicforge_ai.schemas import ImageGenerationRequest


class ImageModelError(RuntimeError):
    """Base class for user-presentable image-model failures."""


class ImageModelConfigurationError(ImageModelError):
    """Raised when required image-provider settings are missing or invalid."""


class ImageModelRequestError(ImageModelError):
    """Remote request failure with timing and credential-safe diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        elapsed_seconds: float | None = None,
        original_exception: BaseException | None = None,
    ) -> None:
        self.message = message
        self.elapsed_seconds = elapsed_seconds
        self.original_exception = original_exception
        diagnostics: list[str] = []
        if elapsed_seconds is not None:
            diagnostics.append(f"耗时 {elapsed_seconds:.2f} 秒")
        if original_exception is not None:
            diagnostics.append(f"原始异常类型：{type(original_exception).__name__}")
        suffix = f"（{'；'.join(diagnostics)}）" if diagnostics else ""
        super().__init__(message + suffix)


class ImageModelConnectionError(ImageModelRequestError):
    """Raised when the image service cannot be reached."""


class ImageModelGenerationTimeoutError(ImageModelRequestError):
    """Raised when image generation exceeds the configured read timeout."""


class ImageModelHttpError(ImageModelRequestError):
    """Raised for a non-success image-service HTTP response."""

    def __init__(
        self,
        status_code: int,
        detail: str = "",
        *,
        elapsed_seconds: float | None = None,
        original_exception: BaseException | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        message = f"图片服务 HTTP 请求失败（状态码 {status_code}）"
        if detail:
            message += f"：{detail}"
        super().__init__(
            message,
            elapsed_seconds=elapsed_seconds,
            original_exception=original_exception,
        )


class ImageModelResponseError(ImageModelError):
    """Raised when response JSON has no supported image field."""


class ImageDownloadError(ImageModelRequestError):
    """Raised when a returned image URL cannot be downloaded."""


class ImageDecodeError(ImageModelError):
    """Raised when base64 image data cannot be decoded."""


class InvalidGeneratedImageError(ImageModelError):
    """Raised when returned bytes are not a valid image."""


class ImageSaveError(ImageModelError):
    """Raised when a generated image or project record cannot be saved."""


class ConfigurationError(ImageModelConfigurationError):
    """Provider configuration is missing or invalid."""


class AuthenticationError(ImageModelRequestError):
    """Provider rejected the configured credential."""


class InsufficientBalanceError(ImageModelRequestError):
    """Provider account does not have enough balance or quota."""


class RateLimitError(ImageModelRequestError):
    """Provider rate limit was reached."""


class ProviderTimeoutError(ImageModelGenerationTimeoutError):
    """Provider request or async task exceeded its deadline."""


class ProviderResponseError(ImageModelRequestError):
    """Provider returned an invalid response or server-side failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        elapsed_seconds: float | None = None,
        original_exception: BaseException | None = None,
    ) -> None:
        self.status_code = status_code
        super().__init__(
            message,
            elapsed_seconds=elapsed_seconds,
            original_exception=original_exception,
        )


class ContentPolicyError(ImageModelRequestError):
    """Provider rejected a prompt or image under its safety policy."""


class UnsupportedCapabilityError(ImageModelError):
    """The selected provider cannot honor a requested capability."""


@dataclass(frozen=True, slots=True)
class ImageProviderCapabilities:
    """Machine-readable feature flags used by validation and Gradio."""

    text_to_image: bool = True
    image_to_image: bool = False
    multi_reference: bool = False
    mask_edit: bool = False
    inpainting: bool = False
    outpainting: bool = False
    negative_prompt: bool = False
    seed: bool = False
    batch: bool = False
    async_task: bool = False
    cancellation: bool = False
    arbitrary_size: bool = False
    transparent_background: bool = False
    quality: bool = False
    strength: bool = False

    def enabled(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in self.__dataclass_fields__
            if bool(getattr(self, name))
        )


@dataclass(frozen=True, slots=True)
class ImageModelDefinition:
    """One selectable provider/model entry for dynamic UI controls."""

    provider_id: str
    model_id: str
    display_name: str
    capabilities: ImageProviderCapabilities
    supported_sizes: tuple[str, ...] = ()
    supported_formats: tuple[str, ...] = ("png",)
    default_parameters: dict[str, Any] | None = None
    requires_async_polling: bool = False
    supports_reference_images: bool = False
    supports_image_edit: bool = False


@dataclass(frozen=True, slots=True)
class ImageModelStatus:
    """Image-provider status suitable for service and UI layers."""

    model_id: str
    display_name: str
    provider_type: str
    model_name: str
    configured: bool
    available: bool
    message: str
    missing_settings: tuple[str, ...] = ()
    connect_timeout: float = 0
    generation_timeout: float = 0


@dataclass(slots=True)
class ImageGenerationResult:
    """Normalized image result with compatibility properties for Stage 3."""

    images: list[Image.Image]
    provider: str
    model: str
    operation: str = "text_to_image"
    request_id: str = ""
    seed: int | None = None
    revised_prompt: str = ""
    duration: float = 0
    actual_parameters: dict[str, Any] | None = None
    fallback_used: bool = False
    raw_metadata: dict[str, Any] | None = None
    errors: list[str] | None = None
    provider_name: str = ""
    output_paths: list[Path] | None = None

    @property
    def image(self) -> Image.Image:
        if not self.images:
            raise ProviderResponseError("图片 Provider 没有返回图片")
        return self.images[0]

    @property
    def output_path(self) -> Path | None:
        return self.output_paths[0] if self.output_paths else None

    @property
    def provider_id(self) -> str:
        return self.provider

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def elapsed_seconds(self) -> float:
        return self.duration


# Stage 3 public name retained for compatibility.
ImageGeneration = ImageGenerationResult


class ImageProvider(ABC):
    """Common contract implemented by Mock and remote image providers."""

    model_id: str
    display_name: str
    provider_type: str
    prompt_profile: str = "neutral"
    uses_local_accelerator: bool = False
    auto_reference_from_first_panel: bool = False
    restrict_reference_to_portrait_panels: bool = False

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the configured model name without exposing credentials."""

    def check_availability(self) -> ImageModelStatus:
        """Backward-compatible alias for ``health_check``."""
        return self.health_check()

    def get_capabilities(self) -> ImageProviderCapabilities:
        """Return supported operations and optional parameters."""
        return ImageProviderCapabilities()

    def get_prompt_profile(self) -> str:
        """Return the prompt strategy used for this Provider/model family."""
        return self.prompt_profile

    def preferred_generation_size(
        self,
        target_aspect_ratio: float,
    ) -> tuple[int, int] | None:
        """Return a Provider-specific safe size or defer to generic sizing."""
        return None

    def model_definitions(self) -> list[ImageModelDefinition]:
        capabilities = self.get_capabilities()
        return [
            ImageModelDefinition(
                provider_id=self.model_id,
                model_id=self.model_name,
                display_name=self.model_name,
                capabilities=capabilities,
                supported_sizes=tuple(getattr(self, "supported_sizes", ())),
                supported_formats=tuple(getattr(self, "supported_formats", ("png",))),
                requires_async_polling=capabilities.async_task,
                supports_reference_images=capabilities.image_to_image,
                supports_image_edit=capabilities.image_to_image,
            )
        ]

    @abstractmethod
    def validate_config(self) -> ImageModelStatus:
        """Validate required local configuration without a paid request."""

    def health_check(self) -> ImageModelStatus:
        """Return provider configuration/health without generating an image."""
        return self.validate_config()

    @abstractmethod
    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        """Generate one panel and save a local image suitable for composition."""

    def edit(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        """Edit reference images or raise an explicit capability error."""
        raise UnsupportedCapabilityError(
            f"{self.display_name} 不支持图片编辑"
        )

    def normalize_result(
        self,
        payload: dict[str, Any],
        request: ImageGenerationRequest,
        *,
        operation: str,
        output_path: Path | None = None,
    ) -> ImageGenerationResult:
        """Normalize provider payload or raise a clear response error."""
        raise UnsupportedCapabilityError(
            f"{self.display_name} 未实现结果标准化"
        )

    def redact_secrets(self, value: str) -> str:
        """Remove configured credentials and bearer tokens from diagnostics."""
        import re

        safe = value
        for secret in self._secret_values():
            if secret:
                safe = safe.replace(secret, "[REDACTED]")
        return re.sub(
            r"(?:Bearer|Key)\s+[A-Za-z0-9._~+/=-]+",
            lambda match: match.group(0).split()[0] + " [REDACTED]",
            safe,
            flags=re.IGNORECASE,
        )

    def _secret_values(self) -> tuple[str, ...]:
        return tuple(
            str(value)
            for name in ("api_key", "token")
            if (value := getattr(self, name, ""))
        )

    def validate_request(
        self,
        request: ImageGenerationRequest,
        *,
        operation: str,
    ) -> None:
        """Reject unsupported parameters rather than silently dropping them."""
        capabilities = self.get_capabilities()
        checks = (
            (bool(request.reference_images), "image_to_image", "参考图"),
            (len(request.reference_images) > 1, "multi_reference", "多参考图"),
            (request.mask_image is not None, "mask_edit", "Mask 编辑"),
            (bool(request.negative_prompt), "negative_prompt", "Negative prompt"),
            (request.seed is not None, "seed", "Seed"),
            (request.count > 1, "batch", "批量生成"),
            (request.quality != "auto", "quality", "质量等级"),
            (request.strength is not None, "strength", "编辑强度"),
        )
        if operation == "text_to_image" and not capabilities.text_to_image:
            raise UnsupportedCapabilityError(f"{self.display_name} 不支持文生图")
        if operation == "edit" and not capabilities.image_to_image:
            raise UnsupportedCapabilityError(f"{self.display_name} 不支持图片编辑")
        for requested, capability, label in checks:
            if requested and not bool(getattr(capabilities, capability)):
                raise UnsupportedCapabilityError(
                    f"{self.display_name} 不支持参数：{label}"
                )
        definition = self.model_definitions()[0]
        if (
            request.output_format
            and request.output_format not in definition.supported_formats
        ):
            raise UnsupportedCapabilityError(
                f"{self.display_name} 不支持输出格式：{request.output_format}"
            )
        requested_size = (
            f"{request.width}x{request.height}"
            if request.width and request.height
            else request.aspect_ratio
        )
        if (
            requested_size
            and not capabilities.arbitrary_size
            and requested_size not in definition.supported_sizes
        ):
            raise UnsupportedCapabilityError(
                f"{self.display_name} 不支持尺寸：{requested_size}"
            )
