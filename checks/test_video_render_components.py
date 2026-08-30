from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from remotion_runner import (
    RemotionRenderResult,
    RemotionRunner,
    RemotionRunnerDependencies,
)
from video_contracts import VideoRenderConfig
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
