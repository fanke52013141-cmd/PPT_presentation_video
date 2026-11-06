"""A failed lip-sync run must preserve the previous confirmed result."""
from pathlib import Path
import subprocess

import pytest

from digital_human_lipsync import LipSyncRuntime, synthesize_lipsync


def make_runtime(tmp_path):
    root = tmp_path / "MuseTalk"
    for name in ["python.exe", "ffmpeg.exe", "scripts/realtime_inference.py",
                 "models/musetalkV15/unet.pth", "models/musetalkV15/musetalk.json"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return LipSyncRuntime(root, root / "python.exe", "revision", root / "ffmpeg.exe")


def test_failure_preserves_existing_video(tmp_path):
    runtime = make_runtime(tmp_path)
    base, audio, output = [tmp_path / name for name in ["base.mp4", "voice.wav", "result.mp4"]]
    for path in [base, audio, output]:
        path.write_bytes(path.name.encode())

    def execute(argv, **kwargs):
        if "scripts.realtime_inference" in argv:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        Path(argv[-1]).write_bytes(b"normalized")

    with pytest.raises(subprocess.TimeoutExpired):
        synthesize_lipsync(base, audio, output, runtime, execute=execute,
                          validate_result=lambda *args: None)
    assert output.read_bytes() == b"result.mp4"
    assert not list(runtime.repository.glob("ppt_job_*"))
    assert not list(runtime.repository.rglob("ppt_preparation.json"))


def test_invalid_model_environment_rejected_before_execution(tmp_path):
    runtime = make_runtime(tmp_path)
    (runtime.repository / "models/musetalkV15/unet.pth").unlink()
    with pytest.raises(ValueError, match="未就绪"):
        synthesize_lipsync(tmp_path / "base.mp4", tmp_path / "voice.wav",
                          tmp_path / "output.mp4", runtime,
                          execute=lambda *args, **kwargs: pytest.fail("must not execute"),
                          validate_result=lambda *args: None)
