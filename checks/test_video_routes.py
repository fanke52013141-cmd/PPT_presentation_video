from __future__ import annotations

import time
from types import SimpleNamespace

import server


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
        for route in server.app.routes
        for method in (getattr(route, "methods", set()) or set())
    }
    assert ("/api/projects/{project_id}/videos", "GET") in route_methods
    assert ("/api/projects/{project_id}/videos/{filename}", "GET") in route_methods
    assert ("/api/projects/{project_id}/videos/{filename}/speed", "POST") in route_methods
    assert ("/api/projects/{project_id}/videos/{filename}", "DELETE") in route_methods


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
    with server._RENDER_TASKS_LOCK:
        server._RENDER_TASKS[task_id] = task
    try:
        result = server.get_render_status(project_id, task_id=task_id, db=_Db(project))
    finally:
        with server._RENDER_TASKS_LOCK:
            server._RENDER_TASKS.pop(task_id, None)

    assert result["status"] == "rendering"
    assert result["task_id"] == task_id
    assert result["videos"] == [{"filename": "existing.mp4"}]
