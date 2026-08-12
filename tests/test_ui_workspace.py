from comicforge_ai.models import MockTextModel
from comicforge_ai.service import ComicGenerator
from comicforge_ai.ui import (
    _APP_CSS,
    _storyboard_rows,
    append_reference_image_for_ui,
    clear_reference_images_for_ui,
    create_demo,
    reference_file_order_markdown,
    reference_upload_guide,
    regenerate_panel_for_ui,
    restore_panel_version_for_ui,
)


def test_workspace_registers_scrollable_fullscreen_preview() -> None:
    config = create_demo().get_config_file()
    components = config["components"]

    preview = next(
        item
        for item in components
        if item.get("props", {}).get("elem_id") == "comic-preview"
    )
    scripts = [item.get("js") or "" for item in config["dependencies"]]
    component_ids = {
        item.get("props", {}).get("elem_id") for item in components
    }

    assert preview["props"]["elem_classes"] == ["cf-preview-fit"]
    assert all(
        item.get("props", {}).get("label") != "预览方式"
        for item in components
    )
    assert all("cf-preview-width" not in script for script in scripts)
    assert any("requestFullscreen" in script for script in scripts)
    assert any("addEventListener('wheel'" in script for script in scripts)
    assert any("addEventListener('pointermove'" in script for script in scripts)
    assert any("addEventListener('dblclick'" in script for script in scripts)
    assert "cf-fullscreen-button" in component_ids
    assert all(
        item.get("props", {}).get("label") != "界面" for item in components
    )
    assert {
        "cf-flow-heading",
        "cf-flow-note",
        "cf-canvas-heading",
        "cf-preview-help",
        "cf-revision-heading",
    }.issubset(component_ids)

    labels = {
        item.get("props", {}).get("label"): item.get("props", {})
        for item in components
        if item.get("props", {}).get("label")
    }
    assert "宽度" not in labels
    assert "高度" not in labels
    assert "尺寸或宽高比" not in labels
    assert "Negative prompt" not in labels
    assert "Seed（0/空表示随机）" not in labels
    assert labels["不希望画面出现的内容"]["visible"] is False
    assert labels["系统随机 Seed"]["visible"] is False
    assert labels["有序角色参考图（可批量导入并拖动排序）"][
        "allow_reordering"
    ] is True
    assert labels["有序角色参考图（可批量导入并拖动排序）"]["height"] == 300
    assert "选择要调整顺序的图片" not in labels
    assert labels["粘贴或导入一张参考图"]["sources"] == [
        "clipboard",
        "upload",
    ]
    assert labels["局部修改范围图"]["visible"] is False

    download_labels = {
        item.get("props", {}).get("label")
        for item in components
        if item.get("type") == "downloadbutton"
    }
    assert "↓ 导出 PDF" in download_labels


def test_workspace_preview_uses_an_independent_viewport() -> None:
    assert "height: min(68vh, 820px)" in _APP_CSS
    assert "#comic-preview.cf-preview-width img" not in _APP_CSS
    assert ".cf-canvas-shell:fullscreen" in _APP_CSS
    assert ".cf-canvas-shell:fullscreen #comic-preview img" in _APP_CSS
    assert "cursor: grab" in _APP_CSS
    assert "#cf-reference-files .file-preview" in _APP_CSS
    assert "overflow-y: auto !important" in _APP_CSS
    assert ".cf-dark-mode" not in _APP_CSS
    assert "background: #f5f7fb" in _APP_CSS
    assert "#cf-flow-heading" in _APP_CSS
    assert "#cf-flow-note" in _APP_CSS
    assert "#cf-canvas-heading" in _APP_CSS
    assert "#cf-preview-mode" not in _APP_CSS
    assert "#cf-preview-help" in _APP_CSS
    assert ".cf-canvas-shell .form" in _APP_CSS
    assert ".cf-canvas-shell > div" in _APP_CSS
    assert ".cf-canvas-shell div:has(#comic-preview)" in _APP_CSS
    assert "#comic-preview > div" in _APP_CSS
    assert ".cf-revision-card .form" in _APP_CSS
    assert "#cf-revision-heading" in _APP_CSS
    assert "--block-background-fill: #ffffff" in _APP_CSS


def test_workspace_uses_side_settings_navigation_and_one_notice() -> None:
    config = create_demo().get_config_file()
    components = config["components"]
    component_ids = [
        item.get("props", {}).get("elem_id") for item in components
    ]

    assert {
        "cf-project-summary",
        "cf-open-content",
        "cf-open-page",
        "cf-open-models",
        "cf-open-lettering",
        "cf-settings-content",
        "cf-settings-page",
        "cf-settings-models",
        "cf-settings-lettering",
        "cf-global-notice",
        "cf-open-advanced-settings",
        "cf-advanced-settings-panel",
        "cf-close-advanced-settings",
    }.issubset(component_ids)
    assert component_ids.count("cf-global-notice") == 1
    assert ".cf-action-primary button" in _APP_CSS
    assert ".cf-action-danger button" in _APP_CSS
    assert ".cf-global-notice" in _APP_CSS
    assert ".cf-advanced-settings" in _APP_CSS
    assert ".cf-image-settings-trigger button" in _APP_CSS
    assert ".cf-modal-close button" in _APP_CSS
    assert "0 0 0 100vmax" in _APP_CSS
    assert "max-height: 150px" not in _APP_CSS
    assert "max-height: min(88dvh, 860px) !important" in _APP_CSS
    assert "overflow-y: auto !important" in _APP_CSS
    assert ".cf-advanced-settings > .styler" in _APP_CSS
    assert "overflow: visible !important" in _APP_CSS

    scripts = [item.get("js") or "" for item in config["dependencies"]]
    assert any("outsideHandler" in script for script in scripts)
    assert any("event.key === 'Escape'" in script for script in scripts)

    settings_button = next(
        item
        for item in components
        if item.get("props", {}).get("elem_id") == "cf-open-advanced-settings"
    )
    image_model = next(
        item
        for item in components
        if item.get("props", {}).get("label") == "具体图片模型"
    )
    fallback_provider = next(
        item
        for item in components
        if item.get("props", {}).get("label") == "失败时备用图片服务"
    )
    assert settings_button["type"] == "button"
    assert settings_button["props"]["value"] == "图片设置"
    assert image_model["type"] == "radio"
    assert fallback_provider["type"] == "radio"

    labels = {
        item.get("props", {}).get("label"): item
        for item in components
        if item.get("props", {}).get("label")
    }
    assert "回退到历史版本" in labels
    assert any(
        item.get("type") == "button"
        and item.get("props", {}).get("value") == "↶ 恢复这一格的历史版本"
        for item in components
    )


