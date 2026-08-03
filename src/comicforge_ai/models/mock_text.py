"""Deterministic text provider used without API keys or network calls."""

from comicforge_ai.models.base import TextModelProvider, TextModelStatus
from comicforge_ai.schemas import (
    CharacterProfile,
    ComicProject,
    ComicTextItem,
    ContentLanguage,
    LayoutMode,
    NormalizedPoint,
    PanelSpec,
    StoryBible,
    StoryBibleCharacter,
    SubShot,
)


class MockTextModel(TextModelProvider):
    """Generate a small structured story and storyboard from user input."""

    model_id = "mock"
    display_name = "Mock 文本模型（离线）"
    provider_type = "mock"

    _beats = (
        ("开场", "主人公在日常环境中发现了一个意外线索。"),
        ("行动", "主人公决定追随线索，迈出大胆的一步。"),
        ("转折", "计划遇到阻碍，伙伴提出了出人意料的办法。"),
        ("结局", "两人化解难题，并用轻松的方式呼应主题。"),
    )

    @property
    def model_name(self) -> str:
        return "comicforge-template-v2"

    def check_availability(self) -> TextModelStatus:
        return TextModelStatus(
            model_id=self.model_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            configured=True,
            available=True,
            message="始终可用；不访问网络，不需要 API Key。",
        )

    def generate_project(
        self,
        theme: str,
        style: str,
        panel_count: int = 4,
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "grid",
        allow_multi_shot_panels: bool = False,
        source_story: str = "",
    ) -> ComicProject:
        """Return a validated comic project with exactly ``panel_count`` panels."""
        clean_theme = theme.strip()
        clean_style = style.strip()
        if not clean_theme:
            raise ValueError("请输入漫画主题")
        if not clean_style:
            raise ValueError("请输入漫画风格")
        if panel_count < 1:
            raise ValueError("漫画格数必须是正整数")

        characters = [
            CharacterProfile(
                name="小漫",
                role="主角",
                appearance=f"圆润轮廓、亮色外套，采用{clean_style}表现",
                personality="好奇、勇敢，偶尔有点冒失",
                visual_prompt=f"小漫，圆润轮廓，亮色外套，{clean_style}漫画角色",
            ),
            CharacterProfile(
                name="阿格",
                role="伙伴",
                appearance=f"方形小机器人，带有{clean_style}装饰纹理",
                personality="冷静、可靠，喜欢说俏皮话",
                visual_prompt=f"阿格，方形小机器人，装饰纹理，{clean_style}漫画角色",
            ),
        ]

        panels: list[PanelSpec] = []
        for index in range(panel_count):
            beat_name, beat_text = self._beat_for(index, panel_count)
            bubble_position = ("top_left", "top_right", "top_left", "top_right")[
                index % 4
            ]
            speaker_position = "bottom_right" if "left" in bubble_position else "bottom_left"
            dialogue = self._localized_dialogue(index, panel_count, language)
            narration = self._localized_narration(index, language)
            panels.append(
                PanelSpec(
                    sequence=index + 1,
                    scene=f"{beat_name}：围绕“{clean_theme}”，{beat_text}",
                    visual_description=(
                        f"{clean_style}漫画画面，小漫与阿格位于与“{clean_theme}”"
                        f"相关的场景中，以清晰构图表现{beat_name}情节。"
                    ),
                    characters=["小漫", "阿格"],
                    action=self._action_for(index, panel_count),
                    dialogue=dialogue,
                    narration=narration,
                    narrative_role=beat_name,
                    importance=5 if index == panel_count - 1 else 3,
                    composition=(
                        "inset"
                        if allow_multi_shot_panels and index == panel_count // 2
                        else "single"
                    ),
                    subshots=(
                        [
                            SubShot(
                                shot_type="reaction_close_up",
                                visual_description="伙伴对关键转折作出清晰表情反应",
                                focus="角色表情",
                                position="top_right",
                            )
                        ]
                        if allow_multi_shot_panels and index == panel_count // 2
                        else []
                    ),
                    character_positions={
                        "小漫": speaker_position,
                        "阿格": "bottom_left" if speaker_position == "bottom_right" else "bottom_right",
                    },
                    reserved_bubble_regions=[bubble_position],
                    text_items=[
                        ComicTextItem(
                            type="speech",
                            speaker="小漫" if index == 0 else "阿格",
                            text=dialogue.split("：", maxsplit=1)[-1],
                            preferred_position=bubble_position,
                            speaker_position=speaker_position,
                            speaker_anchor=NormalizedPoint(
                                x=0.75 if speaker_position == "bottom_right" else 0.25,
                                y=0.72,
                            ),
                        ),
                        ComicTextItem(
                            type="narration",
                            text=narration,
                            preferred_position="top_right"
                            if bubble_position != "top_right"
                            else "top_left",
                        ),
                    ],
                    image_prompt=(
                        f"{clean_style}漫画，小漫（圆润轮廓、亮色外套）和阿格"
                        f"（方形小机器人），{beat_text}，画面清晰，角色一致；"
                        f"人物位于{speaker_position}，{bubble_position}保留干净低细节负空间；"
                        "画面中不要出现文字、字母、标题、水印或现成气泡"
                    ),
                )
            )

        title, story = self._localized_title_story(clean_theme, language)
        clean_source_story = source_story.strip()
        if len(clean_source_story) > 20000:
            raise ValueError("故事或剧本原文不能超过 20000 个字符")
        if clean_source_story:
            story = clean_source_story
        return ComicProject(
            title=title,
            theme=clean_theme,
            style=clean_style,
            panel_count=panel_count,
            story=story,
            characters=characters,
            panels=panels,
            content_language=language,
            layout_mode=layout_mode,
            allow_multi_shot_panels=allow_multi_shot_panels,
            user_story_guidance=clean_source_story,
            title_candidates=[
                title,
                f"{clean_theme}：关键一刻",
                f"围绕{clean_theme}的一天",
            ],
            story_bible=StoryBible(
                time_period="当代",
                location=f"与“{clean_theme}”相关的统一场景",
                characters=[
                    StoryBibleCharacter(
                        name="小漫",
                        identity="好奇的主角",
                        appearance="圆润轮廓、亮色外套",
                        clothing="固定亮色外套",
                        motivation="与伙伴一起解决问题",
                    ),
                    StoryBibleCharacter(
                        name="阿格",
                        identity="可靠的机器人伙伴",
                        appearance="方形小机器人",
                        clothing="统一装饰纹理外壳",
                        motivation="冷静协助小漫",
                    ),
                ],
                key_objects=[clean_theme],
                timeline=[panel.narrative_role for panel in panels],
                visual_style=clean_style,
            ),
        )

    def generate_reviewed_project(
        self,
        theme: str,
        style: str,
        panel_count: int,
        language: ContentLanguage = "zh-CN",
        layout_mode: LayoutMode = "grid",
        allow_multi_shot_panels: bool = False,
        source_story: str = "",
    ) -> ComicProject:
        project = self.generate_project(
            theme,
            style,
            panel_count,
            language,
            layout_mode,
            allow_multi_shot_panels,
            source_story,
        )
        project.script_reviewed = True
        project.review_notes = [
            "已检查角色连续性、因果关系、动作可视化和气泡台词长度。",
            "Mock 模式使用确定性模板，不进行外部事实核查。",
        ]
        return project

    def revise_project_with_guidance(
        self,
        project: ComicProject,
        user_guidance: str,
    ) -> ComicProject:
        """Provide a deterministic offline revision that visibly retains guidance."""
        clean_guidance = user_guidance.strip()
        if not clean_guidance:
            raise ValueError("请先描述正确的故事细节或必须遵守的情节")

        revised = self.generate_project(
            project.theme,
            project.style,
            project.panel_count,
            project.content_language,
            project.layout_mode,
            project.allow_multi_shot_panels,
        )
        cumulative_guidance = (
            f"{project.user_story_guidance}\n{clean_guidance}"
            if project.user_story_guidance
            else clean_guidance
        )
        revised.user_story_guidance = cumulative_guidance
        revised.story = cumulative_guidance
        revised.script_reviewed = True
        revised.review_notes = [
            "已记录用户提供的故事依据，并据此重建完整分镜结构。",
            "Mock 模式只能进行确定性模板演示，不能核实历史或原著事实。",
        ]
        revised.story_bible.timeline = [
            f"用户故事依据：{cumulative_guidance}",
            *[panel.narrative_role for panel in revised.panels],
        ]
        for panel in revised.panels:
            panel.scene = f"依据用户故事说明设计：{panel.scene}"
            panel.image_prompt = (
                f"用户故事依据：{cumulative_guidance}；{panel.image_prompt}"
            )
        return revised

    def _beat_for(self, index: int, panel_count: int) -> tuple[str, str]:
        if panel_count == 1:
            return "完整故事", "主人公发现问题、灵机一动，并开心地解决了它。"
        beat_index = round(index * (len(self._beats) - 1) / (panel_count - 1))
        return self._beats[beat_index]

    @staticmethod
    def _dialogue_for(index: int, panel_count: int) -> str:
        if panel_count == 1:
            return "小漫：原来答案一直就在身边！"
        if index == 0:
            return "小漫：咦？我们去看看吧！"
        if index == panel_count - 1:
            return "阿格：任务完成，收工！"
        return "阿格：别急，我有一个好主意。"

    def _localized_dialogue(
        self,
        index: int,
        panel_count: int,
        language: ContentLanguage,
    ) -> str:
        if language == "en":
            if index == 0:
                return "Manga: Let's take a look!"
            if index == panel_count - 1:
                return "Ager: We did it!"
            return "Ager: I have an idea."
        if language == "ja-JP":
            if index == 0:
                return "マンガ：見に行こう！"
            if index == panel_count - 1:
                return "アグ：やったね！"
            return "アグ：いい考えがあるよ。"
        return self._dialogue_for(index, panel_count)

    @staticmethod
    def _localized_narration(index: int, language: ContentLanguage) -> str:
        if language == "en":
            return ("A clue appears.", "They take action.", "A surprise!", "Problem solved.")[
                index % 4
            ]
        if language == "ja-JP":
            return ("手がかりを発見。", "二人は動き出す。", "思わぬ展開！", "無事に解決。")[
                index % 4
            ]
        return ("线索出现。", "他们开始行动。", "意外的转折！", "问题解决。")[
            index % 4
        ]

    @staticmethod
    def _localized_title_story(
        theme: str,
        language: ContentLanguage,
    ) -> tuple[str, str]:
        if language == "en":
            return (
                theme,
                (
                    f"Manga and Ager follow a clue about {theme}, face a surprise, "
                    "and solve the problem together."
                ),
            )
        if language == "ja-JP":
            return (
                f"『{theme}』",
                f"マンガとアグは「{theme}」の手がかりを追い、思わぬ展開を経て問題を解決する。",
            )
        return (
            f"《{theme}》",
            f"小漫和阿格围绕“{theme}”展开小冒险，经历发现、行动、转折并解决问题。",
        )

    @staticmethod
    def _action_for(index: int, panel_count: int) -> str:
        if panel_count == 1:
            return "小漫举起找到的答案，阿格在旁边开心鼓掌。"
        if index == 0:
            return "小漫惊讶地指向线索，阿格转身观察。"
        if index == panel_count - 1:
            return "两人击掌庆祝，神情轻松。"
        return "小漫向前尝试，阿格冷静地给出建议。"
