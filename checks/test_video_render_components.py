from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from remotion_runner import (
    RemotionRenderResult,
    RemotionRunner,
    RemotionRunnerDependencies,
)
from video_contracts import VideoRenderConfig, VideoRenderError
from video_render_service import (
    VideoRenderDependencies,
    VideoRenderService,
)


def _config(tmp_path: Path) -> VideoRenderConfig:
    return VideoRenderConfig(
        repo_root=tmp_path,
        runs_root=tmp_path,
        pipeline_version="test-pipeline",
        reveal_visual_lead_sec=0.2,
        bind_timeout_sec=1,
        build_props_timeout_sec=1,
        npm_install_timeout_sec=1,
        render_timeout_sec=1,
        color_process_timeout_sec=1,
    )


def test_remotion_asset_validation_rejects_missing_and_traversal(
    tmp_path: Path,
) -> None:
    public_dir = tmp_path / "public"
    valid_asset = public_dir / "runtime" / "slide.png"
    valid_asset.parent.mkdir(parents=True)
    valid_asset.write_bytes(b"png")
    props = {
        "slides": [
            {
                "audio_file": "runtime/missing.mp3",
                "scene": {
                    "canvas": {
                        "background_asset": "../outside.png",
                    },
                    "layers": [
                        {"asset": "runtime/slide.png"},
                    ],
                },
            }
        ]
    }

    assert RemotionRunner.validate_public_assets(
        props,
        public_dir,
    ) == [
        "../outside.png",
        "runtime/missing.mp3",
    ]


def test_remotion_props_use_project_canvas_dimensions(tmp_path: Path) -> None:
    project = SimpleNamespace(
        id="portrait-project",
        run_dir=str(tmp_path),
        canvas_profile="portrait_9_16",
    )
    received: list[str] = []

    def build_props_command(args, **_kwargs):
        received.extend(args)
        (tmp_path / "remotion_props.json").write_text(
            '{"width":1080,"height":1920,"slides":[]}', encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    runner = RemotionRunner(
        RemotionRunnerDependencies(
            config=_config(tmp_path),
            build_reveal_assets=lambda _project: None,
            write_project_log=lambda *_args, **_kwargs: None,
            run_subprocess_bounded=build_props_command,
            resolve_media_tool=lambda _name: None,
        )
    )
    props, _public_dir = runner._build_remotion_props(project, lambda _stage: None)

    assert props["width"] == 1080
    assert props["height"] == 1920
    assert received[received.index("--width") + 1] == "1080"
    assert received[received.index("--height") + 1] == "1920"


def test_render_coordinator_delegates_and_publishes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "videos" / "render_test.mp4"
    output_path.parent.mkdir()
    output_path.write_bytes(b"video")
    project = SimpleNamespace(
        id="project-test",
        run_dir=str(tmp_path),
    )
    stages: list[str] = []
    commits: list[bool] = []

    class FakeDb:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return project

        def commit(self):
            commits.append(True)

        def close(self):
            return None

    class FakeArtifacts:
        def project_video_dir(self, _project):
            return output_path.parent

        def current_render_input_fingerprint(self, _project):
            return {"digest": "fingerprint"}

        def visual_settings(self, _project):
            return {
                "video_background": "#FEFDF9",
                "subtitle_style": {"font_size": 48},
            }

        def record_rendered_video(
            self,
            _db,
            _project,
            _path,
            _filename,
            **_kwargs,
        ):
            return SimpleNamespace(id="artifact-test")

        def video_item(self, _project, path, *_args):
            return {"filename": Path(path).name}

        def list_video_items(self, _project):
            return [{"filename": output_path.name}]

    class FakeRunner:
        def run(self, _project, *, output_dir, set_stage):
            assert output_dir == output_path.parent
            for stage in ("building_reveal", "rendering"):
                stages.append(stage)
                set_stage(stage)
            return RemotionRenderResult(
                output_path=output_path,
                output_filename=output_path.name,
                color_validation={"ok": True},
            )

    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=FakeDb,
            artifact_service=FakeArtifacts(),
            remotion_runner=FakeRunner(),
            config=_config(tmp_path),
        )
    )
    service.job_store = SimpleNamespace(
        update=lambda *_args, **_kwargs: None
    )
    service._tasks["task-test"] = {
        "task_id": "task-test",
        "project_id": project.id,
        "status": "rendering",
        "stage": "validating",
        "started_at": 0.0,
    }
    completed: list[tuple[object, int]] = []
    monkeypatch.setattr(
        "video_render_service.invalidation_service.complete_stage",
        lambda value, stage: completed.append((value, stage)),
    )

    service.run_render_job(project.id, "task-test")

    task = service._tasks["task-test"]
    assert stages == ["building_reveal", "rendering"]
    assert completed == [(project, 8)]
    assert commits == [True]
    assert task["status"] == "success"
    assert task["output_filename"] == output_path.name
    assert task["result_artifact_id"] == "artifact-test"


