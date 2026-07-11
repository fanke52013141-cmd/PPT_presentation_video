"""Guard ownership of the six visible production steps."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    html = read_text("static/index.html")
    create_ui = read_text("static/project_profile_extension.js")
    style_ui = read_text("static/style_reference_manager_extension.js")
    one_click_ui = read_text("static/one_click_extension.js")
    one_click_backend = read_text("one_click_orchestrator.py")
    step3_backend = read_text("runtime_step3_image_style.py")

    for script in (
        "project_profile_extension.js",
        "storyboard_background_extension.js",
        "style_reference_manager_extension.js",
        "ai_mask_extension.js",
        "one_click_extension.js",
    ):
        assert script in html, f"frontend script must be declared directly: {script}"

    for deleted_script in (
        "step2_storyboard_settings_extension.js",
        "image_style_reverse_extension.js",
        "visual_draft_quality_extension.js",
    ):
        assert deleted_script not in html

    assert "step2-btn-script-prompt" in html
    assert "step2-btn-visual-prompt" in html
    assert "step3-btn-background-settings" in read_text("static/storyboard_background_extension.js")
    assert "step3-video-background-apply" not in html

    for token in (
        "/steps/3/image-style",
        "style-panel-system-content",
        "style-panel-reverse-files",
        "style-panel-upload-files",
        "style-panel-template-name",
        "最多只能上传 3 张",
    ):
        assert token in style_ui, f"Step 3 image-style flow missing: {token}"
    assert "/project-profile/image-style" not in style_ui
    assert "step3_image_style_templates" in step3_backend

    for forbidden in (
        'name="storyboard_template_id"',
        'name="image_style_template_id"',
        'name="auto_generate_image_style"',
    ):
        assert forbidden not in create_ui

    assert "/steps/2/script/execute" in one_click_backend
    assert "/steps/2/visual/execute" in one_click_backend
    assert "/steps/2/compose" in one_click_backend
    assert "/steps/5/ai-mask/annotate" in one_click_backend
    assert 'client.put(f"/api/projects/{project_id}/steps/6/result"' in one_click_backend
    assert "图片质量检查" not in one_click_ui
    assert "project-profile/image-style" not in one_click_backend
    print("Step ownership wording contract passed.")


if __name__ == "__main__":
    main()
