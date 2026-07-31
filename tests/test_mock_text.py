import pytest

from comicforge_ai.models import MockTextModel
from comicforge_ai.schemas import ComicProject


def test_mock_text_model_builds_valid_four_panel_project() -> None:
    project = MockTextModel().generate_project("机器人学做饭", "科幻霓虹", 4)

    assert isinstance(project, ComicProject)
    assert project.theme == "机器人学做饭"
    assert project.panel_count == 4
    assert len(project.characters) == 2
    assert [panel.number for panel in project.panels] == [1, 2, 3, 4]


@pytest.mark.parametrize("theme", ["", "   "])
def test_mock_text_model_rejects_empty_theme(theme: str) -> None:
    with pytest.raises(ValueError, match="主题"):
        MockTextModel().generate_project(theme, "水彩童话", 4)

