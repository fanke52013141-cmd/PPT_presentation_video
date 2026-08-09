"""Artifact revalidation policy for resumable one-click generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from tts_artifacts import confirmation_status


STAGE_IDS = (
    "preflight",
    "storyboard",
    "images",
    "confirm_images",
    "ai_mask",
    "mask_assets",
    "narration",
    "tts",
    "render",
)


def run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def has_article(project: Any) -> bool:
    try:
        return bool((run_dir(project) / "inputs" / "article.md").read_text(encoding="utf-8-sig").strip())
    except OSError:
        return False


def has_contract(project: Any) -> bool:
    root = run_dir(project)
    contract_path = root / "planning" / "visual_contract.json"
    if not contract_path.is_file() or mtime(root / "inputs" / "article.md") > mtime(contract_path):
        return False
    validation = read_json(root / "planning" / "visual_contract.validation.json", {})
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        return False
    try:
        actual_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    except OSError:
        return False
    return bool(validation.get("contract_sha256")) and validation.get("contract_sha256") == actual_hash


def slide_ids(project: Any) -> list[str]:
    contract = read_json(run_dir(project) / "planning" / "visual_contract.json", {})
    slides = contract.get("slides") if isinstance(contract, dict) else []
    return [
        str(slide.get("slide_id") or "").strip()
        for slide in slides or []
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    ]


def upstream_image_inputs(project: Any, slide_id: str) -> list[Path]:
    root = run_dir(project)
    paths = [
        root / "planning" / "visual_contract.json",
        root / "planning" / "step3_image_style.json",
        root / "planning" / "project_style_references.json",
        root / "slides" / slide_id / "visual_prompt.md",
    ]
    references_dir = root / "planning" / "style_references"
    if references_dir.exists():
        paths.extend(sorted(references_dir.glob("style_reference_*.png"))[:3])
    return paths


def image_needs_generation(project: Any, slide_id: str) -> bool:
    image_path = run_dir(project) / "slides" / slide_id / "visual_draft.png"
    if not image_path.is_file():
        return True
    image_mtime = mtime(image_path)
    return any(mtime(path) > image_mtime for path in upstream_image_inputs(project, slide_id))


def slides_requiring_images(project: Any) -> list[str]:
    return [slide_id for slide_id in slide_ids(project) if image_needs_generation(project, slide_id)]


def has_fresh_narration(project: Any) -> bool:
    root = run_dir(project)
    narration_path = root / "planning" / "narration_beats.json"
    payload = read_json(narration_path, {})
    slides = payload.get("slides") if isinstance(payload, dict) else None
    if not isinstance(slides, list) or mtime(narration_path) < mtime(root / "planning" / "visual_contract.json"):
        return False
    actual_ids = [
        str(slide.get("slide_id") or "").strip()
        for slide in slides
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    ]
    return bool(actual_ids) and actual_ids == slide_ids(project)


def _validate_preflight(project: Any) -> list[str]:
    return [] if has_article(project) else ["article_missing"]


def _validate_storyboard(project: Any) -> list[str]:
    return [] if has_contract(project) else ["visual_contract_stale_or_invalid"]


def _validate_images(project: Any) -> list[str]:
    ids = slide_ids(project)
    if not ids:
        return ["contract_has_no_slides"]
    stale = slides_requiring_images(project)
    return [] if not stale else [f"images_stale:{','.join(stale)}"]


def _validate_confirm_images(project: Any) -> list[str]:
    manifest = read_json(run_dir(project) / "reveal_manifest.json", {})
    slides = manifest.get("slides") if isinstance(manifest, dict) else None
    actual = [
        str(slide.get("slide_id") or "").strip()
        for slide in slides or []
        if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
    ]
    return [] if actual == slide_ids(project) and actual else ["reveal_manifest_slide_set_mismatch"]


def _validate_ai_mask(project: Any) -> list[str]:
    manifest = read_json(run_dir(project) / "reveal_manifest.json", {})
    annotation = manifest.get("ai_mask_annotation") if isinstance(manifest, dict) else None
    status = str(annotation.get("status") or "") if isinstance(annotation, dict) else ""
    return [] if status in {"completed", "completed_needs_review"} else ["ai_mask_incomplete"]


def _validate_mask_assets(project: Any) -> list[str]:
    root = run_dir(project)
    source_mtime = max([
        mtime(root / "reveal_manifest.json"),
        *(mtime(root / "slides" / slide_id / "visual_draft.png") for slide_id in slide_ids(project)),
    ])
    missing_or_stale: list[str] = []
    for slide_id in slide_ids(project):
        slide_root = root / "slides" / slide_id
        outputs = [slide_root / "scene.json", slide_root / "animation_timeline.json", slide_root / "reveal_report.json"]
        if any(not path.is_file() or mtime(path) < source_mtime for path in outputs):
            missing_or_stale.append(slide_id)
    return [] if not missing_or_stale else [f"mask_assets_stale:{','.join(missing_or_stale)}"]


def _validate_narration(project: Any) -> list[str]:
    return [] if has_fresh_narration(project) else ["narration_stale_or_invalid"]


def _validate_tts(project: Any) -> list[str]:
    status = confirmation_status(run_dir(project), slide_ids(project))
    return [] if status.get("confirmed") else [f"audio_not_confirmed:{status.get('reason') or 'unknown'}"]


VALIDATORS: dict[str, Callable[[Any], list[str]]] = {
    "preflight": _validate_preflight,
    "storyboard": _validate_storyboard,
    "images": _validate_images,
    "confirm_images": _validate_confirm_images,
    "ai_mask": _validate_ai_mask,
    "mask_assets": _validate_mask_assets,
    "narration": _validate_narration,
    "tts": _validate_tts,
}

STAGE_INTERNAL_STEP = {
    "preflight": 1,
    "storyboard": 2,
    "images": 3,
    "confirm_images": 4,
    "ai_mask": 5,
    "mask_assets": 5,
    "narration": 6,
    "tts": 7,
    "render": 8,
}


def _project_state_reasons(project: Any, stage_id: str) -> list[str]:
    get_status = getattr(project, "get_step_status", None)
    if not callable(get_status):
        return []
    statuses = get_status()
    if not isinstance(statuses, dict):
        return []
    value = statuses.get(str(STAGE_INTERNAL_STEP[stage_id]))
    if value in {"pending", "in_progress", "pending_reconfirmation"}:
        return [f"project_step_state:{value}"]
    return []


def build_resume_plan(project: Any, failed_stage: str) -> dict[str, Any]:
    failed_stage = failed_stage if failed_stage in STAGE_IDS else "preflight"
    failed_index = STAGE_IDS.index(failed_stage)
    validation: list[dict[str, Any]] = []
    effective_stage = failed_stage
    for stage_id in STAGE_IDS[: failed_index + 1]:
        reasons = (
            ["previous_stage_failed"]
            if stage_id == failed_stage
            else [*VALIDATORS[stage_id](project), *_project_state_reasons(project, stage_id)]
        )
        valid = not reasons
        validation.append({"stage": stage_id, "valid": valid, "reasons": reasons})
        if not valid and STAGE_IDS.index(stage_id) < STAGE_IDS.index(effective_stage):
            effective_stage = stage_id
    return {
        "previous_failed_stage": failed_stage,
        "effective_start_stage": effective_stage,
        "revalidation": validation,
    }
