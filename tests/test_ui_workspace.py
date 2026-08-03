from comicforge_ai.ui import _APP_CSS, create_demo


def test_workspace_registers_fit_and_width_preview_modes() -> None:
    config = create_demo().get_config_file()
    components = config["components"]

    preview = next(
        item
        for item in components
        if item.get("props", {}).get("elem_id") == "comic-preview"
    )
    view_mode = next(
        item
        for item in components
        if item.get("props", {}).get("label") == "预览方式"
    )
    scripts = [item.get("js") or "" for item in config["dependencies"]]
    component_ids = {
        item.get("props", {}).get("elem_id") for item in components
    }

    assert preview["props"]["elem_classes"] == ["cf-preview-fit"]
    assert view_mode["props"]["choices"] == [
        ("整页预览", "fit"),
        ("放大阅读", "width"),
    ]
    assert any("cf-preview-width" in script for script in scripts)
    assert all(
        item.get("props", {}).get("label") != "界面" for item in components
    )
    assert {
        "cf-flow-heading",
        "cf-flow-note",
        "cf-canvas-heading",
        "cf-preview-mode",
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
    assert labels["固定随机结果"]["visible"] is False
    assert labels["角色或画风参考图（可多选）"]["visible"] is False
    assert labels["局部修改范围图（白色区域会被修改）"]["visible"] is False

    download_labels = {
        item.get("props", {}).get("label")
        for item in components
        if item.get("type") == "downloadbutton"
    }
    assert "↓ 导出 PDF" in download_labels


def test_workspace_preview_uses_an_independent_viewport() -> None:
    assert "height: min(68vh, 820px)" in _APP_CSS
    assert "#comic-preview.cf-preview-width img" in _APP_CSS
    assert "overflow-y: auto" in _APP_CSS
    assert ".cf-dark-mode" not in _APP_CSS
    assert "background: #f5f7fb" in _APP_CSS
    assert "#cf-flow-heading" in _APP_CSS
    assert "#cf-flow-note" in _APP_CSS
    assert "#cf-canvas-heading" in _APP_CSS
    assert "#cf-preview-mode" in _APP_CSS
    assert "#cf-preview-help" in _APP_CSS
    assert ".cf-canvas-shell .form" in _APP_CSS
    assert ".cf-canvas-shell > div" in _APP_CSS
    assert ".cf-canvas-shell div:has(#comic-preview)" in _APP_CSS
    assert "#comic-preview > div" in _APP_CSS
    assert ".cf-revision-card .form" in _APP_CSS
    assert "#cf-revision-heading" in _APP_CSS
    assert "--block-background-fill: #ffffff" in _APP_CSS
