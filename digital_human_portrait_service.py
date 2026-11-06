"""Photo motion + lip-sync orchestration shared by jobs and offline verification."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import threading

from digital_human_lipsync import LipSyncRuntime, synthesize_lipsync
from digital_human_motion import PortraitRuntime, prepare_portrait_base
from runtime_support import run_subprocess_killable
from artifact_fingerprint import sha256_file
from scripts.media_tools import probe_media_duration_sec, probe_video_metadata, resolve_media_tool

_pipeline_lock = threading.Lock()


@dataclass(frozen=True)
class PortraitPipelineDependencies:
    motion: PortraitRuntime
    lipsync: LipSyncRuntime
    cache_root: Path


def configured_dependencies() -> PortraitPipelineDependencies:
    """Resolve administrator-installed optional runtimes without importing models."""
    import repository_paths as paths

    def revision(root, relative_paths):
        hashes = [sha256_file(root / name) or "missing" for name in relative_paths]
        return hashlib.sha256("|".join(hashes).encode()).hexdigest()

    motion, lipsync = Path(paths.LIVEPORTRAIT_REPO), Path(paths.MUSETALK_REPO)
    ffmpeg = resolve_media_tool("ffmpeg", Path(paths.REPO_ROOT))
    if not ffmpeg:
        raise ValueError("FFmpeg 未就绪")
    return PortraitPipelineDependencies(
        PortraitRuntime(motion, motion / ".venv/Scripts/python.exe", revision(motion, [
            "inference.py", "src/live_portrait_pipeline.py",
            "pretrained_weights/liveportrait/base_models/motion_extractor.pth",
            "pretrained_weights/liveportrait/base_models/appearance_feature_extractor.pth",
            "pretrained_weights/liveportrait/base_models/spade_generator.pth",
            "pretrained_weights/liveportrait/retargeting_models/stitching_retargeting_module.pth",
        ])),
        LipSyncRuntime(lipsync, lipsync / ".venv/Scripts/python.exe", revision(lipsync, [
            "scripts/realtime_inference.py", "models/musetalkV15/unet.pth",
            "models/musetalkV15/musetalk.json", "ppt_windows_configuration.json",
        ]), Path(ffmpeg)), Path(paths.PORTRAIT_CACHE_DIR),
    )


def execute_model(argv, *, timeout, **kwargs):
    check = kwargs.pop("check", False)
    result = run_subprocess_killable(argv, timeout_sec=timeout, **kwargs)
    if check:
        result.check_returncode()
    return result


def validate_video(path: Path) -> None:
    if not path.is_file() or not path.stat().st_size:
        raise ValueError(f"Missing generated video: {path}")
    if not probe_video_metadata(path) or (probe_media_duration_sec(path) or 0) <= 0:
        raise ValueError(f"Invalid generated video: {path}")


def validate_lipsync(video: Path, audio: Path) -> None:
    validate_video(video)
    expected, actual = probe_media_duration_sec(audio), probe_media_duration_sec(video)
    if not expected or not actual or abs(actual - expected) > 0.25:
        raise ValueError(f"Lip-sync duration mismatch: video={actual}, narration={expected}")


def run_portrait_pipeline(
    photo: Path, driving: Path, audio: Path, output: Path,
    dependencies: PortraitPipelineDependencies,
) -> Path:
    """Validate environments first, prepare reusable motion, then match narration."""
    dependencies.motion.validate()
    dependencies.lipsync.validate()
    environment = dict(os.environ)
    environment["PATH"] = str(dependencies.lipsync.ffmpeg.parent) + os.pathsep + environment.get("PATH", "")
    environment["PYTHONUTF8"] = "1"
    # Official, administrator-installed model checkpoints contain NumPy metadata.
    # This applies only to the isolated model subprocess, never uploaded inputs.
    environment["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"

    def execute(argv, **kwargs):
        return execute_model(argv, env=environment, **kwargs)

    with _pipeline_lock:
        base = prepare_portrait_base(photo, driving, dependencies.cache_root, dependencies.motion,
                                     execute=execute, validate_video=validate_video)
        return synthesize_lipsync(base, audio, output, dependencies.lipsync,
                                 execute=execute, validate_result=validate_lipsync)
