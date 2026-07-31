from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

import server
from visual_settings_service import (
    VisualSettingsDependencies,
    VisualSettingsService,
)


ROOT = Path(__file__).resolve().parents[1]


class _Query:
    def __init__(self, project: Any) -> None:
        self.project = project

    def filter(self, *_args: Any) -> "_Query":
        return self

    def first(self) -> Any:
        return self.project


class _Db:
    def __init__(self, project: Any) -> None:
        self.project = project

    def query(self, *_args: Any) -> _Query:
        return _Query(self.project)


def _visual_service(
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]],
) -> VisualSettingsService:
    current = {
        "generation_background": "#FFFFFF",
        "video_background": "#FEFDF9",
        "subtitle_style": {"font_size": 36},
    }

    def read_settings(_project: Any) -> dict[str, Any]:
        return current.copy()

    def write_settings(
        project: Any,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(("write", (project, *args), kwargs))
        return {
            **current,
            "video_background": (
                args[0] if args else current["video_background"]
            ),
            "subtitle_style": kwargs.get(
                "subtitle_style",
                current["subtitle_style"],
            ),
        }

    def record(name: str):
        def operation(*args: Any, **kwargs: Any) -> None:
            calls.append((name, args, kwargs))

        return operation

    return VisualSettingsService(
        VisualSettingsDependencies(
            read_settings=read_settings,
            write_settings=write_settings,
            sync_background=record("sync"),
            invalidate_background=record("invalidate_background"),
            invalidate_subtitles=record("invalidate_subtitles"),
            preview_background_url=lambda _project: "/preview.png",
            fonts=[{"name": "Test Font"}],
        )
    )


def test_visual_settings_preserve_background_and_subtitle_payloads() -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    project = SimpleNamespace(id="project-1")
    db = _Db(project)
    service = _visual_service(calls)

    background = service.update_background(
        "project-1",
        {"video_background": "#aabbcc"},
        db,
    )
    assert background["video_background"] == "#AABBCC"
    assert calls[0] == ("write", (project, "#AABBCC"), {})
    assert calls[1][0] == "sync"
    assert calls[2][0] == "invalidate_background"

    calls.clear()
    subtitles = service.update_subtitles(
        "project-1",
        {"subtitle_style": {"font_size": 42}},
        db,
    )
    assert subtitles["subtitle_style"] == {"font_size": 42}
    assert calls[0] == (
        "write",
        (project,),
        {"subtitle_style": {"font_size": 42}},
    )
    assert calls[1][0] == "invalidate_subtitles"


def test_visual_settings_reject_invalid_background() -> None:
    service = _visual_service([])
    with pytest.raises(HTTPException) as exc_info:
        service.update_background(
            "project-1",
            {"video_background": "white"},
            _Db(SimpleNamespace(id="project-1")),
        )
    assert exc_info.value.status_code == 400


def test_step3_routes_are_explicit_and_unique() -> None:
    expected = {
        ("/api/image-style", "GET"),
        ("/api/image-style", "PUT"),
        ("/api/projects/{project_id}/steps/3/visual-settings", "GET"),
        ("/api/projects/{project_id}/steps/3/visual-settings", "PUT"),
        ("/api/projects/{project_id}/subtitle-settings", "GET"),
        ("/api/projects/{project_id}/subtitle-settings", "PUT"),
        ("/api/projects/{project_id}/steps/3/prompt-settings", "GET"),
        ("/api/projects/{project_id}/steps/3/prompt-settings", "PUT"),
        ("/api/projects/{project_id}/steps/3/prompts", "GET"),
        ("/api/projects/{project_id}/steps/3/generate", "POST"),
        ("/api/projects/{project_id}/steps/3/upload", "POST"),
        ("/api/projects/{project_id}/steps/3/images", "GET"),
        ("/api/projects/{project_id}/steps/3/images", "DELETE"),
        ("/api/projects/{project_id}/steps/3/image-order", "PUT"),
        ("/api/projects/{project_id}/steps/3/confirm", "POST"),
    }
    observed = [
        (route.path, method)
        for route in server.app.routes
        for method in getattr(route, "methods", set())
        if (route.path, method) in expected
    ]
    assert set(observed) == expected
    assert len(observed) == len(expected)


def test_step3_services_do_not_own_fastapi_wiring() -> None:
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    for name in (
        "global_image_style_service.py",
        "image_workflow_service.py",
        "visual_settings_service.py",
    ):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "APIRouter" not in source
        assert "Depends(" not in source
        assert "get_db" not in source
        assert "import server" not in source
        assert "server_module" not in source

    assert "app.include_router(global_image_style_router)" in server_source
    assert "app.include_router(image_workflow_router)" in server_source
    assert "app.include_router(visual_settings_router)" in server_source
    assert '@app.get("/api/image-style")' not in server_source
    assert (
        '@app.post("/api/projects/{project_id}/steps/3/generate")'
        not in server_source
    )
