"""Source-owned reconciliation between storyboard and Reveal Manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from pipeline_lifecycle import project_artifact_lock, write_json_atomic
from project_storage import slide_dir
from visual_provenance import refresh_provenance_contract_hashes


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _group_id(group: dict[str, Any]) -> str:
    return str(
        group.get("id") or group.get("group_id") or group.get("visual_group_id") or ""
    ).strip()


def _is_manual_group(group: dict[str, Any]) -> bool:
    return _group_id(group).startswith("manual_group_")


def _is_painted_group(group: dict[str, Any]) -> bool:
    strokes = (
        group.get("strokes")
        or group.get("paint_strokes")
        or group.get("manual_mask_strokes")
    )
    if isinstance(strokes, list) and strokes:
        return True
    manual_mask = group.get("manual_mask")
    if isinstance(manual_mask, dict):
        mask_strokes = manual_mask.get("strokes") or manual_mask.get("paint_strokes")
        if isinstance(mask_strokes, list) and mask_strokes:
            return True
        # AI Mask writes exact pixel masks as RLE under manual_mask.rle
        # (source: ai_auto_mask_v3_exact_rle) without brush strokes.
        rle = manual_mask.get("rle")
        if isinstance(rle, dict) and isinstance(rle.get("runs"), list) and rle.get("runs"):
            return True
    return any(key in group for key in ("mask", "mask_path", "mask_url", "mask_data"))


def _contract_group_id(group: dict[str, Any], slide_id: str, index: int) -> str:
    return _group_id(group) or f"{slide_id}_group_{index:03d}"


def _default_box(index: int) -> dict[str, int]:
    row = max(0, index - 1)
    return {"x": 160, "y": min(760, 140 + row * 110), "w": 1600, "h": 92}


def _normalized_box(value: Any, fallback_index: int) -> dict[str, float | int]:
    if isinstance(value, dict):
        try:
            return {
                "x": float(value.get("x", 0)),
                "y": float(value.get("y", 0)),
                "w": float(value.get("w", 0)),
                "h": float(value.get("h", 0)),
            }
        except (TypeError, ValueError):
            return _default_box(fallback_index)
    if isinstance(value, list) and len(value) == 4:
        try:
            x1, y1, x2, y2 = [float(item) for item in value]
            return {
                "x": x1,
                "y": y1,
                "w": max(1.0, x2 - x1),
                "h": max(1.0, y2 - y1),
            }
        except (TypeError, ValueError):
            return _default_box(fallback_index)
    return _default_box(fallback_index)


def _narration_beat_id_for_group(
    contract_slide: dict[str, Any],
    group: dict[str, Any],
) -> str:
    existing = str(group.get("narration_beat_id") or group.get("beat_id") or "").strip()
    if existing:
        return existing
    group_id = _group_id(group)
    content_unit_id = str(group.get("content_unit_id") or "").strip()
    for beat in contract_slide.get("narration_beats", []) or []:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id") or "").strip()
        if not beat_id:
            continue
        if group_id and str(beat.get("group_id") or "").strip() == group_id:
            return beat_id
        if content_unit_id and str(beat.get("content_unit_id") or "").strip() == content_unit_id:
            return beat_id
    return ""


def _merge_contract_group(
    slide_id: str,
    contract_slide: dict[str, Any],
    contract_group: dict[str, Any],
    old_group: dict[str, Any] | None,
    index: int,
) -> dict[str, Any]:
    group_id = _contract_group_id(contract_group, slide_id, index)
    merged: dict[str, Any] = dict(old_group or {})
    merged["id"] = group_id
    merged["visual_group_id"] = group_id
    for field in (
        "role",
        "content_unit_id",
        "visible_text",
        "visual_anchor",
        "mask_target",
        "reveal_order",
    ):
        value = contract_group.get(field)
        if value not in (None, ""):
            merged[field] = value

    beat_id = _narration_beat_id_for_group(contract_slide, contract_group)
    if beat_id:
        merged["narration_beat_id"] = beat_id
    if "box" in contract_group:
        merged["box"] = _normalized_box(contract_group.get("box"), index)
    elif "bbox" in contract_group:
        merged["box"] = _normalized_box(contract_group.get("bbox"), index)
    else:
        merged.setdefault("box", _default_box(index))
    merged.setdefault("padding", {"x": 12, "y": 12})
    merged.setdefault("z_index", index)
    merged.setdefault("review_status", "pending")
    merged.setdefault("reveal", {"action": "brush_reveal", "duration_sec": 0.75})
    return merged


def _dedupe_groups(groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = _group_id(group)
        if not group_id or group_id in seen:
            continue
        seen.add(group_id)
        result.append(group)
    return result


def _reconciled_slide(
    run_dir: Path,
    contract_slide: dict[str, Any],
    old_slide: dict[str, Any] | None,
    slide_index: int,
) -> dict[str, Any]:
    slide_id = str(contract_slide.get("slide_id") or f"slide_{slide_index:03d}").strip()
    slide: dict[str, Any] = dict(old_slide or {})
    slide["slide_id"] = slide_id
    slide["slide_dir"] = slide_dir(run_dir, slide_id).as_posix()
    slide["master"] = "visual_draft.png"
    slide.setdefault("image", f"slides/{slide_id}/visual_draft.png")
    slide.setdefault("status", "pending")
    slide.setdefault("canvas", {"w": 1920, "h": 1080, "background": "#FEFDF9"})

    old_candidates: list[dict[str, Any]] = []
    if old_slide:
        for field in ("semantic_blocks", "groups"):
            values = old_slide.get(field)
            if isinstance(values, list):
                old_candidates.extend(group for group in values if isinstance(group, dict))
    old_by_id = {_group_id(group): group for group in old_candidates if _group_id(group)}
    contract_groups = [
        group
        for group in contract_slide.get("visual_groups", []) or []
        if isinstance(group, dict)
    ]
    contract_ids = {
        _contract_group_id(group, slide_id, index)
        for index, group in enumerate(contract_groups, start=1)
    }
    semantic_blocks = [
        _merge_contract_group(
            slide_id,
            contract_slide,
            group,
            old_by_id.get(_contract_group_id(group, slide_id, index)),
            index,
        )
        for index, group in enumerate(contract_groups, start=1)
    ]
    semantic_blocks = _dedupe_groups(
        semantic_blocks
        + [dict(group) for group in old_candidates if _is_manual_group(group)]
    )

    build_groups: list[dict[str, Any]] = []
    for block in semantic_blocks:
        group_id = _group_id(block)
        old_group = old_by_id.get(group_id)
        if old_group and (_is_painted_group(old_group) or _is_manual_group(old_group)):
            merged = dict(block)
            merged.update(old_group)
            merged["id"] = group_id
            build_groups.append(merged)
        elif group_id in contract_ids:
            build_groups.append(dict(block))
    slide["semantic_blocks"] = semantic_blocks
    slide["groups"] = _dedupe_groups(build_groups)
    return slide


def _ensure_contract_topic_fields(
    contract: dict[str, Any],
    project: Any,
    run_dir: Path,
) -> bool:
    before = _stable_json(contract.get("topic"))
    topic = dict(contract.get("topic") if isinstance(contract.get("topic"), dict) else {})
    article_brief: dict[str, Any] = {}
    brief_path = run_dir / "planning" / "article_brief.json"
    try:
        loaded = json.loads(brief_path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            article_brief = loaded
    except (OSError, json.JSONDecodeError):
        pass

    project_id = _first_non_empty(getattr(project, "id", ""), "project")
    project_name = _first_non_empty(
        getattr(project, "name", ""),
        article_brief.get("title"),
        "未命名项目",
    )
    topic["topic_id"] = _first_non_empty(topic.get("topic_id"), f"topic_{project_id}")
    topic["topic_name"] = _first_non_empty(topic.get("topic_name"), project_name)
    topic["topic_summary"] = _first_non_empty(
        topic.get("topic_summary"),
        article_brief.get("summary"),
        getattr(project, "description", ""),
        project_name,
    )
    contract["topic"] = topic
    return _stable_json(contract.get("topic")) != before


def sync_reveal_manifest(
    project: Any,
    slide_ids: Iterable[str],
    *,
    allow_empty: bool = False,
) -> bool:
    """Reconcile slides/groups while preserving painted and manual Mask data."""
    current_slide_ids = tuple(
        dict.fromkeys(str(slide_id).strip() for slide_id in slide_ids if str(slide_id).strip())
    )
    if not current_slide_ids and not allow_empty:
        return False

    run_dir = Path(project.run_dir).resolve()
    contract_path = run_dir / "planning" / "visual_contract.json"
    manifest_path = run_dir / "reveal_manifest.json"
    if not contract_path.exists():
        return False

    with project_artifact_lock(run_dir):
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(contract, dict):
            return False

        contract_changed = _ensure_contract_topic_fields(contract, project, run_dir)
        if contract_changed:
            write_json_atomic(contract_path, contract)
            refresh_provenance_contract_hashes(run_dir, current_slide_ids)

        if not manifest_path.exists():
            return contract_changed
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return contract_changed
        if not isinstance(manifest, dict):
            return contract_changed

        before = _stable_json(manifest)
        contract_slides_by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in contract.get("slides", []) or []
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }
        old_slides_by_id = {
            str(slide.get("slide_id") or "").strip(): slide
            for slide in manifest.get("slides", []) or []
            if isinstance(slide, dict) and str(slide.get("slide_id") or "").strip()
        }
        missing_slide_ids = [
            slide_id for slide_id in current_slide_ids if slide_id not in old_slides_by_id
        ]
        manifest.setdefault("version", "reveal_v1")
        manifest["slides"] = [
            _reconciled_slide(
                run_dir,
                contract_slides_by_id[slide_id],
                old_slides_by_id.get(slide_id),
                index,
            )
            for index, slide_id in enumerate(current_slide_ids, start=1)
            if slide_id in contract_slides_by_id
        ]
        if missing_slide_ids:
            manifest.pop("ai_mask_annotation", None)
        if _stable_json(manifest) == before:
            return contract_changed
        write_json_atomic(manifest_path, manifest)
        return True
