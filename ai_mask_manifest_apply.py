"""Apply completed AI Mask ownership to reveal manifests and build review issues."""

from __future__ import annotations

from typing import Any

from ai_mask_component_detection import _merge_row_runs, _rle_bounds
from ai_mask_contracts import AI_MASK_MIN_FOREGROUND_COVERAGE, MASK_COLORS


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def _float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(str(value).strip())
    except Exception:
        parsed = default
    return max(lo, min(hi, parsed))


def _exact_manual_mask(elements: list[dict[str, Any]], width: int, height: int, color: str) -> dict[str, Any]:
    rle = _merge_row_runs(elements, width, height)
    bounds = _rle_bounds(rle)
    if bounds is None:
        raise RuntimeError("Exact AI Mask contains no foreground pixels")
    return {
        "source": "ai_auto_mask_v3_exact_rle",
        "color": color,
        "bounds": bounds,
        "rle": rle,
        "strokes": [],
    }


def _has_manual(group: dict[str, Any]) -> bool:
    manual = group.get("manual_mask") if isinstance(group.get("manual_mask"), dict) else {}
    runs = manual.get("rle", {}).get("runs") if isinstance(manual.get("rle"), dict) else []
    strokes = manual.get("strokes")
    return bool(runs) or (isinstance(strokes, list) and any(isinstance(s, dict) and s.get("points") for s in strokes))


def _replaceable_ai_mask(group: dict[str, Any]) -> bool:
    manual = group.get("manual_mask") if isinstance(group.get("manual_mask"), dict) else {}
    source = str(manual.get("source") or group.get("source") or "")
    strokes = manual.get("strokes") if isinstance(manual.get("strokes"), list) else []
    has_corrections = any(isinstance(stroke, dict) and stroke.get("points") for stroke in strokes)
    locked = str(group.get("review_status") or "").lower() in {"approved", "locked"}
    return source.startswith("ai_auto_mask") and not has_corrections and not locked


def _confidence_level(value: Any) -> str:
    confidence = _float(value, 0.0, 0.0, 1.0)
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.65:
        return "medium"
    return "low"


