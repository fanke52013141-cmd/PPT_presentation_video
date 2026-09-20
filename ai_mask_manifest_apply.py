"""Apply completed AI Mask ownership to reveal manifests and build review issues."""

from __future__ import annotations

from typing import Any

from ai_mask_component_detection import _merge_row_runs, _rle_bounds
from ai_mask_contracts import (
    AI_MASK_MIN_FOREGROUND_COVERAGE,
    ASSIGNMENT_SOURCE_MANUAL,
    ASSIGNMENT_SOURCE_RULE,
    MASK_COLORS,
)


def _mark_manual_owned(group: dict[str, Any]) -> None:
    """Record that saved human work owns this region, leaving the pixels alone.

    A re-run must never silently look like it re-confirmed a Mask the user drew;
    the provenance now says ``manual`` so the editor can show who decided.
    """
    ai_match = group.get("ai_match") if isinstance(group.get("ai_match"), dict) else {}
    group["ai_match"] = {
        **ai_match,
        "assignment_source": ASSIGNMENT_SOURCE_MANUAL,
        "ownership_preserved": True,
    }


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
            "assignment_source": str(match.get("assignment_source") or ""),
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
    # A request budget that ran out is not a silent omission: the objects the
    # model never saw must be reviewed by a person, and a partially failed batch
    # means the remaining ownership came from rules.
    batches = match_payload.get("vision_batches") if isinstance(match_payload.get("vision_batches"), dict) else {}
    beyond_budget = [str(value) for value in batches.get("beyond_budget_object_ids", []) or [] if str(value)]
    if beyond_budget:
        issues.append({
            "type": "object_beyond_review_budget",
            "severity": "warning",
            "group_id": "",
            "message": f"有 {len(beyond_budget)} 个画面对象超出本页的多模态请求预算，未经模型确认，请检查其归属。",
            "metrics": {"object_ids": beyond_budget[:40], "object_count": len(beyond_budget)},
        })
    failed_batches = [value for value in batches.get("failed_batch_indices", []) or []]
    if failed_batches:
        issues.append({
            "type": "vision_batch_failed",
            "severity": "warning",
            "group_id": "",
            "message": "部分对象批次请求失败，本页归属可能由规则补全，请检查。",
            "metrics": {
                "failed_batch_indices": failed_batches,
                "failed_batch_error_type": str(batches.get("failed_batch_error_type") or ""),
            },
        })
    issue_messages = {
        "dynamic_group_enters_subtitle_safe_zone": "动态语块进入字幕安全区，请检查。",
        "dynamic_group_owns_title_region_pixels": "正文语块包含标题区域像素，请检查。",
        "group_crosses_left_and_right_regions": "该语块横跨页面左右区域，请确认它是否属于同一叙事单元。",
        "too_many_residual_components": "该语块包含较多自动吸附的小组件，请检查。",
        "many_residual_components": "该语块包含较多自动吸附的小组件，建议检查。",
        "forced_low_confidence_components": "部分画面组件通过最近锚点规则补全，建议检查归属。",
        "unconfirmed_semantic_ownership": "该语块的组件全部由规则或覆盖补全归入，模型未确认其语义归属，请检查。",
        "forced_large_component_completed": "有较大的画面组件被最近锚点规则强制归入该语块，请确认归属。",
        "object_beyond_review_budget": "有画面对象超出模型请求预算，未经语义匹配，请检查归属。",
        "vision_batch_failed": "部分对象批次请求失败，归属可能不完整，请检查。",
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
    provenance = (
        match_payload.get("assignment_provenance")
        if isinstance(match_payload.get("assignment_provenance"), dict) else {}
    )
    provenance_by_group = {
        str(record.get("group_id") or ""): record
        for record in provenance.get("groups", []) or []
        if isinstance(record, dict)
    }
    # The evidence is always recorded, but routing a group to human review only
    # makes sense where the model actually participated.  On a deterministic-
    # prior page (no vision model answered) every group is rule-owned, so
    # per-group review would flood the queue with the page-wide degradation the
    # caller already knows about from vision_status.
    unconfirmed_group_ids = {
        str(value) for value in provenance.get("unconfirmed_group_ids", []) or [] if str(value)
    } if provenance.get("model_participated") else set()
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
        origins = match.get("element_origins") if isinstance(match.get("element_origins"), dict) else {}
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
                _mark_manual_owned(group)
                continue
            if _has_manual(group) and not settings.get("overwrite_existing_ai_mask", True):
                _mark_manual_owned(group)
                continue
            group["box"] = box
            group["visual_group_id"] = gid
            group["manual_mask"] = {
                **exact_mask,
                "color": color,
            }
            confidence_level = _confidence_level(match.get("confidence"))
            match_source = str(match.get("assignment_source") or "")
            record = provenance_by_group.get(gid, {})
            # A high number alone is not confirmation: a body group that only
            # rules and coverage completion placed here still needs a person.
            needs_review = confidence_level != "high" or (
                bool(settings.get("provenance_review_routing", True))
                and gid in unconfirmed_group_ids
            )
            group["review_status"] = "ai_review_required" if needs_review else "ai_matched"
            group["source"] = "ai_auto_mask"
            if match.get("narration_beat_id"):
                group["narration_beat_id"] = match["narration_beat_id"]
            group["auto_mask"] = {
                "version": "auto_mask_v3_exact_rle",
                "method": "multimodal_exact_connected_components_v3",
                "element_ids": match.get("element_ids", []),
                "element_origins": {
                    str(element_id): str(origins.get(str(element_id)) or match_source or ASSIGNMENT_SOURCE_RULE)
                    for element_id in match.get("element_ids", []) or []
                },
                "assignment_source": match_source,
                "bbox": box,
                "compatible_manual_corrections": True,
                "exclusive_pixel_ownership": True,
            }
            group["ai_match"] = {
                "confidence": match.get("confidence"),
                "confidence_level": confidence_level,
                "needs_review": needs_review,
                "assignment_source": match_source,
                "model_ownership_ratio": float(record.get("model_ownership_ratio", 0.0)),
                "reason": match.get("reason", ""),
            }
        updated += 1
    mslide["ai_mask_status"] = {
        "version": "ai_mask_annotation_v4_provenance",
        "updated_group_count": updated,
        "skipped_group_count": skipped,
        "detected_element_count": len(elements_payload.get("elements", [])),
        "residual_component_count": len(elements_payload.get("residual_elements", [])),
        "quality": match_payload.get("quality", {}),
        "assignment_provenance": provenance,
        "review_issues": _review_issues(match_payload),
    }
    return {"updated": updated, "skipped": skipped}


