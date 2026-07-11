from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import project_style_routes
import runtime_bootstrap
import server


def test_style_modules_are_explicit_and_ordered() -> None:
    names = [name for name, _register in project_style_routes.REGISTRATION_STEPS]
    assert names == [
        "project_profile",
        "project_profile_lightweight",
        "project_profile_templates_override",
        "project_style_references",
        "project_style_reference_manager",
        "project_style_reference_step3",
        "image_style_reverse",
        "step3_image_style",
        "step3_image_style_state",
    ]
    assert runtime_bootstrap.RUNTIME_MODULES == []


def test_critical_style_routes_are_present() -> None:
    route_methods = {
        (getattr(route, "path", ""), method)
        for route in server.app.routes
        for method in (getattr(route, "methods", set()) or set())
    }
    for expected in {
        ("/api/project-profile/templates", "GET"),
        ("/api/projects/{project_id}/steps/3/image-style", "GET"),
        ("/api/projects/{project_id}/steps/3/image-style", "PUT"),
        ("/api/projects/{project_id}/steps/3/image-style/reference-images", "GET"),
        ("/api/image-style/project-templates", "GET"),
    }:
        assert expected in route_methods


def test_style_modules_do_not_auto_install_on_import() -> None:
    for path in (
        "runtime_project_profile.py",
        "runtime_project_profile_lightweight.py",
        "runtime_project_profile_templates_override.py",
        "runtime_project_style_references.py",
        "runtime_project_style_reference_manager.py",
        "runtime_project_style_reference_step3.py",
        "runtime_image_style_reverse.py",
        "runtime_step3_image_style.py",
        "runtime_step3_image_style_state.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8").rstrip()
        assert not source.endswith("_install_when_ready()")


if __name__ == "__main__":
    test_style_modules_are_explicit_and_ordered()
    test_critical_style_routes_are_present()
    test_style_modules_do_not_auto_install_on_import()
    print("project style registration checks passed")
