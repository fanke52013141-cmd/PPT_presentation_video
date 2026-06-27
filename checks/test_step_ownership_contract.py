"""Guard user-facing Step ownership wording.

New flows should present storyboard style as Step 2-owned and image style as
Step 3-owned. Legacy Project Profile routes remain for compatibility, but new UI
and Step 3 state bridges must not reintroduce project-level image-style wording.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STRICT_FILES = [
    "static/project_profile_extension.js",
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
]

REQUIRED_STEP3_SNIPPETS = {
    "static/style_reference_manager_extension.js": [
        "/steps/3/image-style/reference-images",
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
}


def read_text(path: str) -> str:
    full_path = ROOT / path
    if not full_path.exists():
        raise AssertionError(f"Required file is missing: {path}")
    return full_path.read_text(encoding="utf-8")


def test_new_flows_do_not_use_project_profile_image_style_wording() -> None:
    offenders: list[str] = []
    for path in STRICT_FILES:
        content = read_text(path)
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in content:
                offenders.append(f"{path}: {snippet}")
    if offenders:
        raise AssertionError("Legacy project-level image-style wording leaked into new Step 2/3 flow:\n" + "\n".join(offenders))


def test_step3_ui_uses_step3_image_style_routes_and_labels() -> None:
    offenders: list[str] = []
    for path, snippets in REQUIRED_STEP3_SNIPPETS.items():
        content = read_text(path)
        for snippet in snippets:
            if snippet not in content:
                offenders.append(f"{path}: missing {snippet}")
    if offenders:
        raise AssertionError("Step 3 image style ownership contract failed:\n" + "\n".join(offenders))


def test_create_project_wizard_is_lightweight() -> None:
    content = read_text("static/project_profile_extension.js")
    forbidden_form_labels = ["分镜风格", "图片风格", "风格参考图", "AI 生成图片风格"]
    offenders = [label for label in forbidden_form_labels if label in content]
    if offenders:
        raise AssertionError("Create project wizard must not expose style ownership controls: " + ", ".join(offenders))


if __name__ == "__main__":
    test_new_flows_do_not_use_project_profile_image_style_wording()
    test_step3_ui_uses_step3_image_style_routes_and_labels()
    test_create_project_wizard_is_lightweight()
    print("Step ownership wording contract passed.")
