from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from digital_human_service import _ensure_ffmpeg_in_path, _probe_duration_sec, composite_circle
from artifact_fingerprint import render_input_fingerprint
from remotion_runner import RemotionRenderResult
from video_contracts import VideoRenderConfig
from video_render_service import (
    DigitalHumanCompositeError,
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


def _write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")


@pytest.mark.parametrize(("presenter_duration", "policy", "rejected"), [
    (2.0, "reject", False),
    (0.6, "reject", False),  # Standard 0.4s Remotion tail.
    (0.3, "reject", True),
    (0.3, "loop", False),
    (0.3, "hold", False),  # Generated presenter during trailing silence.
])
def test_presenter_duration_policy(tmp_path: Path, presenter_duration: float, policy: str, rejected: bool) -> None:
    _ensure_ffmpeg_in_path()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg is unavailable")
    base = tmp_path / "lesson.mp4"
    presenter = tmp_path / "presenter.mp4"
    output = tmp_path / "combined.mp4"
    for target, color, duration in (
        (base, "white", 1.0),
        (presenter, "blue", presenter_duration),
    ):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             f"color=c={color}:s=160x90:r=10", "-t", str(duration),
             "-pix_fmt", "yuv420p", str(target)],
            check=True,
            capture_output=True,
        )
    settings = dict(digi_video=presenter, base_video=base, output=output,
                    circle={"cx": 0.5, "cy": 0.5, "r": 0.2}, short_video_policy=policy)
    if rejected:
        with pytest.raises(RuntimeError, match="短于课程"):
            composite_circle(**settings)
        assert not output.exists()
        return
    composite_circle(**settings)
    assert 0.9 <= _probe_duration_sec(output) <= 1.2


def _fingerprint(run_dir: Path) -> dict[str, object]:
    return render_input_fingerprint(
        run_dir,
        visual_settings={},
        pipeline_version="test-pipeline",
    )


def test_enabled_digital_human_changes_render_fingerprint_for_layout_and_upload(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "planning" / "digital_human.json"
    upload_path = tmp_path / "planning" / "digital_human" / "digi_upload.mp4"
    _write(
        config_path,
        json.dumps(
            {
                "enabled": True,
                "mode": "upload",
                "circle": {"cx": 0.8, "cy": 0.2, "r": 0.25},
            }
        ),
    )
    _write(upload_path, b"first-upload")

    first = _fingerprint(tmp_path)
    assert first["components"]["planning/digital_human.json"]
    assert first["components"]["planning/digital_human/digi_upload.mp4"]

    _write(upload_path, b"replacement-upload")
    second = _fingerprint(tmp_path)
    assert second["digest"] != first["digest"]

    _write(
        config_path,
        json.dumps(
            {
                "enabled": True,
                "mode": "upload",
                "circle": {"cx": 0.6, "cy": 0.2, "r": 0.25},
            }
        ),
    )
    assert _fingerprint(tmp_path)["digest"] != second["digest"]


def test_disabled_digital_human_does_not_change_ordinary_render_fingerprint(
    tmp_path: Path,
) -> None:
    before = _fingerprint(tmp_path)
    _write(
        tmp_path / "planning" / "digital_human.json",
        json.dumps({"enabled": False, "mode": "upload"}),
    )

    assert _fingerprint(tmp_path)["digest"] == before["digest"]


def test_submission_key_changes_when_enabled_upload_changes(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "planning" / "digital_human.json"
    upload_path = tmp_path / "planning" / "digital_human" / "digi_upload.mp4"
    _write(config_path, json.dumps({"enabled": True, "mode": "upload"}))
    _write(upload_path, b"first-upload")
    fingerprint = _fingerprint(tmp_path)
    artifacts = SimpleNamespace(
        current_render_input_fingerprint=lambda _project: fingerprint,
    )
    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=lambda: None,
            artifact_service=artifacts,
            remotion_runner=SimpleNamespace(),
            config=_config(tmp_path),
        )
    )
    project = SimpleNamespace(id="digital-human", run_dir=str(tmp_path))
    first_key = service._submission_key(project)

    _write(upload_path, b"replacement-upload")
    fingerprint = _fingerprint(tmp_path)

    assert service._submission_key(project) != first_key


