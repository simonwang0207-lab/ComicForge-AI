from pathlib import Path

from comicforge_ai.models import MockTextModel, TextModelRegistry
from comicforge_ai.models.base import TextModelRequestError
from comicforge_ai.models.ollama_text import OllamaTextModel
from comicforge_ai.service import ComicGenerator


def test_real_provider_failure_explicitly_falls_back_to_mock(tmp_path: Path) -> None:
    def failing_transport(*args: object, **kwargs: object) -> dict[str, object]:
        raise TextModelRequestError("测试中的模拟连接失败")

    registry = TextModelRegistry(
        [
            MockTextModel(),
            OllamaTextModel(
                base_url="http://127.0.0.1:11434",
                model="not-running",
                transport=failing_transport,
            ),
        ]
    )
    generator = ComicGenerator(
        registry=registry,
        output_dir=tmp_path,
        fallback_to_mock=True,
    )

    result = generator.generate_with_status("离线回退测试", "清新治愈", 3, "ollama")

    assert result.fallback_used is True
    assert result.requested_provider_id == "ollama"
    assert result.actual_provider_id == "mock"
    assert "模拟连接失败" in result.fallback_reason
    assert result.project.output_path is not None
    assert result.project.output_path.exists()


def test_mock_supports_non_four_or_eight_panel_count() -> None:
    project = MockTextModel().generate_project("十三格故事", "科幻霓虹", 13)

    assert project.panel_count == 13
    assert len(project.panels) == 13
    assert project.panels[-1].sequence == 13
