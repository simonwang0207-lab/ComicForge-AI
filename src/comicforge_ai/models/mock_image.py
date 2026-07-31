"""Pillow-based placeholder image model."""

from __future__ import annotations

import platform
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from comicforge_ai.schemas import PanelSpec


class MockImageModel:
    """Render numbered storyboard placeholders instead of calling an image model."""

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

        footer = f"MOCK IMAGE · {style} · {panel.caption}"
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

