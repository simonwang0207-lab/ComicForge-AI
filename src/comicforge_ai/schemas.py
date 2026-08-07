"""Pydantic data models shared by every ComicForge component."""

from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


class CharacterProfile(BaseModel):
    """A reusable description of one comic character."""

    name: str = Field(min_length=1, description="角色名称")
    role: str = Field(default="", description="角色在故事中的定位")
    appearance: str = Field(min_length=1, description="外观特征")
    personality: str = Field(min_length=1, description="性格特点")
    visual_prompt: str = Field(default="", description="保持视觉一致性的角色提示词")
    entity_type: str = Field(
        default="",
        description="供绘图使用的通用实体类型，如 human、animal、robot 或 vehicle",
    )
    species_or_category: str = Field(
        default="",
        description="供绘图使用的具体物种、角色类别或物体类别",
    )
    body_structure: str = Field(
        default="",
        description="供绘图使用的稳定身体结构、轮廓或机械结构",
    )
    identity_features: list[str] = Field(
        default_factory=list,
        description="跨分格必须保留的英文视觉身份特征",
    )
    avoid_features: list[str] = Field(
        default_factory=list,
        description="与该角色身份冲突、绘图时应排除的英文特征",
    )
    age: str = Field(default="", description="年龄或年龄段")
    gender: str = Field(default="", description="性别或外观性别表达")
    hairstyle: str = Field(default="", description="发型与发色")
    facial_features: str = Field(default="", description="面部特征")
    clothing: str = Field(default="", description="固定服装")
    signature_items: list[str] = Field(default_factory=list, description="标志性道具")
    era: str = Field(default="", description="所属时代")
    primary_colors: list[str] = Field(default_factory=list, description="角色主色调")


ContentLanguage = Literal["zh-CN", "en", "ja-JP"]
TextItemType = Literal["speech", "thought", "narration", "sfx"]
TextPresentation = Literal["auto", "bubble", "text_only", "caption", "burst"]
LetteringStyle = Literal["immersive", "classic", "minimal"]
LayoutMode = Literal["grid", "webtoon", "adaptive_page", "custom_page"]
CustomFrameType = Literal["square", "portrait", "landscape", "wide"]
PanelComposition = Literal[
    "single",
    "split_horizontal",
    "split_vertical",
    "inset",
    "montage",
]
PanelPosition = Literal[
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_right",
    "bottom_left",
    "bottom_right",
]