def test_start_render_ends_caller_transaction_before_creating_job(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = SimpleNamespace(id="project-test", run_dir=str(tmp_path))
    events: list[str] = []

    class CallerDb:
        def commit(self) -> None:
            events.append("caller_commit")

        def rollback(self) -> None:
            events.append("caller_rollback")

    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=CallerDb,
            artifact_service=SimpleNamespace(),
            remotion_runner=SimpleNamespace(),
            config=_config(tmp_path),
        )
    )
    service.get_project = lambda _db, _project_id: project
    service._read_contract_slide_ids = lambda _run_dir: ["slide_001"]

    def create_job(*_args, **_kwargs) -> None:
        assert events == ["caller_commit"]
        events.append("job_create")

    service.job_store = SimpleNamespace(
        active=lambda *_args, **_kwargs: None,
        create=create_job,
    )
    monkeypatch.setattr(
        "video_render_service.validate_visual_provenance_set",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        "video_render_service.tts_confirmation_status",
        lambda *_args: {"confirmed": True},
    )

    class NoopThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            events.append("thread_start")

    monkeypatch.setattr("video_render_service.threading.Thread", NoopThread)

    response = service.start_render(CallerDb(), project.id)

    assert response["success"] is True
    assert events == ["caller_commit", "job_create", "thread_start"]


def test_start_render_reports_sanitized_persistence_diagnostic(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    project = SimpleNamespace(id="project-test", run_dir=str(tmp_path))

    class CallerDb:
        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=CallerDb,
            artifact_service=SimpleNamespace(),
            remotion_runner=SimpleNamespace(),
            config=_config(tmp_path),
        )
    )
    service.get_project = lambda _db, _project_id: project
    service._read_contract_slide_ids = lambda _run_dir: ["slide_001"]
    monkeypatch.setattr(
        "video_render_service.validate_visual_provenance_set",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        "video_render_service.tts_confirmation_status",
        lambda *_args: {"confirmed": True},
    )

    from video_job_store import VideoJobPersistenceError

    service.job_store = SimpleNamespace(
        active=lambda *_args, **_kwargs: None,
        create=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            VideoJobPersistenceError(
                category="sqlite_write_locked",
                exception_type="OperationalError",
                attempt_count=3,
                retryable=True,
            )
        )
    )

    with pytest.raises(VideoRenderError, match="本地任务数据库正忙"):
        service.start_render(CallerDb(), project.id)

    message = caplog.text
    assert "category=sqlite_write_locked" in message
    assert "exception_type=OperationalError" in message
    assert "must-not-appear-in-diagnostics" not in message


def test_start_render_releases_project_lock_when_transaction_close_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = SimpleNamespace(id="project-test", run_dir=str(tmp_path))

    class CallerDb:
        def commit(self) -> None:
            raise RuntimeError("transaction commit failed")

        def rollback(self) -> None:
            return None

    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=CallerDb,
            artifact_service=SimpleNamespace(),
            remotion_runner=SimpleNamespace(),
            config=_config(tmp_path),
        )
    )
    service.get_project = lambda _db, _project_id: project
    service._read_contract_slide_ids = lambda _run_dir: ["slide_001"]
    service.job_store = SimpleNamespace(
        active=lambda *_args, **_kwargs: None,
        create=lambda *_args, **_kwargs: pytest.fail("must not create a job"),
    )
    monkeypatch.setattr(
        "video_render_service.validate_visual_provenance_set",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        "video_render_service.tts_confirmation_status",
        lambda *_args: {"confirmed": True},
    )

    with pytest.raises(VideoRenderError, match="无法准备持久化视频任务"):
        service.start_render(CallerDb(), project.id)

    project_lock = service._project_lock(project.id)
    assert project_lock.acquire(blocking=False)
    project_lock.release()
