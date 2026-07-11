"""Validate the reduced backend-only runtime bootstrap contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    bootstrap = (ROOT / "runtime_bootstrap.py").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    required_modules: tuple[str, ...] = ()
    for module in required_modules:
        assert f'"{module}"' in bootstrap, f"runtime module missing: {module}"
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "one_click_orchestrator._register" in server, "one-click routes are not explicitly registered"
    assert "diagnostics_routes._register" in server, "diagnostics route is not explicitly registered"
    assert "storyboard_background._register" in server, "storyboard background routes are not explicitly registered"
    assert "register_project_style_routes" in server, "project style routes are not explicitly registered"
    assert "runtime_ai_mask._register" in server, "AI Mask routes are not explicitly registered"
    assert '"runtime_one_click_orchestrator"' not in bootstrap, "one-click still depends on runtime bootstrap"
    assert '"runtime_diagnostics"' not in bootstrap, "diagnostics still depends on runtime bootstrap"
    assert '"runtime_storyboard_background"' not in bootstrap, "storyboard background still depends on runtime bootstrap"
    assert '"runtime_project_profile"' not in bootstrap, "project profile still depends on runtime bootstrap"
    assert '"runtime_step3_image_style"' not in bootstrap, "Step 3 image style still depends on runtime bootstrap"
    assert '"runtime_ai_mask"' not in bootstrap, "AI Mask still depends on runtime bootstrap"
    assert "RUNTIME_MODULES: list[str] = []" in bootstrap, "runtime bootstrap module list is not empty"
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