class NormalizedPoint(BaseModel):
    """A position inside a panel where both axes use the 0–1 range."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ComicTextItem(BaseModel):
    """One independently rendered comic text element."""

    type: TextItemType
    speaker: str | None = None
    text: str = Field(min_length=1)
    preferred_position: PanelPosition = "top_left"
    speaker_position: PanelPosition | None = None
    speaker_anchor: NormalizedPoint | None = None
    presentation: TextPresentation = Field(
        default="auto",
        description="文字呈现方式；auto 由漫画排字器按文字类型选择",
    )


class PanelTextLocalization(BaseModel):
    """Rendered text snapshot for one panel in one content language."""

    sequence: int = Field(ge=1)
    text_items: list[str] = Field(default_factory=list)


class ComicLocalization(BaseModel):
    """A reusable title and lettering translation that needs no new images."""

    title: str = Field(min_length=1)
    panels: list[PanelTextLocalization] = Field(default_factory=list)


class StoryBibleCharacter(BaseModel):
    """Facts and visual constraints shared by every storyboard panel."""

    name: str = Field(min_length=1)
    identity: str = ""
    appearance: str = ""
    clothing: str = ""
    motivation: str = ""


class StoryBible(BaseModel):
    """Temporary canon used for factual review and visual consistency."""

    time_period: str = ""
    location: str = ""
    characters: list[StoryBibleCharacter] = Field(default_factory=list)
    key_objects: list[str] = Field(default_factory=list)
    timeline: list[str] = Field(default_factory=list)
    visual_style: str = ""
    visual_style_prompt: str = Field(
        default="",
        description="供图像 Provider 使用的英文全项目风格提示词",
    )


class SubShot(BaseModel):
    """An optional secondary shot composed inside one generated panel image."""

    shot_type: str = Field(default="close_up", description="特写、远景、反应镜头等")
    visual_description: str = Field(min_length=1)
    focus: str = ""
    position: PanelPosition = "top_right"


class RevisionTurn(BaseModel):
    """One user-guided script revision retained for continuous collaboration."""

    round: int = Field(ge=1)
    instruction: str = Field(min_length=1)
    result_summary: str = ""


class PanelSpec(BaseModel):
    """Storyboard information for a single panel."""

    sequence: int = Field(
        ge=1,
        validation_alias=AliasChoices("sequence", "number", "index"),
        description="分镜顺序编号",
    )
    page_number: int = Field(default=1, ge=1, description="所属页码")
    scene: str = Field(min_length=1, description="场景与时间地点")
    visual_description: str = Field(default="", description="具体画面构图描述")
    characters: list[str] = Field(default_factory=list, description="出场角色名称")
    action: str = Field(default="", description="角色动作与表情")
    dialogue: str = Field(default="", description="对白")
    narration: str = Field(
        default="",
        validation_alias=AliasChoices("narration", "caption"),
        description="旁白",
    )
    image_prompt: str = Field(default="", description="供图像模型使用的绘图提示词")
    narrative_role: str = Field(default="", description="本格在故事中的叙事作用")
    importance: int = Field(default=3, ge=1, le=5, description="用于自适应版式的视觉重要度")
    composition: PanelComposition = Field(
        default="single",
        description="单镜头或单格内部的分割、插图、蒙太奇构图",
    )
    subshots: list[SubShot] = Field(
        default_factory=list,
        max_length=3,
        description="必要时在同一图片内呈现的辅助镜头",
    )
    character_positions: dict[str, PanelPosition] = Field(
        default_factory=dict,
        description="角色在画面中的大致位置",
    )
    reserved_bubble_regions: list[PanelPosition] = Field(
        default_factory=list,
        description="生图时应保留的干净负空间",
    )
    text_items: list[ComicTextItem] = Field(
        default_factory=list,
        description="对白、思考、旁白和拟声词",
    )
    render_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def migrate_legacy_text(self) -> "PanelSpec":
        """Convert old dialogue/narration strings without breaking old projects."""
        if not self.text_items:
            if self.dialogue.strip():
                speaker, text = _split_legacy_dialogue(self.dialogue)
                self.text_items.append(
                    ComicTextItem(
                        type="speech",
                        speaker=speaker,
                        text=text,
                        preferred_position="top_left",
                        speaker_position="bottom_left",
                        speaker_anchor=NormalizedPoint(x=0.25, y=0.7),
                    )
                )
            if self.narration.strip():
                self.text_items.append(
                    ComicTextItem(
                        type="narration",
                        text=self.narration.strip(),
                        preferred_position="top_right",
                    )
                )
        else:
            if not self.dialogue:
                self.dialogue = " ".join(
                    item.text
                    for item in self.text_items
                    if item.type in {"speech", "thought"}
                )
            if not self.narration:
                self.narration = " ".join(
                    item.text for item in self.text_items if item.type == "narration"
                )
        if not self.reserved_bubble_regions:
            self.reserved_bubble_regions = list(
                dict.fromkeys(item.preferred_position for item in self.text_items)
            )
        return self

    @property
    def number(self) -> int:
        """Backward-compatible day-one name for ``sequence``."""
        return self.sequence

    @property
    def caption(self) -> str:
        """Backward-compatible day-one name for ``narration``."""
        return self.narration


class ComicPage(BaseModel):
    """Optional grouping that allows a project to grow into multiple pages."""

    number: int = Field(ge=1, description="页码")
    panel_sequences: list[int] = Field(min_length=1, description="本页包含的分镜编号")


class CustomPanelFrame(BaseModel):
    """One user-selected frame in a deterministic custom comic page."""

    sequence: int = Field(ge=1, description="对应的分镜编号")
    frame_type: CustomFrameType = Field(
        default="square",
        description="方形/竖幅占半行，横向/超宽画框独占一行",
    )


class ImageGenerationRequest(BaseModel):
    """Provider-independent request for generation and image editing."""

    prompt: str = Field(min_length=1)
    negative_prompt: str = ""
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    aspect_ratio: str = ""
    quality: str = "auto"
    count: int = Field(default=1, ge=1, le=6)
    seed: int | None = Field(default=None, ge=0)
    style: str = ""
    output_format: str = "png"
    reference_images: list[Path] = Field(default_factory=list)
    mask_image: Path | None = None
    strength: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: str = ""
    panel: PanelSpec | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def dimensions_are_paired(self) -> "ImageGenerationRequest":
        if (self.width is None) != (self.height is None):
            raise ValueError("width 和 height 必须同时设置或同时留空")
        return self


# Backward-compatible Stage 3 name used by the comic service and tests.
PanelImageRequest = ImageGenerationRequest


class PanelImageRecord(BaseModel):
    """Persisted provenance for one locally saved panel image."""

    sequence: int = Field(ge=1)
    provider_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    panel_prompt: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    generation_seconds: float = Field(ge=0)
    operation: str = "text_to_image"
    request_id: str = ""
    seed: int | None = None
    actual_parameters: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False
    error_summary: str = ""
    reference_source: str = ""
    reference_panel_sequence: int | None = Field(default=None, ge=1)


class PanelImageVersion(BaseModel):
    """Immutable archived raw-panel revision that can be restored later."""

    sequence: int = Field(ge=1)
    version: int = Field(ge=1)
    local_path: str = Field(min_length=1)
    archived_at: str = Field(min_length=1)
    reason: str = "regeneration"
    record: PanelImageRecord


class ComicProject(BaseModel):
    """All structured information and output metadata for a comic."""

    title: str = Field(min_length=1, description="漫画标题")
    theme: str = Field(min_length=1, description="漫画主题")
    style: str = Field(min_length=1, description="视觉风格")
    panel_count: int = Field(ge=1, description="漫画格数")
    story: str = Field(min_length=1, description="故事梗概")
    characters: list[CharacterProfile] = Field(min_length=1)
    panels: list[PanelSpec] = Field(min_length=1)
    pages: list[ComicPage] = Field(default_factory=list)
    requested_text_provider: str = ""
    requested_text_model: str = ""
    actual_text_provider: str = ""
    actual_text_model: str = ""
    requested_review_provider: str = ""
    requested_review_model: str = ""
    actual_review_provider: str = ""
    actual_review_model: str = ""
    review_applied: bool = False
    requested_image_provider: str = ""
    requested_image_model: str = ""
    image_fallback_used: bool = False
    image_error_summary: str = ""
    panel_images: list[PanelImageRecord] = Field(default_factory=list)
    panel_image_versions: list[PanelImageVersion] = Field(default_factory=list)
    output_path: Path | None = None
    content_language: ContentLanguage = "zh-CN"
    layout_mode: LayoutMode = "grid"
    custom_layout: list[CustomPanelFrame] = Field(
        default_factory=list,
        description="用户选择的画框顺序；仅在 custom_page 模式下参与排版",
    )
    allow_multi_shot_panels: bool = False
    title_candidates: list[str] = Field(default_factory=list, max_length=8)
    revision_history: list[RevisionTurn] = Field(default_factory=list)
    user_story_guidance: str = Field(
        default="",
        description="用户提供的故事事实、人物关系和必须保留的情节约束",
    )
    story_bible: StoryBible = Field(default_factory=StoryBible)
    review_notes: list[str] = Field(default_factory=list)
    script_reviewed: bool = False
    bubble_theme: str = "classic"
    lettering_style: LetteringStyle = "immersive"
    show_panel_numbers: bool = False
    localizations: dict[str, ComicLocalization] = Field(default_factory=dict)

    @model_validator(mode="after")
    def panel_count_matches_specs(self) -> "ComicProject":
        if len(self.panels) != self.panel_count:
            raise ValueError("panels 数量必须与 panel_count 一致")
        expected_numbers = list(range(1, self.panel_count + 1))
        if [panel.sequence for panel in self.panels] != expected_numbers:
            raise ValueError("分镜编号必须从 1 连续递增")
        if self.pages:
            referenced = [
                sequence for page in self.pages for sequence in page.panel_sequences
            ]
            if sorted(referenced) != expected_numbers:
                raise ValueError("pages 必须且只能引用项目中的全部分镜")
        if self.panel_images and [
            image.sequence for image in self.panel_images
        ] != expected_numbers:
            raise ValueError("panel_images 必须按分镜编号从 1 连续记录")
        if self.custom_layout and [
            frame.sequence for frame in self.custom_layout
        ] != expected_numbers:
            raise ValueError("custom_layout 必须按分镜编号从 1 连续记录")
        return self


def _split_legacy_dialogue(value: str) -> tuple[str | None, str]:
    clean = value.strip()
    for separator in ("：", ":"):
        if separator in clean:
            speaker, text = clean.split(separator, maxsplit=1)
            if speaker.strip() and text.strip():
                return speaker.strip(), text.strip().strip("“”\"'")
    return None, clean.strip("“”\"'")
