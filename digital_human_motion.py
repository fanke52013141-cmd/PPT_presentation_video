"""Source-owned portrait motion preparation, independent of HTTP and model imports.

Model runtimes live in separate external environments. Cache publication occurs
only after successful inference and media validation; failed work never replaces
a previously usable base video.
"""
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

from artifact_fingerprint import sha256_file

_preparation_lock = threading.Lock()
MOTION_RECIPE_VERSION = "liveportrait-head-motion-v1"


@dataclass(frozen=True)
class PortraitRuntime:
    repository: Path
    python: Path
    revision: str

    def validate(self) -> None:
        if not self.revision.strip():
            raise ValueError("模型 revision 不能为空")
        if not self.python.is_file() or not (self.repository / "inference.py").is_file():
            raise ValueError("LivePortrait 独立运行环境未就绪")


def motion_cache_key(photo: Path, driving: Path, revision: str) -> str:
    """Use bytes and recipe revision, never filenames, as cache identity."""
    hashes = [sha256_file(photo), sha256_file(driving)]
    if not all(hashes):
        raise ValueError("讲师照片或动作视频不存在或无法读取")
    payload = [MOTION_RECIPE_VERSION, revision, *hashes]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def prepare_portrait_base(
    photo: Path,
    driving: Path,
    cache_root: Path,
    runtime: PortraitRuntime,
    *,
    execute: Callable,
    validate_video: Callable[[Path], None],
) -> Path:
    """Prepare a reusable silent base, serializing model/cache writes locally.

    execute must run a bounded, killable subprocess with the supplied argv and
    cwd. validate_video must reject empty/non-video outputs. No fallback may
    substitute the driver or a still image for a failed identity transfer.
    """
    runtime.validate()
    if photo.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("讲师形象必须是 PNG、JPEG 或 WebP 图片")
    if driving.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
        raise ValueError("动作模板必须是视频，不接受序列化模型文件")
    key = motion_cache_key(photo, driving, runtime.revision)
    root = cache_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / key
    with _preparation_lock:
        base = destination / "base.mp4"
        seal = destination / "complete.json"
        if base.is_file() and seal.is_file():
            try:
                saved = json.loads(seal.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            if saved.get("sha256") == sha256_file(base) and saved.get("key") == key:
                validate_video(base)
                return base
        with tempfile.TemporaryDirectory(prefix="motion-", dir=root) as temporary:
            work = Path(temporary)
            # Stable safe basenames also avoid shell quoting issues in upstream
            # video/audio helpers. Only trusted video/image inputs are accepted.
            source = work / ("portrait" + photo.suffix.lower())
            driver = work / ("driving" + driving.suffix.lower())
            shutil.copyfile(photo, source)
            shutil.copyfile(driving, driver)
            if key != motion_cache_key(source, driver, runtime.revision):
                raise ValueError("输入素材在准备期间发生变化，请重新提交")
            execute(
                [str(runtime.python), "inference.py", "-s", str(source),
                 "-d", str(driver), "-o", str(work), "--flag-crop-driving-video"],
                cwd=str(runtime.repository), timeout=3600, check=True,
                stdin=subprocess.DEVNULL,
            )
            generated = work / "portrait--driving.mp4"
            validate_video(generated)
            if not generated.is_file() or generated.stat().st_size == 0:
                raise ValueError("动作迁移未生成有效视频")
            destination.mkdir(exist_ok=True)
            staged = destination / "base.pending.mp4"
            shutil.copyfile(generated, staged)
            staged.replace(base)
            marker = destination / "complete.pending.json"
            marker.write_text(json.dumps({"key": key, "sha256": sha256_file(base),
                                          "revision": runtime.revision}), encoding="utf-8")
            marker.replace(seal)
        return base
