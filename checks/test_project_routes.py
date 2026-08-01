from pathlib import Path

import server
from route_inventory import iter_effective_routes


ROOT = Path(__file__).resolve().parents[1]


def test_project_router_preserves_project_lifecycle_paths() -> None:
    routes = {
        (
            route.path,
            frozenset(getattr(route, "methods", None) or []),
        )
        for route in iter_effective_routes(server.app)
    }
    assert ("/api/projects", frozenset({"POST"})) in routes
    assert ("/api/projects", frozenset({"GET"})) in routes
    assert (
        "/api/projects/{project_id}",
        frozenset({"GET"}),
    ) in routes
    assert (
        "/api/projects/{project_id}",
        frozenset({"DELETE"}),
    ) in routes
    assert (
        "/api/projects/{project_id}/ai-mode",
        frozenset({"GET"}),
    ) in routes
    assert (
        "/api/projects/{project_id}/ai-mode",
        frozenset({"PUT"}),
    ) in routes


def test_project_service_has_no_application_module_dependency() -> None:
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    service_source = (ROOT / "project_service.py").read_text(
        encoding="utf-8"
    )
    routes_source = (ROOT / "project_routes.py").read_text(
        encoding="utf-8"
    )
    assert "app.include_router(project_router)" in server_source
    assert '@app.post("/api/projects")' not in server_source
    assert "APIRouter" not in service_source
    assert "router = APIRouter()" in routes_source
    for source in (service_source, routes_source):
        assert "server_module" not in source
        assert "import server" not in source
