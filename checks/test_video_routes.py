from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import server
from route_inventory import iter_effective_routes
import video_routes


class _Db:
    def __init__(self, project):
        self.project = project

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.project


def test_video_collection_route_is_registered() -> None:
    route_methods = {
        (getattr(route, "path", ""), method)
        for route in iter_effective_routes(server.app)
        for method in (getattr(route, "methods", set()) or set())
    }
    assert ("/api/projects/{project_id}/videos", "GET") in route_methods
    assert ("/api/projects/{project_id}/videos/{filename}", "GET") in route_methods
    assert ("/api/projects/{project_id}/videos/{filename}/speed", "POST") in route_methods
    assert ("/api/projects/{project_id}/videos/{filename}", "DELETE") in route_methods
    assert ("/api/projects/{project_id}/steps/8/render", "POST") in route_methods
    assert ("/api/projects/{project_id}/steps/8/render-status", "GET") in route_methods
    assert ("/api/projects/{project_id}/video/status", "GET") in route_methods
    assert ("/api/projects/{project_id}/video", "GET") in route_methods
    assert hasattr(video_routes, "router")


def test_render_status_returns_active_task_without_type_error(tmp_path) -> None:
    project_id = "route-status-project"
    project = SimpleNamespace(id=project_id, run_dir=str(tmp_path))
    task_id = "task-route-status"
    task = {
        "task_id": task_id,
        "project_id": project_id,
        "status": "rendering",
        "stage": "rendering",
        "started_at": time.time(),
        "finished_at": None,
        "elapsed_sec": 0.0,
        "error": None,
        "video": None,
        "videos": [{"filename": "existing.mp4"}],
    }
    service = server.video_render_service
    with service._tasks_lock:
        service._tasks[task_id] = task
    try:
        result = service.render_status(
            _Db(project),
            project_id,
            task_id=task_id,
        )
    finally:
        with service._tasks_lock:
            service._tasks.pop(task_id, None)

    assert result["status"] == "rendering"
    assert result["task_id"] == task_id
    assert result["videos"] == [{"filename": "existing.mp4"}]


def test_video_source_has_no_server_module_or_legacy_routes() -> None:
    root = Path(__file__).resolve().parents[1]
    service_source = (root / "video_render_service.py").read_text(
        encoding="utf-8"
    )
    routes_source = (root / "video_routes.py").read_text(
        encoding="utf-8"
    )
    server_source = (root / "server.py").read_text(
        encoding="utf-8"
    )
    for source in (service_source, routes_source):
        assert "server_module" not in source
        assert "sys.modules" not in source
    assert "app.include_router(video_router)" in server_source
    assert '@app.post("/api/projects/{project_id}/steps/8/render")' not in server_source
