"""Project-scoped logging, artifact, and workflow runtime helpers."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional

import invalidation_service
from narration_audio_service import beat_tts_text, clean_tts_text
from pipeline_lifecycle import project_artifact_lock
from pipeline_state import mark_retry_needed
from reveal_manifest_service import sync_reveal_manifest
from tts_artifacts import (
    artifact_paths as tts_artifact_paths,
    artifact_status as tts_artifact_status,
    confirmation_path as tts_confirmation_path,
    is_audio_confirmed,
    nonempty_file as tts_nonempty_file,
    remove_outputs as remove_tts_outputs,
    timeline_duration_sec,
)
from visual_contract_service import read_contract_slide_ids


logger = logging.getLogger("PPTStudio")


def reveal_lock_for(project: Any):
    return project_artifact_lock(project.run_dir)


def _redact_log_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(
        token in lowered
        for token in (
            "api_key",
            "apikey",
            "authorization",
            "token",
            "secret",
        )
    ):
        return "***REDACTED***" if value else value
    if isinstance(value, str) and len(value) > 4000:
        return (
            value[:4000]
            + f"\n... [truncated {len(value) - 4000} chars]"
        )
    return value


def write_project_log(
    project: Any,
    event: str,
    **fields: Any,
) -> None:
    try:
        log_dir = os.path.join(project.run_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "project_id": project.id,
            "event": event,
        }
        record.update(
            {
                key: _redact_log_value(key, value)
                for key, value in fields.items()
            }
        )
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(
            os.path.join(log_dir, "pipeline.log"),
            "a",
            encoding="utf-8",
        ) as file:
            file.write(line + "\n")
        logger.info(
            "project=%s event=%s %s",
            project.id,
            event,
            line,
        )
    except Exception as exc:
        logger.warning(
            "Failed to write project log for %s: %s",
            getattr(project, "id", "<unknown>"),
            exc,
        )


def all_current_slide_images_exist(project: Any) -> bool:
    slide_ids = read_contract_slide_ids(project.run_dir)
    if not slide_ids:
        return False
    return all(
        os.path.exists(
            os.path.join(
                project.run_dir,
                "slides",
                slide_id,
                "visual_draft.png",
            )
        )
        for slide_id in slide_ids
    )


def sync_reveal_manifest_to_contract(
    project: Any,
    slide_ids: Optional[List[str]] = None,
) -> bool:
    explicit_slide_ids = slide_ids is not None
    current_slide_ids = (
        slide_ids
        if explicit_slide_ids
        else read_contract_slide_ids(project.run_dir)
    )
    return sync_reveal_manifest(
        project,
        current_slide_ids,
        allow_empty=explicit_slide_ids,
    )


def audio_confirmation_path(project: Any) -> str:
    return str(tts_confirmation_path(project.run_dir))


def project_audio_confirmed(project: Any) -> bool:
    return is_audio_confirmed(
        project.run_dir,
        read_contract_slide_ids(project.run_dir),
    )


def nonempty_file(path: str) -> bool:
    return tts_nonempty_file(path)


def slide_tts_artifact_paths(
    project: Any,
    slide_id: str,
) -> Dict[str, str]:
    return {
        key: str(path)
        for key, path in tts_artifact_paths(
            project.run_dir,
            slide_id,
        ).items()
    }


def read_timeline_duration_sec(
    timeline_path: str,
) -> Optional[float]:
    return timeline_duration_sec(timeline_path)


def slide_tts_artifact_status(
    project: Any,
    slide_id: str,
) -> Dict[str, Any]:
    return tts_artifact_status(project.run_dir, slide_id)


def remove_tts_artifacts(paths: Dict[str, str]) -> None:
    remove_tts_outputs(paths)


def ensure_slide_tts_text_file(
    project: Any,
    slide_id: str,
    contract: Dict[str, Any],
) -> str:
    paths = slide_tts_artifact_paths(project, slide_id)
    text_file = paths["text"]
    if os.path.exists(text_file):
        return text_file

    logger.warning(
        "tts_text.txt not found for slide %s, "
        "trying to generate it from contract",
        slide_id,
    )
    slide_narration = ""
    for slide in contract.get("slides", []) or []:
        if (
            not isinstance(slide, dict)
            or slide.get("slide_id") != slide_id
        ):
            continue
        beats = (
            slide.get("narration_beats", [])
            if isinstance(slide.get("narration_beats"), list)
            else []
        )
        slide_narration = "\n".join(
            beat_tts_text(beat)
            for beat in beats
            if (
                isinstance(beat, dict)
                and clean_tts_text(beat_tts_text(beat))
            )
        )
        break
    os.makedirs(os.path.dirname(text_file), exist_ok=True)
    with open(text_file, "w", encoding="utf-8") as file:
        file.write(slide_narration + "\n")
    return text_file


def mark_step_retry_needed(
    project: Any,
    target_step: int,
    db: Any,
) -> None:
    current_status = mark_retry_needed(
        project.get_step_status(),
        target_step,
    )
    project.current_step = target_step
    project.set_step_status(current_status)
    db.commit()


def mark_step_in_progress(
    project: Any,
    target_step: int,
    db: Any,
) -> None:
    invalidation_service.begin_stage(project, target_step)
    db.commit()


def handle_step_navigation(
    project: Any,
    target_step: int,
    db: Any,
) -> None:
    invalidation_service.complete_stage(project, target_step)
    db.commit()


def begin_storyboard_after_article_import(
    project: Any,
    db: Any,
) -> None:
    """Complete Step 1 and make Step 2 the resumable active stage."""
    invalidation_service.upstream_content_changed(project, 1)
    invalidation_service.begin_stage(project, 2)
    db.commit()


def invalidate_after_upstream_edit(
    project: Any,
    source_step: int,
    db: Any,
) -> None:
    invalidation_service.upstream_content_changed(
        project,
        source_step,
    )
    db.commit()


def clear_slide_visual_derivatives(
    project: Any,
    slide_id: str,
) -> None:
    invalidation_service.clear_slide_visual_derivatives(
        project,
        slide_id,
    )


def mark_slide_image_changed(
    project: Any,
    slide_id: str,
    db: Any,
) -> None:
    invalidation_service.slide_images_changed(
        project,
        [slide_id],
        all_images_exist=all_current_slide_images_exist(project),
    )
    db.commit()
