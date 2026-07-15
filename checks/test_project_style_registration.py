from pathlib import Path
import sys
from collections import Counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import project_style_routes  # noqa: E402
import server  # noqa: E402


def test_style_modules_are_explicit_and_ordered() -> None:
    names = [name for name, _register in project_style_routes.REGISTRATION_STEPS]
    assert names == [
        "project_profile",
        "project_profile_lightweight",
        "project_profile_templates_override",
        "project_style_references",
        "project_style_reference_manager",
        "image_style_reverse",
        "step3_image_style",
        "step3_image_style_state",
    ]
    assert not (ROOT / "runtime_bootstrap.py").exists()


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
        "runtime_image_style_reverse.py",
        "runtime_step3_image_style.py",
        "runtime_step3_image_style_state.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8").rstrip()
        assert "def _install_when_ready" not in source
        assert "def _candidate_modules" not in source


def test_step3_prompt_and_generate_routes_are_unique() -> None:
    routes = [
        (getattr(route, "path", ""), frozenset(getattr(route, "methods", set()) or set()))
        for route in server.app.routes
    ]
    assert routes.count(("/api/projects/{project_id}/steps/3/prompts", frozenset({"GET"}))) == 1
    assert routes.count(("/api/projects/{project_id}/steps/3/generate", frozenset({"POST"}))) == 1


def test_application_has_no_duplicate_method_path_routes() -> None:
    keys = [
        (method, getattr(route, "path", ""))
        for route in server.app.routes
        for method in (getattr(route, "methods", set()) or set())
        if method not in {"HEAD", "OPTIONS"}
    ]
    assert not [key for key, count in Counter(keys).items() if count > 1]


if __name__ == "__main__":
    test_style_modules_are_explicit_and_ordered()
    test_critical_style_routes_are_present()
    test_style_modules_do_not_auto_install_on_import()
    test_step3_prompt_and_generate_routes_are_unique()
    test_application_has_no_duplicate_method_path_routes()
    print("project style registration checks passed")
