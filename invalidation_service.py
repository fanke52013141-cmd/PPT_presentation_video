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
import uuid

from impact_registry import IMPACT_RULES
from impact_source_version import impact_source_version
from project_impact_service import record_impact

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
from pipeline_state import current_step_after_completion
from project_storage import planning_path, safe_child


LOGGER = logging.getLogger(__name__)


def _record_content_impact(project: Any, reason: str, slide_ids: Iterable[str] = ()) -> None:
    """Bind a real business edit to its current project/page input version."""
    normalized = tuple(dict.fromkeys(str(value).strip() for value in slide_ids if str(value).strip()))
    if IMPACT_RULES[reason].scope == "slide" and normalized:
        for slide_id in normalized:
            record_impact(
                project.run_dir, reason=reason, slide_ids=(slide_id,),
                source_version=impact_source_version(project.run_dir, reason, slide_id),
            )
    else:
        record_impact(
            project.run_dir, reason=reason,
            source_version=impact_source_version(project.run_dir, reason, "project"),
        )


@dataclass(frozen=True)
class InvalidationReport:
    reason: str
    affected_steps: tuple[int, ...]
    slide_ids: tuple[str, ...] = ()
    removed_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if self.reason not in IMPACT_RULES:
            raise ValueError(f"Unregistered downstream impact: {self.reason}")


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
    previous = project.get_step_status()
    # Confirming an already completed stage is idempotent.  The stage action
    # that changed an input is responsible for invalidating its dependants.
    if previous.get(str(target_step)) == "completed":
        return InvalidationReport(reason="stage_already_completed", affected_steps=())
    # Completion is a status transition.  Input-changing operations register
    # their own dependency impact at the point of mutation.
    statuses = dict(previous)
    statuses[str(target_step)] = "completed"
    project.current_step = current_step_after_completion(project.current_step, target_step)
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="stage_completed",
        affected_steps=(),
    )


def begin_stage(project: Any, target_step: int) -> InvalidationReport:
    statuses = project.get_step_status()
    if statuses.get(str(target_step)) == "completed":
        return InvalidationReport(reason="stage_already_completed", affected_steps=())
    statuses[str(target_step)] = "in_progress"
    project.current_step = target_step
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="stage_started",
        affected_steps=(),
    )


def upstream_content_changed(project: Any, source_step: int) -> InvalidationReport:
    """Keep existing work available while flagging changed upstream inputs."""
    statuses = project.get_step_status()
    statuses[str(source_step)] = "completed"
    if source_step == 1:
        mark_selected_stale(statuses, (2,))
        affected = (2,)
        # The article is not a render input. Keep existing downstream assets
        # until a real storyboard change establishes a concrete dependency.
        removed = []
    else:
        mark_downstream_pending(statuses, from_step=3)
        affected = tuple(range(3, 9))
        removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    project.current_step = source_step
    project.set_step_status(statuses)
    _record_content_impact(project, "article_changed" if source_step == 1 else "storyboard_changed")
    return InvalidationReport(
        reason="article_changed" if source_step == 1 else "storyboard_changed",
        affected_steps=affected,
        removed_paths=tuple(removed),
    )


def storyboard_contract_changed(
    project: Any,
    *,
    visual_slide_ids: Iterable[str] = (),
    narration_slide_ids: Iterable[str] = (),
    added_slide_ids: Iterable[str] = (),
    removed_slide_ids: Iterable[str] = (),
    reordered: bool = False,
    empty: bool = False,
    previous_contract: Any = None,
) -> InvalidationReport:
    """Scope a Step 2 edit to the actual slide capabilities it changes."""
    normalize = lambda values: tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    added = normalize(added_slide_ids)
    visual = normalize((*visual_slide_ids, *added))
    narration = normalize((*narration_slide_ids, *added))
    removed_ids = normalize(removed_slide_ids)
    structure_changed = bool(removed_ids or reordered or empty)
    # narration-only 编辑:把逐页图片 provenance 迁移到当前视觉投影,
    # 让已批准图片在渲染门保持有效(与下方分类器同一投影口径)。
    # 迁移内部有三重证据防护,视觉编辑永远洗不白;失败不阻塞失效流程。
    if previous_contract is not None and narration:
        try:
            from visual_provenance import refresh_provenance_for_contract_impact

            refresh_provenance_for_contract_impact(
                project.run_dir,
                previous_contract,
                visual_slide_ids=visual,
                narration_slide_ids=narration,
                added_slide_ids=added,
            )
        except Exception as exc:  # noqa: BLE001 - 渲染门哈希校验兜底
            LOGGER.debug("narration-only provenance refresh failed for %s: %s", project.run_dir, exc)
    statuses = project.get_step_status()
    statuses["2"] = "in_progress" if empty else "completed"
    affected: set[int] = set()
    if visual:
        mark_selected_stale(statuses, (3, 4, 5, 8))
        affected.update((3, 4, 5, 8))
        _record_content_impact(project, "storyboard_visual_changed", visual)
    if narration:
        mark_selected_stale(statuses, (6, 7, 8))
        affected.update((6, 7, 8))
        _record_content_impact(project, "storyboard_narration_changed", narration)
    if structure_changed:
        mark_selected_stale(statuses, (8,))
        affected.add(8)
        _record_content_impact(project, "storyboard_structure_changed")
    removed_paths = (
        _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
        if affected else []
    )
    project.current_step = 2
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="storyboard_changed",
        affected_steps=tuple(sorted(affected)),
        slide_ids=tuple(dict.fromkeys((*visual, *narration, *removed_ids))),
        removed_paths=tuple(removed_paths),
    )


