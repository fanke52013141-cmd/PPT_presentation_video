from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import project_runtime_service as runtime  # noqa: E402
import server  # noqa: E402


RUNTIME_FUNCTIONS = (
    "reveal_lock_for",
    "write_project_log",
    "all_current_slide_images_exist",
    "sync_reveal_manifest_to_contract",
    "audio_confirmation_path",
    "project_audio_confirmed",
    "nonempty_file",
    "slide_tts_artifact_paths",
    "read_timeline_duration_sec",
    "slide_tts_artifact_status",
    "remove_tts_artifacts",
    "ensure_slide_tts_text_file",
    "mark_step_retry_needed",
    "mark_step_in_progress",
    "handle_step_navigation",
    "begin_storyboard_after_article_import",
    "invalidate_after_upstream_edit",
    "clear_slide_visual_derivatives",
    "mark_slide_image_changed",
)


def test_module_owns_project_runtime_without_application_wiring() -> None:
    source = (ROOT / "project_runtime_service.py").read_text(
        encoding="utf-8"
    )
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    for forbidden in (
        "APIRouter",
        "Depends(",
        "get_db",
        "server_module",
        "import server",
    ):
        assert forbidden not in source
    for function_name in RUNTIME_FUNCTIONS:
        assert f"def {function_name}(" in source
        assert f"def {function_name}(" not in server_source
        assert getattr(server, function_name) is getattr(
            runtime,
            function_name,
        )


def test_project_log_redacts_secrets_and_bounds_large_values(
    tmp_path: Path,
) -> None:
    project = SimpleNamespace(
        id="project-1",
        run_dir=str(tmp_path),
    )

    runtime.write_project_log(
        project,
        "render_started",
        api_key="private",
        authorization="Bearer private",
        empty_secret="",
        details="x" * 4005,
    )

    log_path = tmp_path / "logs" / "pipeline.log"
    record = json.loads(
        log_path.read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["project_id"] == "project-1"
    assert record["event"] == "render_started"
    assert record["api_key"] == "***REDACTED***"
    assert record["authorization"] == "***REDACTED***"
    assert record["empty_secret"] == ""
    assert record["details"] == (
        ("x" * 4000) + "\n... [truncated 5 chars]"
    )


def test_manifest_sync_preserves_implicit_and_explicit_empty_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(run_dir="run")
    calls: list[tuple[object, list[str], bool]] = []
    monkeypatch.setattr(
        runtime,
        "read_contract_slide_ids",
        lambda _run_dir: ["slide_001"],
    )
    monkeypatch.setattr(
        runtime,
        "sync_reveal_manifest",
        lambda target, slide_ids, *, allow_empty: calls.append(
            (target, slide_ids, allow_empty)
        )
        or True,
    )

    assert runtime.sync_reveal_manifest_to_contract(project)
    assert runtime.sync_reveal_manifest_to_contract(project, [])
    assert calls == [
        (project, ["slide_001"], False),
        (project, [], True),
    ]


def test_slide_image_completeness_uses_current_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(run_dir=str(tmp_path))
    monkeypatch.setattr(
        runtime,
        "read_contract_slide_ids",
        lambda _run_dir: ["slide_001", "slide_002"],
    )
    for slide_id in ("slide_001", "slide_002"):
        slide_dir = tmp_path / "slides" / slide_id
        slide_dir.mkdir(parents=True)
        (slide_dir / "visual_draft.png").write_bytes(b"png")

    assert runtime.all_current_slide_images_exist(project)
    (tmp_path / "slides" / "slide_002" / "visual_draft.png").unlink()
    assert not runtime.all_current_slide_images_exist(project)


def test_tts_adapters_restore_text_without_rewriting_existing_file(
    tmp_path: Path,
) -> None:
    project = SimpleNamespace(run_dir=str(tmp_path))
    contract = {
        "slides": [
            {
                "slide_id": "slide_001",
                "narration_beats": [
                    {"tts_text": "first"},
                    {"spoken_text": "second"},
                ],
            }
        ]
    }

    text_path = Path(
        runtime.ensure_slide_tts_text_file(
            project,
            "slide_001",
            contract,
        )
    )
    assert text_path.read_text(encoding="utf-8") == (
        "first\nsecond\n"
    )

    text_path.write_text("approved", encoding="utf-8")
    assert runtime.ensure_slide_tts_text_file(
        project,
        "slide_001",
        contract,
    ) == str(text_path)
    assert text_path.read_text(encoding="utf-8") == "approved"


def test_workflow_adapters_commit_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(run_dir="run")
    db = SimpleNamespace(commits=0)
    db.commit = lambda: setattr(db, "commits", db.commits + 1)
    calls: list[tuple[str, int | str]] = []

    monkeypatch.setattr(
        runtime.invalidation_service,
        "begin_stage",
        lambda _project, step: calls.append(("begin", step)),
    )
    monkeypatch.setattr(
        runtime.invalidation_service,
        "complete_stage",
        lambda _project, step: calls.append(("complete", step)),
    )
    monkeypatch.setattr(
        runtime.invalidation_service,
        "upstream_content_changed",
        lambda _project, step: calls.append(("upstream", step)),
    )
    monkeypatch.setattr(
        runtime.invalidation_service,
        "slide_images_changed",
        lambda _project, slide_ids, *, all_images_exist: (
            calls.append(("image", slide_ids[0])),
            calls.append(("all_images", int(all_images_exist))),
        ),
    )
    monkeypatch.setattr(
        runtime,
        "all_current_slide_images_exist",
        lambda _project: True,
    )

    runtime.mark_step_in_progress(project, 3, db)
    runtime.handle_step_navigation(project, 3, db)
    runtime.begin_storyboard_after_article_import(project, db)
    runtime.invalidate_after_upstream_edit(project, 2, db)
    runtime.mark_slide_image_changed(project, "slide_001", db)

    assert db.commits == 5
    assert calls == [
        ("begin", 3),
        ("complete", 3),
        ("upstream", 1),
        ("begin", 2),
        ("upstream", 2),
        ("image", "slide_001"),
        ("all_images", 1),
    ]


def test_article_import_completes_step1_and_begins_step2_once(
    tmp_path: Path,
) -> None:
    statuses = {str(step): "pending" for step in range(1, 9)}
    project = SimpleNamespace(
        run_dir=str(tmp_path),
        current_step=1,
        get_step_status=lambda: dict(statuses),
    )

    def set_step_status(next_statuses: dict[str, str]) -> None:
        statuses.clear()
        statuses.update(next_statuses)

    project.set_step_status = set_step_status
    db = SimpleNamespace(commits=0)
    db.commit = lambda: setattr(db, "commits", db.commits + 1)

    runtime.begin_storyboard_after_article_import(project, db)

    assert project.current_step == 2
    assert statuses["1"] == "completed"
    assert statuses["2"] == "in_progress"
    assert all(
        statuses[str(step)] == "pending"
        for step in range(3, 9)
    )
    assert db.commits == 1
