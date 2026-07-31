from pathlib import Path

from comicforge_ai.service import ComicGenerator


def test_generator_runs_complete_pipeline_and_exports_png(tmp_path: Path) -> None:
    generator = ComicGenerator(output_dir=tmp_path)

    project, page = generator.generate("会飞的书包", "水彩童话", 4)

    assert page.width > 0
    assert page.height > 0
    assert project.output_path is not None
    assert project.output_path.exists()
    assert project.output_path.suffix == ".png"
    assert project.output_path.read_bytes().startswith(b"\x89PNG")

