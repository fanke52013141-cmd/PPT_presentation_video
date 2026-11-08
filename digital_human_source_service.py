"""Project-owned motion sources and generation-input freshness."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

from artifact_fingerprint import sha256_bytes, sha256_file
from scripts.media_tools import probe_video_metadata
from pipeline_lifecycle import read_json_file, write_json_atomic


def project_avatars(run_dir: str | Path) -> dict:
    value = read_json_file(Path(run_dir) / "planning/digital_human/avatar_sources.json")
    return value if isinstance(value, dict) else {}


def register_project_avatar(run_dir: str | Path, avatar_id: str, digest: str) -> None:
    registry = project_avatars(run_dir)
    if registry.get(avatar_id) != digest:
        registry[avatar_id] = digest
        write_json_atomic(Path(run_dir) / "planning/digital_human/avatar_sources.json", registry)


def motion_path(run_dir: str | Path, source: str) -> Path:
    if source == "default":
        from repository_paths import DEFAULT_PORTRAIT_MOTION_VIDEO
        return Path(DEFAULT_PORTRAIT_MOTION_VIDEO)
    if source != "custom":
        raise ValueError("动作来源必须为 default 或 custom")
    return Path(run_dir) / "planning/digital_human/motion_reference.mp4"


def motion_summary(run_dir: str | Path, source: str) -> dict:
    path = motion_path(run_dir, source)
    metadata = probe_video_metadata(path) if path.is_file() else None
    return {"source": source, "exists": bool(metadata), "metadata": metadata}


def save_motion_video(run_dir: str | Path, content: bytes) -> bool:
    """Caller holds the project artifact lock; identical uploads are no-ops."""
    if not content:
        raise ValueError("动作视频为空")
    destination = motion_path(run_dir, "custom")
    if sha256_file(destination) == sha256_bytes(content):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("motion-" + uuid.uuid4().hex + ".mp4")
    try:
        temporary.write_bytes(content)
        if not probe_video_metadata(temporary):
            raise ValueError("动作视频无法解码或缺少有效画面")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def generation_source_fingerprint(run_dir: str | Path, config: dict, *, motion_sha256: str | None = None) -> str:
    if config.get("mode") != "portrait":
        return ""
    path = motion_path(run_dir, str(config.get("motion_source") or "default"))
    payload = ["portrait-source-v1", config.get("avatar_id"),
               motion_sha256 if motion_sha256 is not None else sha256_file(path)]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def presenter_source_stale(run_dir: str | Path, config: dict, entry: dict, *, pending: bool = False) -> bool:
    binding = entry if pending else (entry.get("published") or {})
    return bool(config.get("mode") == "portrait" and
                binding.get("source_sha256") != generation_source_fingerprint(run_dir, config))


def published_audio_hash(entry: dict) -> str:
    published = entry.get("published") or {}
    return str(published.get("audio_sha256") or (
        entry.get("audio_sha256") if entry.get("status") == "done" and not entry.get("pending_request") else ""
    ) or "")


def presenter_audio_stale(run_dir: str | Path, entry: dict, slide_id: str) -> bool:
    stored = published_audio_hash(entry)
    if not stored:
        return True
    if slide_id == "full":
        from digital_human_audio_service import full_audio_current
        path = Path(run_dir) / "planning/digital_human/audio_full.mp3"
        return not full_audio_current(run_dir) or stored != sha256_file(path)
    return stored != sha256_file(Path(run_dir) / "slides" / slide_id / "voice.mp3")


def presenter_readiness(run_dir: str | Path, config: dict | None = None) -> dict:
    """Read-only readiness of the optional presenter for final composition.

    Shared by ``project.state`` observation and the final render precondition so
    the Agent never receives ``can_submit=true`` for a presenter that the render
    stage would reject later.  Returns explicit machine-readable issue codes:

    - ``motion_missing``: portrait mode has no default template and no upload.
    - ``upload_video_missing``: upload mode has not received its finished video.
    - ``presenter_video_missing``: model-generated full presenter is absent.
    - ``presenter_source_stale``: photo or driving video changed since publish.
    - ``presenter_audio_stale``: confirmed course audio changed since publish.
    """
    from digital_human_contracts import load_config

    root = Path(run_dir)
    cfg = config if isinstance(config, dict) else load_config(root)
    enabled = bool(cfg.get("enabled"))
    mode = str(cfg.get("mode") or "portrait").strip().lower()
    digi_dir = root / "planning" / "digital_human"
    checks: dict[str, list[str]] = {"motion": [], "presenter": [], "audio": []}
    motion = {"source": str(cfg.get("motion_source") or "default"), "exists": False}

    if not enabled:
        return {
            "enabled": False, "mode": mode, "required": False, "ready": True,
            "motion": motion,
            "presenter": {"video_exists": False, "source_stale": False, "audio_stale": False},
            "checks": checks, "issues": [],
        }

    if mode == "portrait":
        motion = motion_summary(root, motion["source"])
        if not motion.get("exists"):
            checks["motion"].append("motion_missing")
        video = digi_dir / "digi_full.mp4"
        entry = (cfg.get("slides") or {}).get("full") or {}
        source_stale = bool(video.is_file() and presenter_source_stale(root, cfg, entry))
        audio_stale = bool(video.is_file() and presenter_audio_stale(root, entry, "full"))
    elif mode == "upload":
        video = digi_dir / "digi_upload.mp4"
        source_stale = False
        audio_stale = False
    else:
        video = digi_dir / "digi_full.mp4"
        source_stale = False
        audio_stale = False

    video_exists = video.is_file() and video.stat().st_size > 0
    if not video_exists:
        checks["presenter"].append(
            "upload_video_missing" if mode == "upload" else "presenter_video_missing"
        )
    if source_stale:
        checks["presenter"].append("presenter_source_stale")
    if audio_stale:
        checks["audio"].append("presenter_audio_stale")
    issues = [issue for reasons in checks.values() for issue in reasons]
    return {
        "enabled": True, "mode": mode, "required": True, "ready": not issues,
        "motion": motion,
        "presenter": {
            "video_exists": video_exists,
            "source_stale": source_stale,
            "audio_stale": audio_stale,
        },
        "checks": checks, "issues": issues,
    }
