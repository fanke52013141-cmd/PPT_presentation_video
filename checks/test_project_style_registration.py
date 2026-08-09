from pathlib import Path
import sys
from collections import Counter
from types import SimpleNamespace
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import project_style_routes  # noqa: E402
import project_profile_store  # noqa: E402
from project_style_context import get_project_style_context  # noqa: E402
from route_inventory import iter_effective_routes  # noqa: E402
import server  # noqa: E402


class _ProjectQuery:
    def __init__(self, project) -> None:
        self.project = project

    def filter(self, *_args):
        return self

    def first(self):
        return self.project


class _ProjectDb:
    def __init__(self, project) -> None:
        self.project = project

    def query(self, *_args):
        return _ProjectQuery(self.project)


def test_style_router_is_source_owned_and_explicit() -> None:
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "app.include_router(project_style_router)" in source
    assert "configure_project_style_context" in source
    assert "register_project_style_routes" not in source
    assert hasattr(project_style_routes, "router")


def test_critical_style_routes_are_present() -> None:
    route_methods = {
        (getattr(route, "path", ""), method)
        for route in iter_effective_routes(server.app)
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


def test_runtime_style_modules_are_retired() -> None:
    legacy_paths = (
        "runtime_project_profile.py",
        "runtime_project_profile_lightweight.py",
        "runtime_project_profile_templates_override.py",
        "runtime_project_style_references.py",
        "runtime_project_style_reference_manager.py",
        "runtime_image_style_reverse.py",
        "runtime_step3_image_style.py",
        "runtime_step3_image_style_state.py",
    )
    assert not [path for path in legacy_paths if (ROOT / path).exists()]
    for path in (
        "project_profile_service.py",
        "project_profile_store.py",
        "project_style_reference_service.py",
        "project_style_reference_store.py",
        "image_style_reverse_service.py",
        "step3_image_style_service.py",
        "project_style_template_service.py",
        "project_style_routes.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "def _register(" not in source
        assert "server_module.app" not in source


def test_step3_prompt_and_generate_routes_are_unique() -> None:
    routes = [
        (getattr(route, "path", ""), frozenset(getattr(route, "methods", set()) or set()))
        for route in iter_effective_routes(server.app)
    ]
    assert routes.count(("/api/projects/{project_id}/steps/3/prompts", frozenset({"GET"}))) == 1
    assert routes.count(("/api/projects/{project_id}/steps/3/generate", frozenset({"POST"}))) == 1


def test_application_has_no_duplicate_method_path_routes() -> None:
    keys = [
        (method, getattr(route, "path", ""))
        for route in iter_effective_routes(server.app)
        for method in (getattr(route, "methods", set()) or set())
        if method not in {"HEAD", "OPTIONS"}
    ]
    assert not [key for key, count in Counter(keys).items() if count > 1]


def test_profile_and_step3_style_round_trip_use_narrow_context() -> None:
    context = get_project_style_context()
    assert not hasattr(context, "app")
    assert not hasattr(context, "Project")
    with tempfile.TemporaryDirectory() as temp_dir:
        project = SimpleNamespace(id="project-style-test", run_dir=temp_dir, ai_mode="auto")
        db = _ProjectDb(project)
        saved_profile = project_style_routes.save_project_profile(
            project.id,
            {"automation_mode": "auto"},
            db,
        )
        assert saved_profile["profile"]["automation_mode"] == "auto"
        loaded_profile = project_style_routes.get_project_profile(project.id, db)
        assert loaded_profile["profile"]["automation_mode"] == "auto"

        project.ai_mode = "manual"
        loaded_profile = project_style_routes.get_project_profile(project.id, db)
        assert loaded_profile["profile"]["automation_mode"] == "manual_review"
        project.ai_mode = "auto"

        try:
            project_style_routes.save_project_profile(
                project.id,
                {"quality_gates": {"pause_on_render_failure": "false"}},
                db,
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 400
        else:
            raise AssertionError("string quality gate values must be rejected")

        profile_source = (ROOT / "project_profile_store.py").read_text(encoding="utf-8")
        routes_source = (ROOT / "project_style_routes.py").read_text(encoding="utf-8")
        assert "write_json_atomic(path, value)" in profile_source
        assert "project_profile_store.load_profile(project)" in routes_source
        assert "project_profile_store.save_profile(" in routes_source

        profile_path = Path(temp_dir) / "planning" / project_profile_store.PROFILE_FILENAME
        profile_path.write_text(
            '{"quality_gates":{"pause_on_render_failure":"false"}}',
            encoding="utf-8",
        )
        legacy_profile = project_profile_store.load_profile(project)
        assert legacy_profile["quality_gates"]["pause_on_render_failure"] is False

        profile_path.write_text(
            '{"quality_gates":{"pause_on_render_failure":{"legacy":"invalid"}}}',
            encoding="utf-8",
        )
        malformed_legacy_profile = project_profile_store.load_profile(project)
        assert malformed_legacy_profile["quality_gates"]["pause_on_render_failure"] is True

        saved_style = project_style_routes.put_step3_image_style(
            project.id,
            {"system_content": "Use soft blue geometric cards."},
            db,
        )
        assert saved_style["style"]["system_content"] == "Use soft blue geometric cards."
        loaded_style = project_style_routes.get_step3_image_style(project.id, db)
        assert loaded_style["style"]["system_content"] == "Use soft blue geometric cards."


if __name__ == "__main__":
    test_style_router_is_source_owned_and_explicit()
    test_critical_style_routes_are_present()
    test_runtime_style_modules_are_retired()
    test_step3_prompt_and_generate_routes_are_unique()
    test_application_has_no_duplicate_method_path_routes()
    test_profile_and_step3_style_round_trip_use_narrow_context()
    print("project style registration checks passed")
