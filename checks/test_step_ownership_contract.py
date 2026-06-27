"""Guard Step ownership wording and routes.

New flows should present storyboard style as Step 2-owned and image style as
Step 3-owned. Legacy Project Profile routes remain for compatibility, but new UI
and Step 3 state bridges must not reintroduce project-level image-style controls.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STRICT_FILES = [
    "static/style_reference_manager_extension.js",
    "static/image_style_reverse_extension.js",
    "static/step2_storyboard_settings_extension.js",
    "runtime_step3_image_style.py",
    "runtime_step3_image_style_state.py",
    "runtime_step2_storyboard_settings.py",
    "runtime_one_click_step3_style_patch.py",
]

FORBIDDEN_SNIPPETS = [
    "Project Profile 图片风格",
    "项目级风格参考图",
    "项目级图片风格",
    "project-level image style",
    "Project Profile image_style_profile",
    "/project-profile/image-style",
]

REQUIRED_STEP3_SNIPPETS = {
    "static/style_reference_manager_extension.js": [
        "/steps/3/image-style",
        "'/reference-images'",
        "Step 3 图片风格",
    ],
    "static/image_style_reverse_extension.js": [
        "/steps/3/image-style",
        "Step 3：上传示例图反推图片风格",
    ],
    "runtime_step3_image_style_state.py": [
        "step3_image_style.json",
        "Step 3 当前图片风格",
    ],
    "runtime_step3_image_style.py": [
        "step3_image_style.json",
        "style_state",
        "_save_step3_style_state",
    ],
}

REQUIRED_SELF_CONTAINED_STYLE_PANEL_SNIPPETS = [
    "style-panel-reverse-files",
    "btn-style-panel-reverse-run",
    "renderInlineReversePreview",
    "renderInlineReverseResult",
    "apiPostForm(step3ImageStyleUrl(projectId, '/reverse'), form)",
    "apiPost(step3ImageStyleUrl(projectId, '/reference-images/generate'), { count: 3 })",
    "window.refreshStep3Prompts",
]

FORBIDDEN_STYLE_PANEL_BRIDGE_SNIPPETS = [
    "reverseButton.click()",
    "openReversePanel",
    "反推风格面板还没有加载完成",
]

REQUIRED_REVERSE_FALLBACK_SNIPPETS = [
    "step3-btn-image-style-panel",
    "document.getElementById('step3-btn-image-style-reverse')?.remove();",
    "兼容入口：新的主入口是 Step 3 工具栏里的“图片风格”。",
]

REQUIRED_ONE_CLICK_STEP3_STYLE_SNIPPETS = [
    "检查 Step 3 图片风格参考图",
    "Step 3 图片风格参考图已就绪；自动流程不会从项目创建配置生成参考图",
    "STAGE_TITLE_OVERRIDES",
    "_normalize_status_titles",
    "no_project_profile_style_refs",
]

FORBIDDEN_ONE_CLICK_STEP3_STYLE_SNIPPETS = [
    "检查项目级风格参考图",
    "项目级风格参考图",
    "Project style references",
]

REQUIRED_ONE_CLICK_UI_SNIPPETS = [
    "一键生成会读取当前各步骤配置",
    "Step 2 分镜设置",
    "Step 3 图片风格/参考图",
    "Step 5 Mask 设置",
    "它不会从创建项目弹窗定义分镜或图片风格",
    "复用当前 Step 2/3/5 配置",
]

FORBIDDEN_CREATE_WIZARD_CONTROLS = [
    "name=\"storyboard_template_id\"",
    "name=\"image_style_template_id\"",
    "name=\"auto_generate_image_style\"",
    "id=\"project-profile-style-references\"",
    "btn-image-style-reverse",
]

FORBIDDEN_STEP3_ALIAS_SNIPPETS = [
    "_apply_style_to_project(",
    '"profile":',
    "'profile':",
]


def read_text(path: str) -> str:
    full_path = ROOT / path
    if not full_path.exists():
        raise AssertionError(f"Required file is missing: {path}")
    return full_path.read_text(encoding="utf-8")


def test_new_flows_do_not_use_legacy_image_style_routes_or_wording() -> None:
    offenders: list[str] = []
    for path in STRICT_FILES:
        content = read_text(path)
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in content:
                offenders.append(f"{path}: {snippet}")
    if offenders:
        raise AssertionError("Legacy project-level image-style route/wording leaked into new Step 2/3 flow:\n" + "\n".join(offenders))


def test_step3_ui_uses_step3_image_style_routes_and_labels() -> None:
    offenders: list[str] = []
    for path, snippets in REQUIRED_STEP3_SNIPPETS.items():
        content = read_text(path)
        for snippet in snippets:
            if snippet not in content:
                offenders.append(f"{path}: missing {snippet}")
    if offenders:
        raise AssertionError("Step 3 image style ownership contract failed:\n" + "\n".join(offenders))


def test_step3_image_style_panel_is_self_contained() -> None:
    content = read_text("static/style_reference_manager_extension.js")
    missing = [snippet for snippet in REQUIRED_SELF_CONTAINED_STYLE_PANEL_SNIPPETS if snippet not in content]
    forbidden = [snippet for snippet in FORBIDDEN_STYLE_PANEL_BRIDGE_SNIPPETS if snippet in content]
    problems = []
    if missing:
        problems.append("Missing self-contained Step 3 image style panel snippets:\n" + "\n".join(missing))
    if forbidden:
        problems.append("Step 3 image style panel must not bridge through hidden reverse button:\n" + "\n".join(forbidden))
    if problems:
        raise AssertionError("\n\n".join(problems))


def test_reverse_style_extension_is_only_a_fallback_entry() -> None:
    content = read_text("static/image_style_reverse_extension.js")
    missing = [snippet for snippet in REQUIRED_REVERSE_FALLBACK_SNIPPETS if snippet not in content]
    if missing:
        raise AssertionError("Reverse style extension must stay a fallback when the unified Step 3 panel exists:\n" + "\n".join(missing))


def test_one_click_uses_step3_image_style_wording() -> None:
    content = read_text("runtime_one_click_step3_style_patch.py")
    missing = [snippet for snippet in REQUIRED_ONE_CLICK_STEP3_STYLE_SNIPPETS if snippet not in content]
    forbidden = [snippet for snippet in FORBIDDEN_ONE_CLICK_STEP3_STYLE_SNIPPETS if snippet in content]
    problems = []
    if missing:
        problems.append("Missing One-click Step 3 style wording snippets:\n" + "\n".join(missing))
    if forbidden:
        problems.append("One-click Step 3 style patch must not expose legacy project-level wording:\n" + "\n".join(forbidden))
    if problems:
        raise AssertionError("\n\n".join(problems))


def test_one_click_ui_explains_current_step_settings() -> None:
    content = read_text("static/one_click_extension.js")
    missing = [snippet for snippet in REQUIRED_ONE_CLICK_UI_SNIPPETS if snippet not in content]
    if missing:
        raise AssertionError("One-click UI must explain that automation reads current Step settings:\n" + "\n".join(missing))


def test_create_project_wizard_has_no_style_controls() -> None:
    content = read_text("static/project_profile_extension.js")
    offenders = [snippet for snippet in FORBIDDEN_CREATE_WIZARD_CONTROLS if snippet in content]
    if offenders:
        raise AssertionError("Create project wizard must not expose style ownership controls:\n" + "\n".join(offenders))


def test_step3_alias_reverse_writes_step3_state_not_project_profile() -> None:
    content = read_text("runtime_step3_image_style.py")
    offenders = [snippet for snippet in FORBIDDEN_STEP3_ALIAS_SNIPPETS if snippet in content]
    if offenders:
        raise AssertionError("Step 3 reverse alias must write step3_image_style.json, not Project Profile:\n" + "\n".join(offenders))


if __name__ == "__main__":
    test_new_flows_do_not_use_legacy_image_style_routes_or_wording()
    test_step3_ui_uses_step3_image_style_routes_and_labels()
    test_step3_image_style_panel_is_self_contained()
    test_reverse_style_extension_is_only_a_fallback_entry()
    test_one_click_uses_step3_image_style_wording()
    test_one_click_ui_explains_current_step_settings()
    test_create_project_wizard_has_no_style_controls()
    test_step3_alias_reverse_writes_step3_state_not_project_profile()
    print("Step ownership wording contract passed.")