def _review_issues(match_payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for match in match_payload.get("matches", []) or []:
        if not isinstance(match, dict):
            continue
        confidence = _float(match.get("confidence"), 0.0, 0.0, 1.0)
        level = _confidence_level(confidence)
        if level == "high" and not match.get("below_threshold"):
            continue
        issues.append({
            "type": "low_confidence_match" if level == "low" else "review_match",
            "severity": "warning",
            "group_id": str(match.get("group_id") or ""),
            "confidence": round(confidence, 4),
            "confidence_level": level,
            "message": "AI 对该语块的元素归属不够确定，请检查。",
        })
    for group_id in match_payload.get("unmatched_groups", []) or []:
        issues.append({
            "type": "unmatched_group",
            "severity": "blocking",
            "group_id": str(group_id),
            "confidence": 0.0,
            "confidence_level": "low",
            "message": "该语块没有找到可靠的画面元素。",
        })
    quality = match_payload.get("quality") if isinstance(match_payload.get("quality"), dict) else {}
    if quality:
        coverage = _float(quality.get("foreground_coverage_ratio"), 0.0, 0.0, 1.0)
        minimum_coverage = _float(
            quality.get("minimum_foreground_coverage_ratio"),
            AI_MASK_MIN_FOREGROUND_COVERAGE,
            0.0,
            1.0,
        )
        if coverage < minimum_coverage:
            issues.append({
                "type": "foreground_coverage_below_threshold",
                "severity": "blocking",
                "group_id": "",
                "message": f"前景覆盖率为 {coverage:.2%}，低于要求的 {minimum_coverage:.2%}。",
                "metrics": {"coverage": round(coverage, 6), "minimum": round(minimum_coverage, 6)},
            })
        unassigned_count = _int(quality.get("unassigned_component_count"), 0, 0, 1_000_000)
        if unassigned_count:
            issues.append({
                "type": "unassigned_foreground_components",
                "severity": "blocking",
                "group_id": "",
                "message": f"仍有 {unassigned_count} 个前景组件未分配。",
                "metrics": {"unassigned_component_count": unassigned_count},
            })
        overlap_count = _int(quality.get("overlap_pixel_count"), 0, 0, 1_000_000_000)
        if overlap_count:
            issues.append({
                "type": "cross_group_pixel_overlap",
                "severity": "blocking",
                "group_id": "",
                "message": f"检测到 {overlap_count} 个跨语块重叠像素。",
                "metrics": {"overlap_pixel_count": overlap_count},
            })
    semantic_quality = match_payload.get("semantic_quality") if isinstance(match_payload.get("semantic_quality"), dict) else {}
    issue_messages = {
        "dynamic_group_enters_subtitle_safe_zone": "动态语块进入字幕安全区，请检查。",
        "dynamic_group_owns_title_region_pixels": "正文语块包含标题区域像素，请检查。",
        "group_crosses_left_and_right_regions": "该语块横跨页面左右区域，请确认它是否属于同一叙事单元。",
        "too_many_residual_components": "该语块包含较多自动吸附的小组件，请检查。",
        "many_residual_components": "该语块包含较多自动吸附的小组件，建议检查。",
        "forced_low_confidence_components": "部分画面组件通过最近锚点规则补全，建议检查归属。",
        "group_contains_multiple_independent_visual_islands": "一个分镜语块描述了多个应分别 Reveal 的独立视觉岛，请返回分镜规划拆分语块。",
        "insufficient_visual_groups_for_independent_objects": "画面存在多个独立语义对象，但分镜提供的可 Reveal 语块不足。",
    }
    for severity, field in (("blocking", "blocking_errors"), ("warning", "warnings")):
        for issue in semantic_quality.get(field, []) or []:
            if not isinstance(issue, dict):
                continue
            issue_type = str(issue.get("type") or "semantic_review")
            issues.append({
                **issue,
                "type": issue_type,
                "severity": severity,
                "group_id": str(issue.get("group_id") or ""),
                "message": issue_messages.get(issue_type, "AI Mask 语义质量需要检查。"),
            })
    return issues


def _find_group(groups: list[dict[str, Any]], gid: str) -> dict[str, Any] | None:
    for group in groups:
        if not isinstance(group, dict):
            continue
        identifiers = {
            str(group.get("id") or ""),
            str(group.get("group_id") or ""),
            str(group.get("visual_group_id") or ""),
        }
        if gid in identifiers:
            return group
    return None


def _migrate_legacy_default_reveal(group: dict[str, Any]) -> None:
    """Replace only the old default wipe, preserving deliberate custom animation."""
    reveal = group.get("reveal") if isinstance(group.get("reveal"), dict) else {}
    if not reveal:
        # Semantic groups created by AI Mask do not necessarily originate from
        # the coordinate template.  Give those groups the current production
        # default explicitly; otherwise the scene builder falls back to its
        # historical 0.75 s duration and the picture is still animating after
        # the narration has begun.
        group["reveal"] = {
            "type": "crop_fade_up",
            "duration": 0.25,
            "auto_default": True,
        }
        return
    reveal_type = str(reveal.get("type") or "")
    try:
        duration = float(reveal.get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if reveal_type == "wipe_left_to_right" and abs(duration - 0.75) <= 0.001:
        group["reveal"] = {"type": "crop_fade_up", "duration": 0.25, "auto_migrated": True}


def _apply(manifest: dict[str, Any], slide: dict[str, Any], elements_payload: dict[str, Any], match_payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, int]:
    slide_id = str(slide.get("slide_id") or "")
    mslide = next((s for s in manifest.get("slides", []) if isinstance(s, dict) and str(s.get("slide_id") or "") == slide_id), None)
    if not mslide:
        raise RuntimeError(f"Missing reveal manifest slide: {slide_id}")
    groups = mslide.setdefault("groups", [])
    semantic = mslide.setdefault("semantic_blocks", [])
    canvas = elements_payload.get("canvas", {})
    width, height = int(canvas.get("width", 1920)), int(canvas.get("height", 1080))
    by_element = {
        e["element_id"]: e
        for e in (elements_payload.get("elements", []) or []) + (elements_payload.get("residual_elements", []) or [])
        if isinstance(e, dict) and e.get("element_id")
    }
    updated = skipped = 0
    static_element_ids = [
        str(value) for value in match_payload.get("static_element_ids", []) or []
        if str(value) in by_element
    ]
    static_group_ids = {
        str(value) for value in match_payload.get("static_group_ids", []) or [] if str(value)
    }
    # Remove legacy static title paint. Narrated title/subtitle groups are
    # rebuilt below with the same exact RLE masks as body groups.
    for collection in (groups, semantic):
        collection[:] = [
            group for group in collection
            if not (
                isinstance(group, dict)
                and (
                    str(group.get("id") or group.get("group_id") or group.get("visual_group_id") or "") in static_group_ids
                    or bool(group.get("is_static_header"))
                )
            )
        ]
    if static_element_ids:
        static_mask = _exact_manual_mask(
            [by_element[element_id] for element_id in static_element_ids],
            width,
            height,
            "#000000",
        )
        groups.append({
            "id": "__static_title_header__",
            "group_id": "__static_title_header__",
            "role": "background",
            "visible_text": "固定标题区",
            "box": dict(static_mask["bounds"]),
            "manual_mask": static_mask,
            "is_static": True,
            "is_static_header": True,
            "link_to_narration": False,
            "review_status": "ai_static",
            "source": "ai_static_header",
            "z_index": 5,
        })
    visual_group_order = {
        str(group.get("id") or ""): index
        for index, group in enumerate(slide.get("visual_groups", []) or [])
        if isinstance(group, dict)
    }
    matches = [match for match in match_payload.get("matches", []) or [] if isinstance(match, dict)]
    valid_match_group_ids = {
        str(match.get("group_id") or "")
        for match in matches
        if not match.get("below_threshold")
        and any(str(element_id) in by_element for element_id in match.get("element_ids", []) or [])
    }
    for match in matches:
        gid = str(match.get("group_id") or "")
        if match.get("below_threshold"):
            # Vision and the deterministic fallback can both report the same
            # group.  A low-confidence/empty vision candidate is not a real
            # omission when a later fallback candidate successfully owns the
            # group, and static title groups are intentionally not dynamic.
            if gid not in valid_match_group_ids and gid not in static_group_ids:
                skipped += 1
            continue
        matched_elements = [by_element[eid] for eid in match.get("element_ids", []) if eid in by_element]
        if not matched_elements:
            if gid not in valid_match_group_ids and gid not in static_group_ids:
                skipped += 1
            continue
        exact_mask = _exact_manual_mask(matched_elements, width, height, MASK_COLORS[visual_group_order.get(gid, 0) % len(MASK_COLORS)])
        box = dict(exact_mask["bounds"])
        semantic_group = _find_group(semantic, gid)
        display_group_id = str((semantic_group or {}).get("group_id") or (semantic_group or {}).get("id") or gid)
        color = MASK_COLORS[visual_group_order.get(gid, 0) % len(MASK_COLORS)]
        for collection in (groups, semantic):
            group = _find_group(collection, gid)
            if group is None:
                group = {
                    "id": display_group_id,
                    "group_id": display_group_id,
                    "visual_group_id": gid,
                    "role": "body_content",
                    "visible_text": gid,
                    "padding_px": 32,
                    "z_index": 40 + len(collection),
                }
                collection.append(group)
            _migrate_legacy_default_reveal(group)
            if str(group.get("review_status") or "").lower() in {"approved", "locked"}:
                continue
            # Human corrections are always authoritative. Only a pristine Mask
            # produced by a previous AI run may be replaced automatically.
            if _has_manual(group) and not _replaceable_ai_mask(group):
                continue
            if _has_manual(group) and not settings.get("overwrite_existing_ai_mask", True):
                continue
            group["box"] = box
            group["visual_group_id"] = gid
            group["manual_mask"] = {
                **exact_mask,
                "color": color,
            }
            confidence_level = _confidence_level(match.get("confidence"))
            group["review_status"] = "ai_matched" if confidence_level == "high" else "ai_review_required"
            group["source"] = "ai_auto_mask"
            if match.get("narration_beat_id"):
                group["narration_beat_id"] = match["narration_beat_id"]
            group["auto_mask"] = {
                "version": "auto_mask_v3_exact_rle",
                "method": "multimodal_exact_connected_components_v3",
                "element_ids": match.get("element_ids", []),
                "bbox": box,
                "compatible_manual_corrections": True,
                "exclusive_pixel_ownership": True,
            }
            group["ai_match"] = {
                "confidence": match.get("confidence"),
                "confidence_level": confidence_level,
                "needs_review": confidence_level != "high",
                "reason": match.get("reason", ""),
            }
        updated += 1
    mslide["ai_mask_status"] = {
        "version": "ai_mask_annotation_v3_exact_rle",
        "updated_group_count": updated,
        "skipped_group_count": skipped,
        "detected_element_count": len(elements_payload.get("elements", [])),
        "residual_component_count": len(elements_payload.get("residual_elements", [])),
        "quality": match_payload.get("quality", {}),
        "review_issues": _review_issues(match_payload),
    }
    return {"updated": updated, "skipped": skipped}