def test_storyboard_rows_prefer_chinese_review_text() -> None:
    project = MockTextModel().generate_project("一只猫第一次坐地铁", "清新治愈", 1)
    project.panels[0].visual_description = (
        "Wide shot of a modern subway platform with a small orange cat"
    )
    project.panels[0].scene = "清晨的现代地铁站台"
    project.panels[0].action = "小橘猫探头观察车门"

    assert _storyboard_rows(project)[0][1] == "清晨的现代地铁站台；小橘猫探头观察车门"


def test_storyboard_rows_do_not_treat_mixed_english_as_chinese() -> None:
    project = MockTextModel().generate_project("哪吒闹海", "清新治愈", 1)
    project.panels[0].scene = "天空中，哪吒与敖丙对决"
    project.panels[0].visual_description = (
        "High angle shot of which吒 flying while敖丙 raises a spear"
    )
    project.panels[0].action = "Which吒 dodges waves"

    assert _storyboard_rows(project)[0][1] == "天空中，哪吒与敖丙对决"


def test_panel_regeneration_and_restore_callbacks_return_fresh_preview(
    tmp_path,
) -> None:
    generator = ComicGenerator(output_dir=tmp_path)
    generated = generator.generate_with_status(
        "前端单格版本",
        "清新治愈",
        2,
        provider_id="mock",
        image_provider_id="mock-image",
    )
    rows = _storyboard_rows(generated.project)

    regenerated = regenerate_panel_for_ui(
        generated.project.model_dump(mode="json"),
        rows,
        1,
        "mock",
        "mock-image",
        "",
        "",
        "auto",
        None,
        "png",
        None,
        None,
        False,
        "",
        "classic",
        "immersive",
        True,
        False,
        True,
        generator,
    )

    assert regenerated[1] is not None
    assert regenerated[3].endswith("comic.png")
    assert "历史版本 v1" in regenerated[6]

    restored = restore_panel_version_for_ui(
        regenerated[0],
        rows,
        1,
        1,
        "classic",
        "immersive",
        True,
        False,
        True,
        generator,
    )

    assert restored[1] is not None
    assert restored[3].endswith("comic.png")
    assert "已恢复到 v1" in restored[6]


def test_reference_upload_guide_uses_story_bible_order() -> None:
    project = MockTextModel().generate_project("双角色", "漫画", 2)

    guide = reference_upload_guide(project.model_dump(mode="json"))

    first = project.characters[0].name
    second = project.characters[1].name
    assert f"1. `{first}`" in guide
    assert f"2. `{second}`" in guide
    assert guide.index(first) < guide.index(second)
    assert "文件名" not in guide
    assert "多人同格会暂时停用参考图" in guide


def test_clipboard_reference_is_appended_to_ordered_list() -> None:
    ordered, cleared = append_reference_image_for_ui(
        "second.png",
        ["first.png"],
    )

    assert ordered == ["first.png", "second.png"]
    assert cleared is None
    assert clear_reference_images_for_ui() == (None, None)


def test_empty_clipboard_reference_does_not_put_uploaders_in_error_state(
    monkeypatch,
) -> None:
    warnings: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "comicforge_ai.ui.gr.Warning",
        lambda message, duration: warnings.append((message, duration)),
    )

    ordered, cleared = append_reference_image_for_ui(None, ["first.png"])

    assert ordered == ["first.png"]
    assert cleared is None
    assert warnings == [("请先粘贴或导入一张角色参考图。", 3)]


def test_actual_reference_file_order_is_visible_with_character_binding() -> None:
    project = MockTextModel().generate_project("双角色", "漫画", 2)
    state = project.model_dump(mode="json")

    order = reference_file_order_markdown(
        state,
        ["C:/uploads/哪吒.jpg", "C:/uploads/敖丙.png"],
    )

    assert "#### 当前已导入顺序" in order
    assert f"1. `哪吒.jpg` → **{project.characters[0].name}**" in order
    assert f"2. `敖丙.png` → **{project.characters[1].name}**" in order
    assert order.index("哪吒.jpg") < order.index("敖丙.png")


def test_reference_upload_area_has_fixed_scrollable_height() -> None:
    assert "#cf-reference-files" in _APP_CSS
    assert "max-height: 320px !important" in _APP_CSS
    assert "#cf-reference-files .file-preview-holder" in _APP_CSS
    assert "min-height: 120px !important" in _APP_CSS
    assert "#cf-reference-files .file-preview" in _APP_CSS
    assert "overflow-y: auto !important" in _APP_CSS
