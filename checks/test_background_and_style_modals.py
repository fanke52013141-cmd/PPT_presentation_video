from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND_UI = (ROOT / "static" / "storyboard_background_extension.js").read_text(encoding="utf-8")
STYLE_UI = (ROOT / "static" / "style_reference_manager_extension.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
BACKGROUND_RUNTIME = (ROOT / "storyboard_background.py").read_text(encoding="utf-8")
STYLE_RUNTIME = (
    (ROOT / "project_style_routes.py").read_text(encoding="utf-8")
    + (ROOT / "project_style_template_service.py").read_text(encoding="utf-8")
)


def test_background_modal_has_image_and_solid_modes():
    assert 'data-mode-card="image"' in BACKGROUND_UI
    assert 'data-mode-card="solid"' in BACKGROUND_UI


def test_background_preview_follows_project_canvas():
    assert ".storyboard-bg-preview" in STYLE_CSS
    assert "aspect-ratio:var(--project-aspect-ratio,16 / 9)" in STYLE_CSS
    assert "${canvasAspectLabel()} 预览" in BACKGROUND_UI
    assert "${canvasSizeLabel()}" in BACKGROUND_UI


def test_background_runtime_preserves_original_for_refitting():
    assert 'ORIGINAL_IMAGE_NAME = "storyboard_background_original.png"' in BACKGROUND_RUNTIME
    assert '_render_background_image(run_dir, config["image_fit"], get_project_canvas(project))' in BACKGROUND_RUNTIME


def test_image_style_modal_has_three_product_modes():
    for tab in ('template', 'manual', 'reverse'):
        assert f'data-style-tab="{tab}"' in STYLE_UI
    assert "System Content" in STYLE_UI
    assert "效果预览" in STYLE_UI


def test_style_previews_follow_project_canvas_and_template_refs_are_readable():
    assert ".style-ref-card" in STYLE_CSS
    assert "aspect-ratio:var(--project-aspect-ratio,16 / 9)" in STYLE_CSS
    assert "会作为后续图片生成的实际参考图" in STYLE_UI
    assert '"/api/image-style/project-templates/{template_id}"' in STYLE_RUNTIME
    assert '"/api/image-style/project-templates/{template_id}/reference-images/{index}"' in STYLE_RUNTIME
    assert "上传图片已成为本次生成的实际参考图" in STYLE_UI
    assert "请先生成或上传至少 1 张效果预览" in STYLE_RUNTIME


def test_builtin_handdrawn_style_has_system_content_and_previews():
    assert 'BUILTIN_HANDDRAWN_TEMPLATE_ID = "handdrawn"' in STYLE_RUNTIME
    assert 'BUILTIN_HANDDRAWN_TEMPLATE_NAME = "手绘风格"' in STYLE_RUNTIME
    assert '"system_content": system_content' in STYLE_RUNTIME
    assert '"built_in": True' in STYLE_RUNTIME
    assert '"PPT模板.png"' in STYLE_RUNTIME
    assert '"PPT示例.png"' in STYLE_RUNTIME
    assert "selectedTemplateId: 'handdrawn'" in STYLE_UI
    assert "STATE.templates.find(item => item.built_in" in STYLE_UI
    assert "!item.built_in" in STYLE_UI
