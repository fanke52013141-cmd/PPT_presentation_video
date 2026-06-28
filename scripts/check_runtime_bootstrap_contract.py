"""Validate the reduced backend-only runtime bootstrap contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    bootstrap = (ROOT / "runtime_bootstrap.py").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    required_modules = (
        "runtime_ai_mask",
        "runtime_storyboard_background",
        "runtime_step3_image_style",
        "runtime_step3_image_style_state",
        "runtime_one_click_orchestrator",
        "runtime_diagnostics",
    )
    for module in required_modules:
        assert f'"{module}"' in bootstrap, f"runtime module missing: {module}"
    for obsolete in (
        "runtime_step5_flush_bridge",
        "runtime_step2_storyboard_settings",
        "runtime_visual_draft_quality_ui",
        "runtime_one_click_ui_cache_buster",
    ):
        assert obsolete not in bootstrap, f"obsolete runtime module still loaded: {obsolete}"
    for script in (
        "project_profile_extension.js",
        "storyboard_background_extension.js",
        "style_reference_manager_extension.js",
        "ai_mask_extension.js",
        "one_click_extension.js",
    ):
        assert script in html, f"direct script declaration missing: {script}"
    print("runtime bootstrap contract passed")


if __name__ == "__main__":
    main()
