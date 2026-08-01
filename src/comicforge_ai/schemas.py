"""Pydantic data models shared by every ComicForge component."""

from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field, model_validator


class CharacterProfile(BaseModel):
    """A reusable description of one comic character."""

    name: str = Field(min_length=1, description="角色名称")
    role: str = Field(default="", description="角色在故事中的定位")
    appearance: str = Field(min_length=1, description="外观特征")
    personality: str = Field(min_length=1, description="性格特点")
    visual_prompt: str = Field(default="", description="保持视觉一致性的角色提示词")


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
    output_path: Path | None = None

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
        return self
