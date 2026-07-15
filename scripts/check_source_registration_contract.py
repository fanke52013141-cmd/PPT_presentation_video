"""Validate that production services are registered explicitly at startup."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert not (ROOT / "runtime_bootstrap.py").exists(), "empty runtime bootstrap should stay retired"
    assert "one_click_orchestrator._register" in server, "one-click routes are not explicitly registered"
    assert "diagnostics_routes._register" in server, "diagnostics route is not explicitly registered"
    assert "storyboard_background._register" in server, "storyboard background routes are not explicitly registered"
    assert "register_project_style_routes" in server, "project style routes are not explicitly registered"
    assert "runtime_ai_mask._register" in server, "AI Mask routes are not explicitly registered"
    for script in (
        "project_profile_extension.js",
        "storyboard_background_extension.js",
        "style_reference_manager_extension.js",
        "ai_mask_extension.js",
        "one_click_extension.js",
    ):
        assert script in html, f"direct script declaration missing: {script}"
    print("explicit source registration contract passed")


if __name__ == "__main__":
    main()
