from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND_UI = (ROOT / "static" / "storyboard_background_extension.js").read_text(encoding="utf-8")
STYLE_UI = (ROOT / "static" / "style_reference_manager_extension.js").read_text(encoding="utf-8")
BACKGROUND_RUNTIME = (ROOT / "runtime_storyboard_background.py").read_text(encoding="utf-8")
STYLE_RUNTIME = (ROOT / "runtime_step3_image_style.py").read_text(encoding="utf-8")


def test_background_modal_has_image_and_solid_modes():
    assert 'data-mode-card="image"' in BACKGROUND_UI
    assert 'data-mode-card="solid"' in BACKGROUND_UI


def test_background_preview_is_strict_16_by_9():
    assert "aspect-ratio:16 / 9" in BACKGROUND_UI
    assert "16:9 预览" in BACKGROUND_UI


def test_background_runtime_preserves_original_for_refitting():
    assert 'ORIGINAL_IMAGE_NAME = "storyboard_background_original.png"' in BACKGROUND_RUNTIME
    assert "_render_background_image(run_dir, config[\"image_fit\"])" in BACKGROUND_RUNTIME


def test_image_style_modal_has_three_product_modes():
    for tab in ('template', 'manual', 'reverse'):
        assert f'data-style-tab="{tab}"' in STYLE_UI
    assert "System Content" in STYLE_UI
    assert "效果预览" in STYLE_UI


def test_style_previews_are_16_by_9_and_template_refs_are_readable():
    assert "aspect-ratio:16 / 9" in STYLE_UI
    assert "会作为后续图片生成的实际参考图" in STYLE_UI
    assert '"/api/image-style/project-templates/{template_id}"' in STYLE_RUNTIME
    assert '"/api/image-style/project-templates/{template_id}/reference-images/{index}"' in STYLE_RUNTIME
    assert "上传图片已成为本次生成的实际参考图" in STYLE_UI
    assert "请先生成或上传至少 1 张效果预览" in STYLE_RUNTIME