def storyboard_script_changed(project: Any) -> InvalidationReport:
    """Require visual planning again while retaining existing artifacts for recovery."""
    statuses = project.get_step_status()
    statuses["2"] = "in_progress"
    project.current_step = 2
    project.set_step_status(statuses)
    record_impact(project.run_dir, reason="storyboard_script_changed")
    return InvalidationReport(
        reason="storyboard_script_changed",
        affected_steps=(2,),
    )


def empty_storyboard_changed(project: Any) -> InvalidationReport:
    """Keep an editable empty storyboard while invalidating all dependants."""
    statuses = project.get_step_status()
    statuses["2"] = "in_progress"
    mark_downstream_pending(statuses, from_step=3)
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    project.current_step = 2
    project.set_step_status(statuses)
    _record_content_impact(project, "storyboard_empty")
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
                if slide.get("groups") or slide.get("semantic_blocks"):
                    recovery_path = safe_child(
                        project.run_dir,
                        "recovery",
                        "masks",
                        f"{normalized_slide_id}-{uuid.uuid4().hex}.json",
                    )
                    write_json_atomic(recovery_path, slide)
                for field in ("groups", "semantic_blocks"):
                    if slide.get(field):
                        changed = True
                    slide[field] = []
                if slide.get("status") != "pending":
                    changed = True
                slide["status"] = "pending"
                annotation = manifest.get("ai_mask_annotation")
                # 标注完成记录覆盖了这张已被替换的图片，保留会让 AI Mask
                # 状态显示为已完成而实际组数据刚被清空。
                if isinstance(annotation, dict) and normalized_slide_id in {
                    str(value) for value in annotation.get("scope_slide_ids") or []
                }:
                    manifest.pop("ai_mask_annotation", None)
                    changed = True
            if changed:
                write_json_atomic(manifest_path, manifest)
        elif manifest_path.exists():
            LOGGER.warning(
                "Invalid reveal manifest was left untouched while clearing slide %s",
                normalized_slide_id,
            )
        removed.extend(clear_slide_reveal_artifacts(project.run_dir, normalized_slide_id))
        # 勾画标注(可选模块)随图片失效:文字布局/时间轴删除、条目 stale。
        # 失败不阻塞既有失效流程;store 未配置(装配缺失)时静默跳过。
        try:
            from annotation_invalidation import invalidate_for_image_change

            removed.extend(invalidate_for_image_change(project, normalized_slide_id))
        except Exception as exc:  # noqa: BLE001 - 失效链路的兜底保护
            LOGGER.warning(
                "Annotation invalidation failed while clearing slide %s: %s",
                normalized_slide_id,
                exc,
            )
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
        removed.extend(_existing_removals(project.run_dir, clear_audio=False, clear_props=True))

    statuses = project.get_step_status()
    statuses["3"] = "completed" if all_images_exist else "in_progress"
    mark_selected_stale(statuses, (4, 5, 8))
    project.current_step = 3
    project.set_step_status(statuses)
    _record_content_impact(project, "slide_image_changed", normalized_ids)
    return InvalidationReport(
        reason="slide_image_changed",
        affected_steps=(4, 5, 8),
        slide_ids=normalized_ids,
        removed_paths=tuple(dict.fromkeys(removed)),
    )


def subtitle_style_changed(project: Any) -> InvalidationReport:
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    statuses = project.get_step_status()
    if statuses.get("8") == "completed":
        statuses["8"] = "pending_reconfirmation"
    project.set_step_status(statuses)
    _record_content_impact(project, "subtitle_style_changed")
    return InvalidationReport(
        reason="subtitle_style_changed",
        affected_steps=(8,),
        removed_paths=tuple(removed),
    )


def mask_content_changed(project: Any) -> InvalidationReport:
    """A changed reveal manifest only requires a new output composition."""
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    statuses = project.get_step_status()
    mark_selected_stale(statuses, (8,))
    project.set_step_status(statuses)
    _record_content_impact(project, "mask_content_changed")
    return InvalidationReport(
        reason="mask_content_changed",
        affected_steps=(8,),
        removed_paths=tuple(removed),
    )


