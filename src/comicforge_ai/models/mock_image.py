"""Pillow-based placeholder image model."""

from __future__ import annotations

import platform
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from comicforge_ai.models.image_base import (
    ImageGeneration,
    ImageModelStatus,
    ImageProvider,
    ImageProviderCapabilities,
    ImageSaveError,
    UnsupportedCapabilityError,
)
from comicforge_ai.schemas import ImageGenerationRequest, PanelSpec


class MockImageModel(ImageProvider):
    """Render numbered storyboard placeholders instead of calling an image model."""

    model_id = "mock-image"
    display_name = "Mock Image（Pillow 占位图）"
    provider_type = "mock"

    _backgrounds = (
        "#FFF1CC",
        "#DDF4FF",
        "#E9E0FF",
        "#DDF7E5",
        "#FFE1E8",
        "#F3E6D1",
        "#DCE8FF",
        "#F5E1F7",
    )

    def __init__(self, width: int = 720, height: int = 480) -> None:
        self.width = width
        self.height = height
        self.title_font = self._load_font(36, bold=True)
        self.body_font = self._load_font(28)
        self.small_font = self._load_font(22)
        self.number_font = self._load_font(32, bold=True)

    @property
    def model_name(self) -> str:
        return "pillow-placeholder-v1"

    def check_availability(self) -> ImageModelStatus:
        return self.validate_config()

    def validate_config(self) -> ImageModelStatus:
        return ImageModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=True,
            available=True,
            message="内置 Pillow 占位图片始终可用",
        )

    def get_capabilities(self) -> ImageProviderCapabilities:
        return ImageProviderCapabilities(
            text_to_image=True,
            seed=True,
            arbitrary_size=True,
        )

    def generate(
        self,
        request: ImageGenerationRequest,
        output_path: Path | None = None,
    ) -> ImageGeneration:
        started = time.perf_counter()
        if request.panel is None:
            raise ImageSaveError("Mock 漫画占位图需要分镜信息")
        self.validate_request(request, operation="text_to_image")
        image = self.generate_visual_panel(request.panel)
        target_size = (self.width, self.height)
        if request.width and request.height:
            target_size = (request.width, request.height)
        elif request.aspect_ratio:
            target_size = self._size_from_ratio(request.aspect_ratio)
        if image.size != target_size:
            image = image.resize(target_size, Image.Resampling.LANCZOS)
        output_paths: list[Path] = []
        if output_path is not None:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                image.save(output_path, format="PNG")
                output_paths.append(output_path)
            except OSError as exc:
                raise ImageSaveError(
                    f"Mock 分镜图片保存失败：{output_path.name}"
                ) from exc
        return ImageGeneration(
            images=[image],
            provider=self.model_id,
            model=self.model_name,
            provider_name=self.display_name,
            duration=time.perf_counter() - started,
            seed=request.seed,
            actual_parameters={
                "width": target_size[0],
                "height": target_size[1],
                "style": request.style,
            },
            raw_metadata={"mock": True},
            output_paths=output_paths,
        )

    def generate_visual_panel(self, panel: PanelSpec) -> Image.Image:
        """Create a text-free offline background for bubble/layout testing."""
        image = Image.new(
            "RGB",
            (self.width, self.height),
            self._backgrounds[(panel.sequence - 1) % len(self._backgrounds)],
        )
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (0, int(self.height * 0.7), self.width, self.height),
            fill="#B8D8C0",
        )
        positions = list(panel.character_positions.values()) or [
            "bottom_left",
            "bottom_right",
        ]
        for index, position in enumerate(positions[:3]):
            center_x = int(self.width * (0.25 if "left" in position else 0.75))
            if "center" in position:
                center_x = self.width // 2
            center_y = int(self.height * (0.56 if "top" in position else 0.66))
            color = ("#FF8E72", "#5A7DCE", "#8B5FBF")[index % 3]
            draw.ellipse(
                (center_x - 52, center_y - 105, center_x + 52, center_y - 1),
                fill=color,
                outline="#273043",
                width=4,
            )
            draw.ellipse(
                (center_x - 34, center_y - 145, center_x + 34, center_y - 77),
                fill="#FFD7B5",
                outline="#273043",
                width=4,
            )
        return image

    def _size_from_ratio(self, value: str) -> tuple[int, int]:
        separator = ":" if ":" in value else "x" if "x" in value.lower() else ""
        if not separator:
            raise UnsupportedCapabilityError(f"无法识别尺寸或宽高比：{value}")
        left, right = value.lower().split(separator, maxsplit=1)
        try:
            width_ratio = float(left)
            height_ratio = float(right)
        except ValueError as exc:
            raise UnsupportedCapabilityError(f"无法识别尺寸或宽高比：{value}") from exc
        if width_ratio <= 0 or height_ratio <= 0:
            raise UnsupportedCapabilityError(f"尺寸或宽高比必须为正数：{value}")
        if separator == "x" and width_ratio >= 64 and height_ratio >= 64:
            return int(width_ratio), int(height_ratio)
        return self.width, max(64, round(self.width * height_ratio / width_ratio))

    def generate_panel(self, panel: PanelSpec, style: str) -> Image.Image:
        """Create one colorful placeholder panel containing its storyboard text."""
        image = Image.new(
            "RGB",
            (self.width, self.height),
            self._backgrounds[(panel.number - 1) % len(self._backgrounds)],
        )
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle(
            (16, 16, self.width - 16, self.height - 16),
            radius=24,
            outline="#273043",
            width=5,
        )
        draw.ellipse((32, 30, 100, 98), fill="#273043")
        number_text = str(panel.number)
        number_box = draw.textbbox((0, 0), number_text, font=self.number_font)
        number_width = number_box[2] - number_box[0]
        draw.text(
            (66 - number_width / 2, 42),
            number_text,
            font=self.number_font,
            fill="white",
        )

        draw.text((120, 38), f"分镜 {panel.number}", font=self.title_font, fill="#273043")
        draw.rounded_rectangle(
            (42, 120, self.width - 42, self.height - 92),
            radius=18,
            fill="#FFFFFFCC",
        )

        y = 146
        y = self._draw_wrapped(
            draw,
            panel.scene,
            (70, y),
            self.width - 140,
            self.body_font,
            "#273043",
            line_spacing=10,
        )
        if panel.dialogue:
            y += 20
            self._draw_wrapped(
                draw,
                panel.dialogue,
                (70, y),
                self.width - 140,
                self.small_font,
                "#9C2C43",
                line_spacing=7,
            )

        footer = f"MOCK IMAGE · {style} · {panel.narration}"
        self._draw_wrapped(
            draw,
            footer,
            (42, self.height - 70),
            self.width - 84,
            self.small_font,
            "#48556A",
            line_spacing=4,
            max_lines=1,
        )
        return image

    @staticmethod
    def _font_candidates(bold: bool) -> list[Path]:
        candidates: list[Path] = []
        system = platform.system()
        if system == "Windows":
            font_dir = Path("C:/Windows/Fonts")
            candidates.extend(
                [
                    font_dir / ("msyhbd.ttc" if bold else "msyh.ttc"),
                    font_dir / ("simhei.ttf" if bold else "simsun.ttc"),
                ]
            )
        elif system == "Darwin":
            candidates.extend(
                [
                    Path("/System/Library/Fonts/PingFang.ttc"),
                    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
                ]
            )
        else:
            candidates.extend(
                [
                    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
                    if bold
                    else Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                ]
            )
        return candidates

    def _load_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        for path in self._font_candidates(bold):
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        return ImageFont.truetype("DejaVuSans.ttf", size=size)

    @staticmethod
    def _split_to_lines(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
    ) -> list[str]:
        lines: list[str] = []
        current = ""
        for character in text:
            candidate = current + character
            box = draw.textbbox((0, 0), candidate, font=font)
            if current and box[2] - box[0] > max_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    def _draw_wrapped(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        position: tuple[int, int],
        max_width: int,
        font: ImageFont.FreeTypeFont,
        fill: str,
        line_spacing: int,
        max_lines: int | None = None,
    ) -> int:
        lines = self._split_to_lines(draw, text, font, max_width)
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and draw.textlength(last + "…", font=font) > max_width:
                last = last[:-1]
            lines[-1] = last + "…"

        x, y = position
        line_height = font.getbbox("示例Ag")[3] - font.getbbox("示例Ag")[1]
        for line in lines:
            draw.text((x, y), line, font=font, fill=fill)
            y += line_height + line_spacing
        return y
