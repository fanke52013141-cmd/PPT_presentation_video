from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

import server
from route_inventory import iter_effective_routes
import visual_settings_service as visual_settings
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
        self.commits = 0

    def query(self, *_args: Any) -> _Query:
        return _Query(self.project)

    def commit(self) -> None:
        self.commits += 1


def _visual_service(
    tmp_path: Path,
) -> VisualSettingsService:
    style_reference_dir = tmp_path / "style"

    return VisualSettingsService(
        VisualSettingsDependencies(
            read_contract_slide_ids=lambda _run_dir: ["slide_001"],
            reveal_lock_for=lambda _project: nullcontext(),
            write_json_atomic=lambda path, value: Path(path).write_text(
                json.dumps(value, ensure_ascii=False, indent=2),
                encoding="utf-8",
            ),
            style_reference_dir=style_reference_dir,
            style_reference_template="template.png",
        )
    )


def test_visual_settings_preserve_background_and_subtitle_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(
        id="project-1",
        run_dir=str(tmp_path),
    )
    db = _Db(project)
    service = _visual_service(tmp_path)
    invalidations: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        visual_settings.invalidation_service,
        "video_background_changed",
        lambda item, slide_ids: invalidations.append(
            ("background", (item, slide_ids))
        ),
    )
    monkeypatch.setattr(
        visual_settings.invalidation_service,
        "subtitle_style_changed",
        lambda item: invalidations.append(("subtitles", item)),
    )

    background = service.update_background(
        "project-1",
        {"video_background": "#aabbcc"},
        db,
    )
    assert background["video_background"] == "#AABBCC"
    assert invalidations == [
        ("background", (project, ["slide_001"]))
    ]
    assert db.commits == 1
    stored = json.loads(
        (tmp_path / "visual_settings.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored["video_background"] == "#AABBCC"

    invalidations.clear()
    subtitles = service.update_subtitles(
        "project-1",
        {"subtitle_style": {"font_size": 42}},
        db,
    )
    assert subtitles["subtitle_style"]["font_size"] == 42
    assert subtitles["subtitle_style"]["font_family"] == (
        "Noto Sans SC"
    )
    assert invalidations == [("subtitles", project)]
    assert db.commits == 2


def test_visual_settings_reject_invalid_background(
    tmp_path: Path,
) -> None:
    service = _visual_service(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        service.update_background(
            "project-1",
            {"video_background": "white"},
            _Db(
                SimpleNamespace(
                    id="project-1",
                    run_dir=str(tmp_path),
                )
            ),
        )
    assert exc_info.value.status_code == 400


def test_visual_settings_sync_manifest_and_select_preview(
    tmp_path: Path,
) -> None:
    service = _visual_service(tmp_path)
    project = SimpleNamespace(
        id="project-1",
        run_dir=str(tmp_path),
    )
    service.write_settings(project, "#123456")
    manifest_path = tmp_path / "reveal_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "canvas": {"background": "#FFFFFF"},
                "background_detection": {"legacy": True},
            }
        ),
        encoding="utf-8",
    )

    assert service.sync_background(project) == "#123456"
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["canvas"]["background"] == "#123456"
    assert "background_detection" not in manifest
    assert manifest["background_settings"] == {
        "generation_background": "#FFFFFF",
        "video_background": "#123456",
        "outer_background_removal": (
            "outer_connected_near_white_only"
        ),
    }

    image = (
        tmp_path
        / "slides"
        / "slide_001"
        / "visual_draft.png"
    )
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    preview = service.preview_background_url(project)
    assert preview.startswith(
        "/api/projects/project-1/slides/slide_001/image?t="
    )


def test_visual_settings_normalization_is_bounded() -> None:
    style = visual_settings.normalize_subtitle_style(
        {
            "font_key": "unknown",
            "font_size": 999,
            "font_weight": 1,
            "bottom": -10,
            "horizontal_margin": "invalid",
            "color": "bad",
            "highlight_color": "#aabbcc",
            "paging_window_ms": 9999,
            "token_highlight": "off",
            "max_lines": 8,
            "line_height": 8,
        }
    )
    assert style["font_key"] == "noto_sans_sc"
    assert style["font_size"] == 72
    assert style["font_weight"] == 300
    assert style["bottom"] == 0
    assert style["horizontal_margin"] == 180
    assert style["color"] == "#111111"
    assert style["highlight_color"] == "#AABBCC"
    assert style["paging_window_ms"] == 2500
    assert style["token_highlight"] is False
    assert style["max_lines"] == 3
    assert style["line_height"] == 2.0


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
            for route in iter_effective_routes(server.app)
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
