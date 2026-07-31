"""Deterministic text model used without API keys or network calls."""

from comicforge_ai.schemas import CharacterProfile, ComicProject, PanelSpec


class MockTextModel:
    """Generate a small structured story and storyboard from user input."""

    _beats = (
        ("开场", "主人公在日常环境中发现了一个意外线索。"),
        ("行动", "主人公决定追随线索，迈出大胆的一步。"),
        ("转折", "计划遇到阻碍，伙伴提出了出人意料的办法。"),
        ("结局", "两人化解难题，并用轻松的方式呼应主题。"),
    )

    def generate_project(
        self,
        theme: str,
        style: str,
        panel_count: int = 4,
    ) -> ComicProject:
        """Return a validated comic project with exactly ``panel_count`` panels."""
        clean_theme = theme.strip()
        clean_style = style.strip()
        if not clean_theme:
            raise ValueError("请输入漫画主题")
        if not clean_style:
            raise ValueError("请输入漫画风格")
        if not 1 <= panel_count <= 8:
            raise ValueError("漫画格数必须在 1 到 8 之间")

        characters = [
            CharacterProfile(
                name="小漫",
                appearance=f"圆润轮廓、亮色外套，采用{clean_style}表现",
                personality="好奇、勇敢，偶尔有点冒失",
            ),
            CharacterProfile(
                name="阿格",
                appearance=f"方形小机器人，带有{clean_style}装饰纹理",
                personality="冷静、可靠，喜欢说俏皮话",
            ),
        ]

        panels: list[PanelSpec] = []
        for index in range(panel_count):
            beat_name, beat_text = self._beat_for(index, panel_count)
            panels.append(
                PanelSpec(
                    number=index + 1,
                    scene=f"{beat_name}：围绕“{clean_theme}”，{beat_text}",
                    caption=f"{clean_style}画面 · 第 {index + 1} 格",
                    dialogue=self._dialogue_for(index, panel_count),
                )
            )

        return ComicProject(
            title=f"《{clean_theme}的一天》",
            theme=clean_theme,
            style=clean_style,
            panel_count=panel_count,
            story=(
                f"小漫和阿格围绕“{clean_theme}”展开一次小冒险。"
                "故事从偶然发现开始，经过尝试与转折，最终温暖收束。"
            ),
            characters=characters,
            panels=panels,
        )

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

