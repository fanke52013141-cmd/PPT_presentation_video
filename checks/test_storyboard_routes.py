from __future__ import annotations

from pathlib import Path

from route_inventory import iter_effective_routes
import server


ROOT = Path(__file__).resolve().parents[1]


EXPECTED_STORYBOARD_PATHS = {
    "/api/step2-prompt-templates",
    "/api/step2-prompt-templates/{template_id}",
    "/api/storyboard-templates",
    "/api/storyboard-templates/{template_id}",
    "/api/projects/{project_id}/steps/2/rules",
    "/api/projects/{project_id}/steps/2/prompts",
    "/api/projects/{project_id}/steps/2/script/execute",
    "/api/projects/{project_id}/steps/2/script/result",
    "/api/projects/{project_id}/steps/2/visual/execute",
    "/api/projects/{project_id}/steps/2/visual/result",
    "/api/projects/{project_id}/steps/2/compose",
    "/api/projects/{project_id}/steps/2/prompt-preview",
    "/api/projects/{project_id}/steps/2/execute",
    "/api/projects/{project_id}/steps/2/result",
    "/api/projects/{project_id}/steps/2/repair",
    "/api/projects/{project_id}/steps/2/manual-skeleton",
}


def test_storyboard_router_preserves_all_public_paths() -> None:
    actual = {
        route.path
        for route in iter_effective_routes(server.app)
        if (
            "/steps/2/" in route.path
            or "step2-prompt-templates" in route.path
            or "storyboard-templates" in route.path
        )
    }
    assert actual == EXPECTED_STORYBOARD_PATHS


def test_storyboard_service_and_routes_have_explicit_boundaries() -> None:
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    service_source = (ROOT / "storyboard_service.py").read_text(
        encoding="utf-8"
    )
    routes_source = (ROOT / "storyboard_routes.py").read_text(
        encoding="utf-8"
    )

    assert "app.include_router(storyboard_router)" in server_source
    assert '@app.post("/api/projects/{project_id}/steps/2/' not in (
        server_source
    )
    assert "@router." not in service_source
    assert "APIRouter" not in service_source
    assert "router = APIRouter()" in routes_source
    for source in (service_source, routes_source):
        assert "server_module" not in source
        assert "sys.modules" not in source
        assert "import server" not in source
