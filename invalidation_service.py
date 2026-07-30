"""Unified downstream invalidation rules for project edits.

The service is intentionally independent of FastAPI and database sessions.
It mutates the supplied project model and generated files; the route owns the
single database commit after the service returns.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Iterable

from pipeline_lifecycle import (
    clear_all_reveal_artifacts,
    clear_audio_confirmation,
    clear_remotion_props,
    clear_slide_reveal_artifacts,
    mark_downstream_pending,
    mark_selected_stale,
    project_artifact_lock,
    read_json_file,
    write_json_atomic,
)
from pipeline_state import begin_step, complete_step, current_step_after_completion
from project_storage import planning_path, safe_child


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class InvalidationReport:
    reason: str
    affected_steps: tuple[int, ...]
    slide_ids: tuple[str, ...] = ()
    removed_paths: tuple[Path, ...] = ()


def _existing_removals(
    run_dir: str | Path,
    *,
    clear_audio: bool,
    clear_props: bool,
) -> list[Path]:
    removed: list[Path] = []
    if clear_audio:
        audio_path = planning_path(run_dir, "audio_confirmed.json")
        if clear_audio_confirmation(run_dir):
            removed.append(audio_path)
    if clear_props:
        props_path = safe_child(run_dir, "remotion_props.json")
        if clear_remotion_props(run_dir):
            removed.append(props_path)
    return removed


def complete_stage(project: Any, target_step: int) -> InvalidationReport:
    statuses = complete_step(project.get_step_status(), target_step)
    removed = _existing_removals(
        project.run_dir,
        clear_audio=target_step < 7,
        clear_props=target_step < 8,
    )
    project.current_step = current_step_after_completion(project.current_step, target_step)
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="stage_completed",
        affected_steps=tuple(range(target_step + 1, 9)),
        removed_paths=tuple(removed),
    )


def begin_stage(project: Any, target_step: int) -> InvalidationReport:
    statuses = begin_step(project.get_step_status(), target_step)
    project.current_step = target_step
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="stage_started",
        affected_steps=tuple(range(target_step, 9)),
    )


def upstream_content_changed(project: Any, source_step: int) -> InvalidationReport:
    """Invalidate everything derived from an edited article or storyboard."""
    statuses = complete_step(project.get_step_status(), source_step)
    removed = _existing_removals(project.run_dir, clear_audio=True, clear_props=True)
    project.current_step = source_step
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="article_changed" if source_step == 1 else "storyboard_changed",
        affected_steps=tuple(range(source_step + 1, 9)),
        removed_paths=tuple(removed),
    )


def empty_storyboard_changed(project: Any) -> InvalidationReport:
    """Keep an editable empty storyboard while invalidating all dependants."""
    statuses = project.get_step_status()
    statuses["2"] = "in_progress"
    mark_downstream_pending(statuses, from_step=3)
    removed = _existing_removals(project.run_dir, clear_audio=True, clear_props=True)
    project.current_step = 2
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="storyboard_empty",
        affected_steps=tuple(range(3, 9)),
        removed_paths=tuple(removed),
    )


def clear_slide_visual_derivatives(project: Any, slide_id: str) -> tuple[Path, ...]:
    """Remove Mask metadata and reveal assets derived from one source image."""
    normalized_slide_id = str(slide_id).strip()
    if not normalized_slide_id:
        return ()
    removed: list[Path] = []
    manifest_path = safe_child(project.run_dir, "reveal_manifest.json")
    with project_artifact_lock(project.run_dir):
        manifest = read_json_file(manifest_path)
        if isinstance(manifest, dict):
            changed = False
            for slide in manifest.get("slides", []) or []:
                if (
                    not isinstance(slide, dict)
                    or str(slide.get("slide_id") or "").strip() != normalized_slide_id
                ):
                    continue
                for field in ("groups", "semantic_blocks"):
                    if slide.get(field):
                        changed = True
                    slide[field] = []
                if slide.get("status") != "pending":
                    changed = True
                slide["status"] = "pending"
            if changed:
                write_json_atomic(manifest_path, manifest)
        elif manifest_path.exists():
            LOGGER.warning(
                "Invalid reveal manifest was left untouched while clearing slide %s",
                normalized_slide_id,
            )
        removed.extend(clear_slide_reveal_artifacts(project.run_dir, normalized_slide_id))
    return tuple(removed)


def slide_images_changed(
    project: Any,
    slide_ids: Iterable[str],
    *,
    all_images_exist: bool,
) -> InvalidationReport:
    normalized_ids = tuple(dict.fromkeys(str(value).strip() for value in slide_ids if str(value).strip()))
    removed: list[Path] = []
    with project_artifact_lock(project.run_dir):
        for slide_id in normalized_ids:
            removed.extend(clear_slide_visual_derivatives(project, slide_id))
        removed.extend(_existing_removals(project.run_dir, clear_audio=True, clear_props=True))

    statuses = project.get_step_status()
    statuses["3"] = "completed" if all_images_exist else "in_progress"
    mark_downstream_pending(statuses, from_step=4)
    project.current_step = 3
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="slide_image_changed",
        affected_steps=tuple(range(4, 9)),
        slide_ids=normalized_ids,
        removed_paths=tuple(dict.fromkeys(removed)),
    )


def subtitle_style_changed(project: Any) -> InvalidationReport:
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    statuses = project.get_step_status()
    if statuses.get("8") == "completed":
        statuses["8"] = "pending_reconfirmation"
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="subtitle_style_changed",
        affected_steps=(8,),
        removed_paths=tuple(removed),
    )


def video_background_changed(
    project: Any,
    slide_ids: Iterable[str],
) -> InvalidationReport:
    normalized_ids = tuple(dict.fromkeys(str(value).strip() for value in slide_ids if str(value).strip()))
    with project_artifact_lock(project.run_dir):
        removed = clear_all_reveal_artifacts(project.run_dir, normalized_ids)
    statuses = project.get_step_status()
    mark_selected_stale(statuses, (5, 8))
    project.current_step = 3
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="video_background_changed",
        affected_steps=(5, 8),
        slide_ids=normalized_ids,
        removed_paths=tuple(dict.fromkeys(removed)),
    )


def narration_synthesis_started(project: Any) -> InvalidationReport:
    removed = _existing_removals(project.run_dir, clear_audio=True, clear_props=False)
    statuses = begin_step(project.get_step_status(), 7)
    project.current_step = 7
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="narration_changed",
        affected_steps=(7, 8),
        removed_paths=tuple(removed),
    )
