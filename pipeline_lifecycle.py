"""Central file and status lifecycle rules for generated project artifacts.

This module deliberately has no FastAPI or database dependency.  Callers own
database commits and Manifest mutation; this module owns deterministic artifact
paths, deletion semantics, and downstream step-state transitions.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
from typing import Any, Iterable, MutableMapping

from project_storage import planning_path, safe_child, slide_dir


LOGGER = logging.getLogger(__name__)
REVEAL_FILENAMES = ("scene.json", "animation_timeline.json", "reveal_report.json")
TTS_FILENAMES = ("voice.mp3", "tts_metadata.json", "subtitles.srt", "audio_timeline.json")


def remove_file(path: str | Path) -> bool:
    """Remove one file and report whether an artifact existed."""
    target = Path(path)
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        LOGGER.warning("Failed to remove generated artifact %s: %s", target, exc)
        return False


def remove_tree(path: str | Path) -> bool:
    """Remove one generated directory without escaping to parent paths."""
    target = Path(path)
    if not target.exists():
        return False
    try:
        shutil.rmtree(target)
        return True
    except OSError as exc:
        LOGGER.warning("Failed to remove generated artifact directory %s: %s", target, exc)
        return False


def clear_remotion_props(run_dir: str | Path) -> bool:
    return remove_file(safe_child(run_dir, "remotion_props.json"))


def clear_audio_confirmation(run_dir: str | Path) -> bool:
    return remove_file(planning_path(run_dir, "audio_confirmed.json"))


def clear_slide_reveal_artifacts(run_dir: str | Path, slide_id: str) -> list[Path]:
    target_slide_dir = slide_dir(run_dir, slide_id)
    removed: list[Path] = []
    for filename in REVEAL_FILENAMES:
        path = target_slide_dir / filename
        if remove_file(path):
            removed.append(path)
    assets_dir = target_slide_dir / "assets"
    if remove_tree(assets_dir):
        removed.append(assets_dir)
    if clear_remotion_props(run_dir):
        removed.append(safe_child(run_dir, "remotion_props.json"))
    return removed


def clear_all_reveal_artifacts(run_dir: str | Path, slide_ids: Iterable[str]) -> list[Path]:
    removed: list[Path] = []
    for slide_id in slide_ids:
        removed.extend(clear_slide_reveal_artifacts(run_dir, str(slide_id)))
    # Handles projects whose contract currently has no slides.
    props_path = safe_child(run_dir, "remotion_props.json")
    if clear_remotion_props(run_dir) and props_path not in removed:
        removed.append(props_path)
    return removed


def mark_downstream_pending(
    statuses: MutableMapping[str, Any],
    *,
    from_step: int,
    through_step: int = 8,
) -> MutableMapping[str, Any]:
    """Downgrade downstream steps while preserving completed/stale distinction."""
    for step in range(from_step, through_step + 1):
        key = str(step)
        statuses[key] = "pending_reconfirmation" if statuses.get(key) == "completed" else "pending"
    return statuses


def mark_selected_stale(
    statuses: MutableMapping[str, Any], step_numbers: Iterable[int]
) -> MutableMapping[str, Any]:
    for step in step_numbers:
        key = str(step)
        if statuses.get(key) == "completed":
            statuses[key] = "pending_reconfirmation"
        elif statuses.get(key) != "pending":
            statuses[key] = "pending"
    return statuses