def test_uploaded_digital_human_composites_locally_without_9001(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id="digital-human", run_dir=str(tmp_path))
    source = tmp_path / "planning" / "digital_human" / "digi_upload.mp4"
    _write(source, b"source")
    _write(
        tmp_path / "planning" / "digital_human.json",
        json.dumps({"enabled": True, "mode": "upload"}),
    )
    base = tmp_path / "videos" / "render.mp4"
    _write(base, b"base")
    calls: list[dict[str, object]] = []

    def composite_circle(**kwargs):
        calls.append(kwargs)
        Path(kwargs["output"]).write_bytes(b"composited")

    monkeypatch.setitem(
        sys.modules,
        "digital_human_service",
        SimpleNamespace(composite_circle=composite_circle),
    )
    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=lambda: None,
            artifact_service=SimpleNamespace(),
            remotion_runner=SimpleNamespace(
                _validate_render_color=lambda *_args, **_kwargs: {"ok": True}
            ),
            config=_config(tmp_path),
        )
    )
    service._ensure_local_digital_human_ffmpeg = lambda: None
    service._set_task_stage = lambda *_args: None

    result, composited = service._apply_digital_human_composite(
        project,
        RemotionRenderResult(
            output_path=base,
            output_filename=base.name,
            color_validation={"ok": True},
        ),
        "task-id",
    )

    assert composited is True
    assert result.output_path.read_bytes() == b"composited"
    assert calls[0]["digi_video"] == source


def test_enabled_digital_human_missing_upload_fails_and_removes_base_output(
    tmp_path: Path,
) -> None:
    project = SimpleNamespace(id="digital-human", run_dir=str(tmp_path))
    _write(
        tmp_path / "planning" / "digital_human.json",
        json.dumps({"enabled": True, "mode": "upload"}),
    )
    base = tmp_path / "videos" / "render.mp4"
    _write(base, b"base")
    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=lambda: None,
            artifact_service=SimpleNamespace(),
            remotion_runner=SimpleNamespace(),
            config=_config(tmp_path),
        )
    )

    with pytest.raises(DigitalHumanCompositeError, match="未找到上传的视频"):
        service._apply_digital_human_composite(
            project,
            RemotionRenderResult(
                output_path=base,
                output_filename=base.name,
                color_validation={"ok": True},
            ),
            "task-id",
        )

    assert not base.exists()


def test_enabled_digital_human_missing_composite_output_fails_and_removes_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id="digital-human", run_dir=str(tmp_path))
    source = tmp_path / "planning" / "digital_human" / "digi_upload.mp4"
    _write(source, b"source")
    _write(
        tmp_path / "planning" / "digital_human.json",
        json.dumps({"enabled": True, "mode": "upload"}),
    )
    base = tmp_path / "videos" / "render.mp4"
    _write(base, b"base")
    monkeypatch.setitem(
        sys.modules,
        "digital_human_service",
        SimpleNamespace(composite_circle=lambda **_kwargs: None),
    )
    service = VideoRenderService(
        VideoRenderDependencies(
            session_factory=lambda: None,
            artifact_service=SimpleNamespace(),
            remotion_runner=SimpleNamespace(),
            config=_config(tmp_path),
        )
    )
    service._ensure_local_digital_human_ffmpeg = lambda: None
    service._set_task_stage = lambda *_args: None

    with pytest.raises(DigitalHumanCompositeError, match="未生成有效视频"):
        service._apply_digital_human_composite(
            project,
            RemotionRenderResult(
                output_path=base,
                output_filename=base.name,
                color_validation={"ok": True},
            ),
            "task-id",
        )

    assert not base.exists()
