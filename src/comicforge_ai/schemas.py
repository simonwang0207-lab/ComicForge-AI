"""Pydantic data models for comic projects."""

from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class CharacterProfile(BaseModel):
    """A reusable description of one comic character."""

    name: str = Field(min_length=1, description="角色名称")
    appearance: str = Field(min_length=1, description="外观特征")
    personality: str = Field(min_length=1, description="性格特点")


class PanelSpec(BaseModel):
    """Storyboard information for a single panel."""

    number: int = Field(ge=1, description="分镜编号")
    scene: str = Field(min_length=1, description="画面描述")
    caption: str = Field(default="", description="旁白")
    dialogue: str = Field(default="", description="对白")


class ComicProject(BaseModel):
    """All structured information and output metadata for a comic."""

    title: str = Field(min_length=1, description="漫画标题")
    theme: str = Field(min_length=1, description="漫画主题")
    style: str = Field(min_length=1, description="视觉风格")
    panel_count: int = Field(ge=1, le=8, description="漫画格数")
    story: str = Field(min_length=1, description="故事梗概")
    characters: list[CharacterProfile] = Field(min_length=1)
    panels: list[PanelSpec] = Field(min_length=1)
    output_path: Path | None = None

    @model_validator(mode="after")
    def panel_count_matches_specs(self) -> "ComicProject":
        if len(self.panels) != self.panel_count:
            raise ValueError("panels 数量必须与 panel_count 一致")
        expected_numbers = list(range(1, self.panel_count + 1))
        if [panel.number for panel in self.panels] != expected_numbers:
            raise ValueError("分镜编号必须从 1 连续递增")
        return self

