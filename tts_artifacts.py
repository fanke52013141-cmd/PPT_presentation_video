"""Pure filesystem helpers for per-slide TTS artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from pipeline_lifecycle import remove_file
from project_storage import planning_path, slide_dir


REQUIRED_OUTPUT_KEYS = ("audio", "metadata", "srt", "timeline")


def confirmation_path(run_dir: str | Path) -> Path:
    return planning_path(run_dir, "audio_confirmed.json")


def is_audio_confirmed(run_dir: str | Path) -> bool:
    return confirmation_path(run_dir).is_file()


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