def annotation_content_changed(project: Any, slide_ids: Iterable[str]) -> InvalidationReport:
    """Keep annotation inputs and existing exports; require a new MP4 composition."""
    normalized_ids = tuple(dict.fromkeys(str(value).strip() for value in slide_ids if str(value).strip()))
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    statuses = project.get_step_status()
    mark_selected_stale(statuses, (8,))
    project.set_step_status(statuses)
    _record_content_impact(project, "annotation_changed", normalized_ids)
    return InvalidationReport(
        reason="annotation_changed",
        affected_steps=(8,),
        slide_ids=normalized_ids,
        removed_paths=tuple(removed),
    )


def digital_human_changed(project: Any) -> InvalidationReport:
    """Changing the presenter only affects a newly composed output video."""
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    statuses = project.get_step_status()
    mark_selected_stale(statuses, (8,))
    project.set_step_status(statuses)
    _record_content_impact(project, "digital_human_changed")
    return InvalidationReport(
        reason="digital_human_changed",
        affected_steps=(8,),
        removed_paths=tuple(removed),
    )


def subtitle_visibility_changed(
    project: Any,
    slide_ids: Iterable[str],
) -> InvalidationReport:
    """Changing subtitle visibility affects composition, not source images."""
    normalized_ids = tuple(
        dict.fromkeys(str(value).strip() for value in slide_ids if str(value).strip())
    )
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    statuses = project.get_step_status()
    mark_selected_stale(statuses, (8,))
    project.set_step_status(statuses)
    _record_content_impact(project, "subtitle_visibility_changed")
    return InvalidationReport(
        reason="subtitle_visibility_changed",
        affected_steps=(8,),
        slide_ids=normalized_ids,
        removed_paths=tuple(dict.fromkeys(removed)),
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
    _record_content_impact(project, "video_background_changed")
    return InvalidationReport(
        reason="video_background_changed",
        affected_steps=(5, 8),
        slide_ids=normalized_ids,
        removed_paths=tuple(dict.fromkeys(removed)),
    )


def narration_synthesis_started(project: Any) -> InvalidationReport:
    statuses = project.get_step_status()
    if statuses.get("7") == "completed":
        return InvalidationReport(reason="stage_already_completed", affected_steps=())
    statuses["7"] = "in_progress"
    project.current_step = 7
    project.set_step_status(statuses)
    return InvalidationReport(
        reason="narration_synthesis_started",
        affected_steps=(),
    )


def audio_artifacts_changed(project: Any, slide_ids: Iterable[str]) -> InvalidationReport:
    normalized_ids = tuple(dict.fromkeys(str(value).strip() for value in slide_ids if str(value).strip()))
    if not normalized_ids:
        return InvalidationReport(reason="stage_already_completed", affected_steps=())
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    # 勾画页面写入必须与编辑器 patch/confirm 共用项目工件锁:
    # 后台 TTS 完成与用户 autosave 并发时,无锁的 read-modify-write
    # 会让后写者覆盖先写者(用户笔迹编辑丢失不可恢复)。
    with project_artifact_lock(project.run_dir):
        for slide_id in normalized_ids:
            try:
                from annotation_invalidation import invalidate_for_audio_change

                removed.extend(invalidate_for_audio_change(project, slide_id))
            except Exception as exc:  # noqa: BLE001 - keep audio generation usable
                LOGGER.warning("Annotation timing invalidation failed for %s: %s", slide_id, exc)
    statuses = project.get_step_status()
    mark_selected_stale(statuses, (7, 8))
    project.set_step_status(statuses)
    _record_content_impact(project, "audio_artifacts_changed", normalized_ids)
    try:
        from digital_human_impact import mark_presenter_audio_stale

        stale_presenter_ids = mark_presenter_audio_stale(project.run_dir, normalized_ids)
        if stale_presenter_ids:
            _record_content_impact(project, "digital_human_audio_changed", stale_presenter_ids)
    except Exception as exc:  # noqa: BLE001 - audio must remain usable
        LOGGER.warning("Digital-human audio linkage failed: %s", exc)
    return InvalidationReport(
        reason="audio_artifacts_changed",
        affected_steps=(7, 8),
        slide_ids=normalized_ids,
        removed_paths=tuple(removed),
    )


def narration_content_changed(project: Any) -> InvalidationReport:
    """An actual narration edit invalidates audio, never image or Mask work."""
    # Keep the confirmation record for recovery.  Its artifact hashes make
    # project_audio_confirmed false when the TTS input actually differs.
    removed = _existing_removals(project.run_dir, clear_audio=False, clear_props=True)
    statuses = project.get_step_status()
    mark_selected_stale(statuses, (7, 8))
    project.set_step_status(statuses)
    _record_content_impact(project, "narration_content_changed")
    return InvalidationReport(
        reason="narration_content_changed",
        affected_steps=(7, 8),
        removed_paths=tuple(removed),
    )
