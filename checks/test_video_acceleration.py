from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from remotion_runner import (
    RemotionRunner,
    RemotionRunnerDependencies,
    _remotion_hardware_acceleration,
)
from video_acceleration import (
    encoder_reencode_arguments,
    parse_ffmpeg_video_encoders,
    select_video_encoder,
)
from video_contracts import VideoRenderConfig


def _config(tmp_path: Path, *, mode: str = "auto") -> VideoRenderConfig:
    return VideoRenderConfig(
        repo_root=tmp_path,
        runs_root=tmp_path,
        pipeline_version="test",
        reveal_visual_lead_sec=0.2,
        bind_timeout_sec=1,
        build_props_timeout_sec=1,
        npm_install_timeout_sec=1,
        render_timeout_sec=1,
        color_process_timeout_sec=1,
        render_acceleration=mode,
    )


def test_hardware_encoder_selection_priority_and_cpu_fallback() -> None:
    available = parse_ffmpeg_video_encoders(
        " V..... h264_amf\n V..... h264_qsv\n V..... h264_nvenc\n V..... libx264"
    )
    selection = select_video_encoder("auto", available)
    assert selection.encoder == "h264_nvenc"
    assert selection.hardware is True

    cpu = select_video_encoder("auto", {"libx264"})
    assert cpu.encoder == "libx264"
    assert cpu.fallback_reason == "hardware_h264_encoder_not_advertised"
    assert select_video_encoder("cpu", available).encoder == "libx264"


def test_gpu_mode_is_explicit_when_hardware_encoder_is_not_advertised() -> None:
    with pytest.raises(RuntimeError, match="GPU 编码不可用"):
        select_video_encoder("gpu", {"libx264"})


def test_encoder_arguments_keep_hardware_and_cpu_quality_contracts() -> None:
    assert encoder_reencode_arguments("h264_nvenc") == [
        "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0",
    ]
    assert encoder_reencode_arguments("libx264") == [
        "-preset", "veryfast", "-crf", "18",
    ]


def test_remotion_uses_hardware_acceleration_for_selected_hardware_encoder() -> None:
    available = {"h264_nvenc", "libx264"}
    assert _remotion_hardware_acceleration(
        select_video_encoder("auto", available)
    ) == "if-possible"
    assert _remotion_hardware_acceleration(
        select_video_encoder("gpu", available)
    ) == "required"
    assert _remotion_hardware_acceleration(
        select_video_encoder("cpu", available)
    ) == "disable"


def test_runner_probes_ffmpeg_and_logs_cpu_fallback(tmp_path: Path) -> None:
    logs: list[tuple[str, dict[str, object]]] = []

    def command(args, **_kwargs):
        assert args[-1] == "-encoders"
        return SimpleNamespace(returncode=0, stdout=" V..... libx264", stderr="")

    runner = RemotionRunner(
        RemotionRunnerDependencies(
            config=_config(tmp_path),
            build_reveal_assets=lambda _project: None,
            write_project_log=lambda _project, event, **values: logs.append((event, values)),
            run_subprocess_bounded=command,
            resolve_media_tool=lambda name: "ffmpeg" if name == "ffmpeg" else None,
        )
    )
    selection = runner._select_video_encoder(SimpleNamespace(id="project"))
    assert selection.encoder == "libx264"
    assert logs[-1][0] == "step8_render_acceleration_selected"
    assert logs[-1][1]["fallback_reason"] == "hardware_h264_encoder_not_advertised"


def test_hardware_color_reencode_retries_cpu_on_failure(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    logs: list[tuple[str, dict[str, object]]] = []
    target = tmp_path / "render.mp4"
    target.write_bytes(b"video")

    def command(args, **_kwargs):
        commands.append(args)
        output = Path(args[-1])
        if "h264_nvenc" in args:
            return SimpleNamespace(returncode=1, stdout="", stderr="encoder unavailable")
        output.write_bytes(b"cpu")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    runner = RemotionRunner(
        RemotionRunnerDependencies(
            config=_config(tmp_path),
            build_reveal_assets=lambda _project: None,
            write_project_log=lambda _project, event, **values: logs.append((event, values)),
            run_subprocess_bounded=command,
            resolve_media_tool=lambda name: "ffmpeg" if name == "ffmpeg" else None,
        )
    )
    runner._container_already_bt709 = lambda _path: False
    verification_calls = 0

    def verify(_path):
        nonlocal verification_calls
        verification_calls += 1
        # Force stream-copy to fall through; the CPU retry must still verify.
        return verification_calls >= 2

    runner._verify_color_metadata_with_ffprobe = verify
    assert runner._normalize_video_color_metadata(
        target,
        SimpleNamespace(id="project"),
        select_video_encoder("auto", {"h264_nvenc", "libx264"}),
    )
    assert any("h264_nvenc" in command for command in commands)
    assert any("libx264" in command for command in commands)
    assert any(event == "step8_color_metadata_hardware_fallback" for event, _ in logs)


def test_hardware_color_reencode_retries_cpu_when_verify_fails(tmp_path: Path) -> None:
    """7.x nvenc 可能 rc=0 但写不出 ffprobe 可读的 bt709，必须仍降级 libx264。"""
    commands: list[list[str]] = []
    logs: list[tuple[str, dict[str, object]]] = []
    target = tmp_path / "render.mp4"
    target.write_bytes(b"video")

    def command(args, **_kwargs):
        commands.append(args)
        output = Path(args[-1])
        # Stage1 是流拷贝（不含编码器名）；Stage2 用 nvenc；Stage3 是 libx264 回退。
        if "h264_nvenc" in args:
            output.write_bytes(b"nvenc")
        elif "libx264" in args:
            output.write_bytes(b"cpu")
        else:
            output.write_bytes(b"copy")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    runner = RemotionRunner(
        RemotionRunnerDependencies(
            config=_config(tmp_path),
            build_reveal_assets=lambda _project: None,
            write_project_log=lambda _project, event, **values: logs.append((event, values)),
            run_subprocess_bounded=command,
            resolve_media_tool=lambda name: "ffmpeg" if name == "ffmpeg" else None,
        )
    )
    runner._container_already_bt709 = lambda _path: False

    def verify(path):
        # 只有 libx264 产物能通过复核，模拟流拷贝与 nvenc 产物元数据均不可读。
        return path.read_bytes() == b"cpu"

    runner._verify_color_metadata_with_ffprobe = verify
    assert runner._normalize_video_color_metadata(
        target,
        SimpleNamespace(id="project"),
        select_video_encoder("auto", {"h264_nvenc", "libx264"}),
    )
    assert any("h264_nvenc" in command for command in commands)
    assert any("libx264" in command for command in commands)
    fallback = next(
        values for event, values in logs
        if event == "step8_color_metadata_hardware_fallback"
    )
    assert fallback["verify_failed"] is True
