"""Bounded MuseTalk 1.5 adapter; keeps optional model imports out of the app."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Callable
import uuid

from artifact_fingerprint import sha256_file

_inference_lock = threading.Lock()


@dataclass(frozen=True)
class LipSyncRuntime:
    repository: Path
    python: Path
    revision: str
    ffmpeg: Path

    def validate(self) -> None:
        required = [self.python, self.ffmpeg,
                    self.repository / "scripts/realtime_inference.py",
                    self.repository / "models/musetalkV15/unet.pth",
                    self.repository / "models/musetalkV15/musetalk.json"]
        if not self.revision.strip() or not all(path.is_file() for path in required):
            raise ValueError("MuseTalk 1.5 模型或独立运行环境未就绪")
        # Upstream currently interpolates these paths into ffmpeg shell commands.
        # Reject unsupported roots explicitly instead of producing broken output.
        root = str(self.repository.resolve())
        if any(character.isspace() or character in '&|;`$<>\"\'' for character in root):
            raise ValueError("MuseTalk 运行目录不能包含空格或 shell 特殊字符")


def synthesize_lipsync(
    base_video: Path,
    audio: Path,
    output: Path,
    runtime: LipSyncRuntime,
    *,
    execute: Callable,
    validate_result: Callable[[Path, Path], None],
) -> Path:
    """Reuse preprocessed bases; publish only validated audio-matched results.

    The caller supplies a killable executor and duration/stream validator. A
    process-local lock protects upstream's shared avatar directories and GPU.
    """
    runtime.validate()
    base_hash, audio_hash = sha256_file(base_video), sha256_file(audio)
    if not base_hash or not audio_hash:
        raise ValueError("讲师底片与已确认旁白必须存在")
    identity = hashlib.sha256(json.dumps(
        ["musetalk-v15-fps25-v1", runtime.revision, base_hash],
        separators=(",", ":"),
    ).encode()).hexdigest()
    avatar = "ppt_" + identity
    root = runtime.repository.resolve()
    avatar_root = root / "results/v15/avatars" / avatar
    complete = avatar_root / "ppt_preparation.json"
    with _inference_lock:
        with tempfile.TemporaryDirectory(prefix="ppt_job_", dir=root) as temporary:
            work = Path(temporary)
            normalized = work / "base.mp4"
            voice = work / "voice.wav"
            common = dict(timeout=600, check=True, stdin=subprocess.DEVNULL)
            execute([str(runtime.ffmpeg), "-y", "-i", str(base_video.resolve()),
                     "-an", "-vf", "fps=25", "-c:v", "libx264", "-pix_fmt",
                     "yuv420p", str(normalized)], **common)
            execute([str(runtime.ffmpeg), "-y", "-i", str(audio.resolve()),
                     "-vn", "-ar", "16000", "-ac", "1", str(voice)], **common)
            if base_hash != sha256_file(base_video) or audio_hash != sha256_file(audio):
                raise ValueError("底片或旁白在生成期间发生变化")
            # The upstream CLI prompts interactively on a partial old avatar.
            # Only this adapter's hash-owned cache may be rebuilt automatically.
            preparation = not complete.is_file()
            if preparation and avatar_root.exists():
                if avatar_root.parent != root / "results/v15/avatars":
                    raise ValueError("缓存路径超出模型工作目录")
                shutil.rmtree(avatar_root)
            request = uuid.uuid4().hex
            config = work / "request.json"
            config.write_text(json.dumps({avatar: {
                "preparation": preparation, "video_path": str(normalized),
                "bbox_shift": 0, "audio_clips": {request: str(voice)},
            }}), encoding="utf-8")
            execute([str(runtime.python), "-m", "scripts.realtime_inference",
                     "--version", "v15", "--inference_config", str(config),
                     "--unet_config", "models/musetalkV15/musetalk.json",
                     "--unet_model_path", "models/musetalkV15/unet.pth",
                     "--ffmpeg_path", str(runtime.ffmpeg.parent),
                     "--fps", "25", "--batch_size", "4"],
                    cwd=str(root), timeout=7200, check=True, stdin=subprocess.DEVNULL)
            generated = avatar_root / "vid_output" / (request + ".mp4")
            validate_result(generated, audio)
            if not generated.is_file() or not generated.stat().st_size:
                raise ValueError("对口型模型没有生成有效视频")
            output = output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            staged = output.with_name(output.stem + "." + request + ".pending.mp4")
            try:
                # Keep the exact confirmed narration, not MuseTalk's resampled input.
                execute([str(runtime.ffmpeg), "-y", "-i", str(generated), "-i",
                         str(audio.resolve()), "-map", "0:v:0", "-map", "1:a:0",
                         "-c:v", "copy", "-c:a", "aac", "-shortest", str(staged)], **common)
                validate_result(staged, audio)
                staged.replace(output)
                complete.write_text(json.dumps({"identity": identity}), encoding="utf-8")
            finally:
                staged.unlink(missing_ok=True)
                generated.unlink(missing_ok=True)
    return output
