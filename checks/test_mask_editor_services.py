from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

import mask_manifest_service as manifest_service
import mask_preview_service as preview_service
from route_inventory import iter_effective_routes
import server


def _write_json(path: Path | str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _manifest_dependencies(
    tmp_path: Path,
    *,
    builds: list[str],
    navigations: list[int],
) -> manifest_service.MaskManifestDependencies:
    return manifest_service.MaskManifestDependencies(
        normalize_visual_type=lambda value, **_kwargs: str(value or "text"),
        reveal_lock_for=lambda _project: nullcontext(),
        read_contract_slide_ids=lambda _run_dir: ["slide_001"],
        sync_reveal_manifest_to_contract=lambda _project: False,
        storage_slide_file=lambda run_dir, slide_id, filename: (
            Path(run_dir) / "slides" / slide_id / filename
        ),
        write_json_atomic=_write_json,
        handle_step_navigation=lambda _project, step, _db: (
            navigations.append(step)
        ),
        sync_project_background_color=lambda _project: None,
        write_project_log=lambda *_args, **_kwargs: None,
        apply_storyboard_background=lambda _path: builds.append(
            "background"
        ),
        repo_root=tmp_path,
        python_executable="python",
        build_timeout_sec=1.0,
    )


def test_step5_routes_are_source_owned_and_unique() -> None:
    expected = {
        ("POST", "/api/projects/{project_id}/steps/5/semantic-blocks"),
        ("GET", "/api/projects/{project_id}/steps/5/result"),
        ("POST", "/api/projects/{project_id}/steps/5/repair"),
        ("PUT", "/api/projects/{project_id}/steps/5/draft"),
        (
            "POST",
            "/api/projects/{project_id}/steps/5/slides/{slide_id}/preview",
        ),
        (
            "GET",
            "/api/projects/{project_id}/slides/{slide_id}/mask-preview",
        ),
        ("PUT", "/api/projects/{project_id}/steps/5/result"),
    }
    keys = Counter(
        (method, route.path)
        for route in iter_effective_routes(server.app)
        for method in (getattr(route, "methods", set()) or set())
        if method not in {"HEAD", "OPTIONS"}
    )
    assert all(keys[key] == 1 for key in expected)

    root = Path(__file__).resolve().parents[1]
    server_source = (root / "server.py").read_text(encoding="utf-8")
    route_source = (root / "mask_editor_routes.py").read_text(
        encoding="utf-8"
    )
    for service_name in (
        "mask_manifest_service.py",
        "mask_preview_service.py",
    ):
        source = (root / service_name).read_text(encoding="utf-8")
        assert "APIRouter" not in source
        assert "Depends(" not in source
        assert "get_db" not in source
        assert "import server" not in source
        assert "server_module" not in source
    assert "router = APIRouter()" in route_source
    assert "app.include_router(mask_editor_router)" in server_source
    assert '@app.put("/api/projects/{project_id}/steps/5/' not in (
        server_source
    )


def test_draft_never_builds_or_navigates_and_final_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds: list[str] = []
    navigations: list[int] = []
    original_dependencies = manifest_service._dependencies
    manifest_service.configure_mask_manifest_dependencies(
        _manifest_dependencies(
            tmp_path,
            builds=builds,
            navigations=navigations,
        )
    )
    monkeypatch.setattr(
        manifest_service,
        "build_current_reveal_assets",
        lambda _project: builds.append("build"),
    )
    project = SimpleNamespace(
        id="mask-lifecycle",
        run_dir=str(tmp_path),
    )
    payload = {"slides": [{"slide_id": "slide_001", "groups": []}]}
    try:
        assert manifest_service.update_step5_draft(
            project,
            payload,
        ) == {"success": True}
        assert builds == []
        assert navigations == []

        without_build = manifest_service.update_step5_result(
            project,
            {"slides": [{"slide_id": "slide_001", "groups": []}]},
            build_assets=False,
            db=object(),
        )
        assert without_build == {
            "success": True,
            "built_assets": False,
        }
        assert builds == []
        assert navigations == [5]

        with_build = manifest_service.update_step5_result(
            project,
            {"slides": [{"slide_id": "slide_001", "groups": []}]},
            build_assets=True,
            db=object(),
        )
        assert with_build == {
            "success": True,
            "built_assets": True,
        }
        assert builds == ["build"]
        assert navigations == [5, 5]
    finally:
        manifest_service._dependencies = original_dependencies


def test_reveal_validation_uses_the_project_canvas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dependencies = manifest_service._dependencies
    manifest_service.configure_mask_manifest_dependencies(
        _manifest_dependencies(tmp_path, builds=[], navigations=[])
    )
    received: list[str] = []

    def fake_run(command, **_kwargs):
        received.extend(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(manifest_service, "run_subprocess_killable", fake_run)
    try:
        manifest_service.validate_current_reveal_assets(
            SimpleNamespace(run_dir=str(tmp_path), canvas_profile="portrait_9_16")
        )
    finally:
        manifest_service._dependencies = original_dependencies

    assert received[received.index("--width") + 1] == "1080"
    assert received[received.index("--height") + 1] == "1920"


def test_semantic_refresh_preserves_only_painted_manual_groups(
    tmp_path: Path,
) -> None:
    planning = tmp_path / "planning"
    planning.mkdir()
    _write_json(
        planning / "visual_contract.json",
        {
            "slides": [
                {
                    "slide_id": "slide_001",
                    "visual_groups": [
                        {
                            "id": "body",
                            "role": "content_body",
                            "visible_text": "Body",
                            "visual_type": "text",
                        }
                    ],
                    "narration_beats": [
                        {
                            "id": "beat_001",
                            "group_id": "body",
                            "spoken_text": "Narration.",
                        }
                    ],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "reveal_manifest.json",
        {
            "slides": [
                {
                    "slide_id": "slide_001",
                    "groups": [
                        {
                            "id": "manual_group_1",
                            "manual_mask": {
                                "strokes": [
                                    {
                                        "mode": "paint",
                                        "points": [{"x": 1, "y": 1}],
                                    }
                                ]
                            },
                        },
                        {
                            "id": "stale_empty",
                            "manual_mask": {"strokes": []},
                        },
                    ],
                }
            ]
        },
    )
    original_dependencies = manifest_service._dependencies
    manifest_service.configure_mask_manifest_dependencies(
        _manifest_dependencies(
            tmp_path,
            builds=[],
            navigations=[],
        )
    )
    try:
        manifest, processed = (
            manifest_service.refresh_reveal_semantic_blocks(
                SimpleNamespace(
                    id="semantic-refresh",
                    run_dir=str(tmp_path),
                )
            )
        )
    finally:
        manifest_service._dependencies = original_dependencies

    assert processed == 1
    slide = manifest["slides"][0]
    assert [group["id"] for group in slide["groups"]] == [
        "manual_group_1"
    ]
    assert [
        block["visual_group_id"]
        for block in slide["semantic_blocks"]
    ] == ["body"]


def test_preview_uses_production_builder_and_reports_cutout_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id="preview-project", run_dir=str(tmp_path))
    slide_dir = tmp_path / "slides" / "slide_001"
    slide_dir.mkdir(parents=True)
    manifest_path = tmp_path / "reveal_manifest.json"
    _write_json(manifest_path, {"slides": [{"slide_id": "slide_001"}]})
    _write_json(
        slide_dir / "reveal_report.json",
        {
            "fallback_full_slide": False,
            "warnings": ["sample"],
            "groups": [
                {
                    "cutout": {
                        "manual_mask_pixel_count": 10,
                        "retained_pixel_count": 8,
                    }
                }
            ],
            "static_groups": [
                {
                    "cutout": {
                        "manual_mask_pixel_count": 2,
                        "soft_edge_pixel_count": 3,
                    }
                }
            ],
        },
    )
    calls: list[str] = []

    def current_file(
        _project: Any,
        slide_id: str,
        filename: str,
    ) -> str:
        return str(tmp_path / "slides" / slide_id / filename)

    def run_builder(command: list[str], **_kwargs: Any) -> Any:
        calls.append(Path(command[1]).name)
        output = Path(command[command.index("--preview-output") + 1])
        output.write_bytes(b"preview")
        return SimpleNamespace(returncode=0, stderr="")

    original_dependencies = preview_service._dependencies
    preview_service.configure_mask_preview_dependencies(
        preview_service.MaskPreviewDependencies(
            reveal_lock_for=lambda _project: nullcontext(),
            sync_project_background_color=lambda _project: calls.append(
                "sync-background"
            ),
            current_slide_file_or_404=current_file,
            project_run_dir_or_500=lambda _project: str(tmp_path),
            read_json_file=lambda path, _default: json.loads(
                Path(path).read_text(encoding="utf-8")
            ),
            apply_storyboard_background=lambda _path: calls.append(
                "apply-background"
            ),
            compose_preview_image=lambda _slide_dir, _preview: calls.append(
                "compose-preview"
            ),
            repo_root=tmp_path,
            python_executable="python",
            build_timeout_sec=1.0,
            run_subprocess=run_builder,
        )
    )
    monkeypatch.setattr(
        preview_service, "run_subprocess_killable", run_builder
    )
    try:
        result = preview_service.build_step5_mask_preview(
            project,
            "slide_001",
        )
    finally:
        preview_service._dependencies = original_dependencies

    assert calls == [
        "sync-background",
        "build_reveal_scene.py",
        "apply-background",
        "compose-preview",
    ]
    assert len(result["manifest_fingerprint"]) == 64
    assert result["warnings"] == ["sample"]
    assert result["fallback_full_slide"] is False
    assert result["cutout_stats"] == {
        "manual_mask_pixel_count": 12,
        "removed_outer_white_pixel_count": 0,
        "soft_edge_pixel_count": 3,
        "retained_pixel_count": 8,
    }


def test_preview_timeout_maps_to_504(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id="preview-timeout", run_dir=str(tmp_path))
    (tmp_path / "slides" / "slide_001").mkdir(parents=True)
    _write_json(tmp_path / "reveal_manifest.json", {"slides": []})
    original_dependencies = preview_service._dependencies
    preview_service.configure_mask_preview_dependencies(
        preview_service.MaskPreviewDependencies(
            reveal_lock_for=lambda _project: nullcontext(),
            sync_project_background_color=lambda _project: None,
            current_slide_file_or_404=lambda _project, slide_id, filename: str(
                tmp_path / "slides" / slide_id / filename
            ),
            project_run_dir_or_500=lambda _project: str(tmp_path),
            read_json_file=lambda _path, default: default,
            apply_storyboard_background=lambda _path: None,
            compose_preview_image=lambda _slide_dir, _preview: None,
            repo_root=tmp_path,
            python_executable="python",
            build_timeout_sec=1.0,
            run_subprocess=lambda *_args, **_kwargs: subprocess.CompletedProcess(
                ["builder"],
                124,
                "",
                "Timed out after 1 seconds.",
            ),
        )
    )
    def killable_timeout(_command, **_kwargs):
        # run_subprocess_killable 的超时契约：返回 returncode=124 的结果
        return SimpleNamespace(returncode=124, stderr="builder timed out")

    monkeypatch.setattr(
        preview_service, "run_subprocess_killable", killable_timeout
    )
    try:
        with pytest.raises(preview_service.MaskPreviewError) as captured:
            preview_service.build_step5_mask_preview(
                project,
                "slide_001",
            )
    finally:
        preview_service._dependencies = original_dependencies
    assert captured.value.status_code == 504
