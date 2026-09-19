"""Pure filesystem helpers for per-slide TTS artifacts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping


from artifact_fingerprint import sha256_file
from pipeline_lifecycle import remove_file
from project_storage import planning_path, slide_dir


REQUIRED_OUTPUT_KEYS = ("audio", "metadata", "srt", "timeline")
CONFIRMATION_SCHEMA_VERSION = 3
CONFIRMATION_HASH_KEYS = ("text",) + REQUIRED_OUTPUT_KEYS

# Optional service-side hook returning the *current* TTS runtime fingerprint
# (voice_id/model/speed/...) for a run directory.  Stored into
# ``audio_confirmed.json`` at confirm time so a later voice-settings change is
# detected without any write-time invalidation.  ``None`` (tests, unconfigured
# process) skips the comparison entirely.
_RUNTIME_RESOLVER: Callable[[str | Path], Mapping[str, Any] | None] | None = None


def set_confirmation_runtime_resolver(
    resolver: Callable[[str | Path], Mapping[str, Any] | None] | None,
) -> None:
    global _RUNTIME_RESOLVER
    _RUNTIME_RESOLVER = resolver


def _normalize_runtime(runtime: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(runtime, Mapping):
        return {}
    return {str(key): str(value or "").strip() for key, value in runtime.items()}


def confirmation_path(run_dir: str | Path) -> Path:
    return planning_path(run_dir, "audio_confirmed.json")


def artifact_hashes(run_dir: str | Path, slide_id: str) -> dict[str, str | None]:
    paths = artifact_paths(run_dir, slide_id)
    return {key: sha256_file(paths[key]) for key in CONFIRMATION_HASH_KEYS}


def build_confirmation_payload(
    run_dir: str | Path,
    slide_ids: list[str],
    *,
    confirmation_mode: str,
    confirmed_at: str | None = None,
    tts_runtime: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_ids = [str(slide_id).strip() for slide_id in slide_ids if str(slide_id).strip()]
    payload: dict[str, Any] = {
        "schema_version": CONFIRMATION_SCHEMA_VERSION,
        "confirmed": True,
        "confirmed_at": confirmed_at or datetime.now().isoformat(),
        "confirmation_mode": str(confirmation_mode or "user_reviewed"),
        "slide_ids": normalized_ids,
        "artifacts": {
            slide_id: artifact_hashes(run_dir, slide_id)
            for slide_id in normalized_ids
        },
    }
    runtime = _normalize_runtime(tts_runtime)
    if runtime:
        payload["tts_runtime"] = runtime
    return payload


def confirmation_status(
    run_dir: str | Path,
    slide_ids: list[str] | None = None,
) -> dict[str, Any]:
    path = confirmation_path(run_dir)
    if not path.is_file():
        return {"confirmed": False, "reason": "missing_confirmation"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"confirmed": False, "reason": "invalid_confirmation"}
    if not isinstance(payload, dict) or payload.get("schema_version") != CONFIRMATION_SCHEMA_VERSION:
        return {"confirmed": False, "reason": "legacy_confirmation"}
    if payload.get("confirmed") is not True:
        return {"confirmed": False, "reason": "not_confirmed"}

    stored_ids = [str(value).strip() for value in payload.get("slide_ids", []) if str(value).strip()]
    current_ids = (
        [str(value).strip() for value in slide_ids if str(value).strip()]
        if slide_ids is not None
        else stored_ids
    )
    if not current_ids or set(current_ids) != set(stored_ids) or len(current_ids) != len(stored_ids):
        return {"confirmed": False, "reason": "slide_set_changed"}

    stored_artifacts = payload.get("artifacts")
    if not isinstance(stored_artifacts, dict):
        return {"confirmed": False, "reason": "invalid_confirmation"}
    stale_slides: list[str] = []
    for slide_id in current_ids:
        expected = stored_artifacts.get(slide_id)
        current = artifact_hashes(run_dir, slide_id)
        if (
            not isinstance(expected, dict)
            or any(not current.get(key) for key in CONFIRMATION_HASH_KEYS)
            or any(expected.get(key) != current.get(key) for key in CONFIRMATION_HASH_KEYS)
        ):
            stale_slides.append(slide_id)
    if stale_slides:
        return {
            "confirmed": False,
            "reason": "artifacts_changed",
            "stale_slides": stale_slides,
        }
    stored_runtime = payload.get("tts_runtime")
    if _RUNTIME_RESOLVER is not None and isinstance(stored_runtime, dict) and stored_runtime:
        live_runtime = _RUNTIME_RESOLVER(run_dir)
        if live_runtime is not None:
            live = _normalize_runtime(live_runtime)
            stored = _normalize_runtime(stored_runtime)
            changed_keys = sorted(
                key
                for key in set(stored) | set(live)
                if stored.get(key, "") != live.get(key, "")
            )
            if changed_keys:
                return {
                    "confirmed": False,
                    "reason": "config_changed",
                    "changed_keys": changed_keys,
                }
    return {
        "confirmed": True,
        "reason": "confirmed",
        "schema_version": CONFIRMATION_SCHEMA_VERSION,
        "slide_ids": current_ids,
    }


def is_audio_confirmed(run_dir: str | Path, slide_ids: list[str] | None = None) -> bool:
    return bool(confirmation_status(run_dir, slide_ids).get("confirmed"))


def artifact_paths(run_dir: str | Path, slide_id: str) -> dict[str, Path]:
    target_slide_dir = slide_dir(run_dir, slide_id)
    return {
        "slide_dir": target_slide_dir,
        "text": target_slide_dir / "tts_text.txt",
        "audio": target_slide_dir / "voice.mp3",
        "metadata": target_slide_dir / "tts_metadata.json",
        "srt": target_slide_dir / "subtitles.srt",
        "timeline": target_slide_dir / "audio_timeline.json",
    }


def nonempty_file(path: str | Path) -> bool:
    target = Path(path)
    try:
        return target.is_file() and target.stat().st_size > 0
    except OSError:
        return False


def timeline_duration_sec(path: str | Path) -> float | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        duration = payload.get("audio_content_duration_sec")
        if duration is None:
            duration = payload.get("duration_sec")
        return float(duration) if duration is not None else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def artifact_status(run_dir: str | Path, slide_id: str) -> dict[str, Any]:
    paths = artifact_paths(run_dir, slide_id)
    exists = {name: nonempty_file(paths[name]) for name in REQUIRED_OUTPUT_KEYS}
    complete = all(exists.values())
    stale = False
    if complete and paths["text"].exists():
        try:
            text_mtime = paths["text"].stat().st_mtime
            oldest_output_mtime = min(paths[name].stat().st_mtime for name in REQUIRED_OUTPUT_KEYS)
            stale = oldest_output_mtime + 0.5 < text_mtime
        except OSError:
            stale = True
    return {
        "slide_id": slide_id,
        "audio_exists": exists["audio"],
        "complete": complete and not stale,
        "stale": stale,
        "missing_artifacts": [name for name, present in exists.items() if not present],
        "audio_bytes": paths["audio"].stat().st_size if exists["audio"] else 0,
        "duration_sec": timeline_duration_sec(paths["timeline"]),
    }


def remove_outputs(paths: Mapping[str, str | Path]) -> list[Path]:
    removed: list[Path] = []
    for key in REQUIRED_OUTPUT_KEYS:
        value = paths.get(key)
        if value is None:
            continue
        path = Path(value)
        if remove_file(path):
            removed.append(path)
    return removed
