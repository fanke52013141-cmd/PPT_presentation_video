"""Semantic ownership cleanup and deterministic component completion for AI Mask."""

from __future__ import annotations

from typing import Any

import numpy as np

from ai_mask_component_detection import _merge_row_runs, _rle_pixel_count
from ai_mask_contracts import (
    AI_MASK_MIN_FOREGROUND_COVERAGE,
    ASSIGNMENT_SOURCE_COMPLETION,
    ASSIGNMENT_SOURCE_MODEL,
    ASSIGNMENT_SOURCE_RULE,
    ASSIGNMENT_SOURCES,
)
from scripts.visual_group_semantics import visual_group_atomicity_issues


# A group whose ownership the model never confirmed is only a risk when the
# narration contract expected a model decision there.  Title and subtitle bands
# are owned by geometry on purpose, so they stay out of the review queue.
_MODEL_DECIDED_ROLES_EXCLUDED = frozenset({"title", "subtitle"})
# One forced component this large inside a group is a decision a human should
# see, because coverage was closed with a real content island, not an
# antialiasing fragment.
LARGE_FORCED_COMPONENT_AREA_RATIO = 0.2


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


def _box_xyxy(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, dict):
        try:
            x1 = float(value.get("x", 0))
            y1 = float(value.get("y", 0))
            return x1, y1, x1 + float(value.get("w", 0)), y1 + float(value.get("h", 0))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return tuple(float(item) for item in value[:4])  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def _manifest_group_for_visual_id(manifest_slide: dict[str, Any], group_id: str) -> dict[str, Any] | None:
    for field in ("semantic_blocks", "groups"):
        for group in manifest_slide.get(field, []) or []:
            if not isinstance(group, dict):
                continue
            identifiers = {
                str(group.get("id") or ""),
                str(group.get("group_id") or ""),
                str(group.get("visual_group_id") or ""),
            }
            if group_id in identifiers:
                return group
    return None


def _declared_origin(item: dict[str, Any]) -> str:
    declared = str(item.get("assignment_source") or "")
    if declared not in ASSIGNMENT_SOURCES:
        # An unstamped payload is never assumed to be a model decision: the
        # provenance layer defaults to the weakest claim.
        return ASSIGNMENT_SOURCE_RULE
    return declared


def _element_origins(item: dict[str, Any], element_ids: list[str], default: str) -> dict[str, str]:
    """Read one match's per-component provenance, defaulting to the weakest claim."""
    declared = _declared_origin(item) if item.get("assignment_source") else default
    stored = item.get("element_origins") if isinstance(item.get("element_origins"), dict) else {}
    origins: dict[str, str] = {}
    for element_id in element_ids:
        value = str(stored.get(element_id) or declared)
        origins[element_id] = value if value in ASSIGNMENT_SOURCES else declared
    return origins


def _fallback_match(
    slide: dict[str, Any],
    elements: list[dict[str, Any]],
    manifest_slide: dict[str, Any] | None = None,
) -> dict[str, Any]:
    narrated_group_ids = {
        str(beat.get("group_id") or "")
        for beat in slide.get("narration_beats", []) or []
        if isinstance(beat, dict) and str(beat.get("group_id") or "")
    }
    groups = [
        group for group in slide.get("visual_groups", []) or []
        if isinstance(group, dict)
        and str(group.get("role") or "") != "decoration"
        and str(group.get("id") or "") in narrated_group_ids
    ]
    beat_by_group = {
        str(beat.get("group_id") or ""): str(beat.get("id") or "")
        for beat in slide.get("narration_beats", []) or []
        if isinstance(beat, dict)
    }
    matches: list[dict[str, Any]] = []
    used: set[str] = set()
    unmatched_groups: list[str] = []
    for index, group in enumerate(groups):
        gid = str(group.get("id") or "")
        prior = _manifest_group_for_visual_id(manifest_slide or {}, gid)
        prior_box = _box_xyxy((prior or {}).get("box"))
        selected: list[str] = []
        if prior_box:
            px1, py1, px2, py2 = prior_box
            for element in elements:
                eid = str(element.get("element_id") or "")
                if not eid or eid in used:
                    continue
                box = _box_xyxy(element.get("bbox"))
                if not box:
                    continue
                ex1, ey1, ex2, ey2 = box
                cx, cy = (ex1 + ex2) / 2, (ey1 + ey2) / 2
                intersects = min(px2, ex2) > max(px1, ex1) and min(py2, ey2) > max(py1, ey1)
                if (px1 <= cx <= px2 and py1 <= cy <= py2) or intersects:
                    selected.append(eid)
        if not selected:
            unmatched_groups.append(gid)
            continue
        used.update(selected)
        matches.append({
            "group_id": gid,
            "narration_beat_id": beat_by_group.get(gid, ""),
            "element_ids": selected,
            "assignment_source": ASSIGNMENT_SOURCE_RULE,
            "confidence": 0.86 if prior_box else 0.74,
            "reason": "deterministic prior-box match" if prior_box else "deterministic reading-order match",
        })
    all_ids = {str(element.get("element_id") or "") for element in elements if str(element.get("element_id") or "")}
    return {
        "slide_id": slide.get("slide_id"),
        "matches": matches,
        "unmatched_elements": sorted(all_ids - used),
        "unmatched_groups": unmatched_groups,
        "warnings": [],
        "matching_method": "deterministic_prior",
    }


def _merge_match_results(primary: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(primary, dict):
        return fallback
    result = dict(primary)
    matches: list[dict[str, Any]] = []
    for item in result.get("matches", []) or []:
        if not isinstance(item, dict):
            continue
        # The multimodal answer is the only source that may claim semantic
        # confirmation, so it is stamped before anything else sees this payload.
        stamped = dict(item)
        stamped.setdefault("assignment_source", ASSIGNMENT_SOURCE_MODEL)
        matches.append(stamped)
    primary_groups = {str(item.get("group_id") or "") for item in matches}
    used_elements = {str(eid) for item in matches for eid in (item.get("element_ids") or [])}
    for item in fallback.get("matches", []) or []:
        gid = str(item.get("group_id") or "")
        if gid in primary_groups:
            continue
        candidate_ids = [str(eid) for eid in item.get("element_ids", []) if str(eid) not in used_elements]
        if not candidate_ids:
            continue
        merged = dict(item)
        merged["element_ids"] = candidate_ids
        merged["assignment_source"] = ASSIGNMENT_SOURCE_RULE
        matches.append(merged)
        used_elements.update(candidate_ids)
    result["matches"] = matches
    result["matching_method"] = "multimodal_with_deterministic_fallback"
    return result


def _clean_match(
    result: Any,
    slide: dict[str, Any],
    elements: list[dict[str, Any]],
    settings: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = fallback
    known_beats = {str(b.get("id") or "") for b in slide.get("narration_beats", []) or [] if isinstance(b, dict)}
    narrated_group_ids = {
        str(b.get("group_id") or "")
        for b in slide.get("narration_beats", []) or []
        if isinstance(b, dict) and str(b.get("group_id") or "")
    }
    known_groups = {
        str(g.get("id") or "")
        for g in slide.get("visual_groups", []) or []
        if isinstance(g, dict) and str(g.get("id") or "") in narrated_group_ids
    }
    known_elements = {str(e.get("element_id") or "") for e in elements}
    matches = []
    used = set()
    for item in result.get("matches", []) or []:
        if not isinstance(item, dict):
            continue
        gid = str(item.get("group_id") or "")
        if gid not in known_groups:
            continue
        bid = str(item.get("narration_beat_id") or "")
        if bid and bid not in known_beats:
            bid = ""
        eids = [
            str(e) for e in item.get("element_ids", [])
            if str(e) in known_elements and str(e) not in used
        ][: int(settings["max_group_elements"])]
        if not eids:
            continue
        try:
            conf = float(item.get("confidence", 0))
        except Exception:
            conf = 0
        object_ids = [str(value) for value in item.get("object_ids", []) or [] if str(value)]
        declared = _declared_origin(item)
        matches.append({"group_id": gid, "narration_beat_id": bid, "object_ids": object_ids, "expanded_from_object_ids": object_ids, "element_ids": eids, "seed_element_ids": list(eids), "assignment_source": declared, "element_origins": {element_id: declared for element_id in eids}, "confidence": conf, "reason": str(item.get("reason") or ""), "below_threshold": conf < float(settings["llm_confidence_threshold"])})
        used.update(eids)
    matched_groups = {str(item.get("group_id") or "") for item in matches}
    payload = {
        "slide_id": slide.get("slide_id"),
        "matches": matches,
        "unmatched_elements": sorted(known_elements - used),
        "unmatched_groups": sorted(known_groups - matched_groups),
        "warnings": result.get("warnings", []) if isinstance(result.get("warnings"), list) else [],
        "matching_method": result.get("matching_method") or fallback.get("matching_method") or "unknown",
    }
    # The batching record has to survive cleanup: "budget exhausted" and "a
    # later batch failed" are review facts, and dropping them here would hide
    # exactly the objects a human must look at.
    if isinstance(result.get("vision_batches"), dict):
        payload["vision_batches"] = dict(result["vision_batches"])
    return payload


def _rebind_shared_containers(
    match_payload: dict[str, Any],
    elements_payload: dict[str, Any],
    slide: dict[str, Any],
) -> dict[str, Any]:
    """Move page-level shared frames off a single content group.

    A sparse component (fill ratio <= 0.25) whose bbox contains the centers of
    two or more other groups' components is page furniture such as an outer
    frame or common border.  It may only belong to the narrated title group;
    one card must never exclusively own the frame that wraps its neighbours.
    """
    matches = [dict(item) for item in match_payload.get("matches", []) or [] if isinstance(item, dict)]
    if len(matches) < 2:
        return match_payload
    lookup: dict[str, dict[str, Any]] = {}
    for element in [
        *(elements_payload.get("elements", []) or []),
        *(elements_payload.get("residual_elements", []) or []),
    ]:
        if isinstance(element, dict) and str(element.get("element_id") or ""):
            lookup[str(element.get("element_id"))] = element

    def bounds(element_id: str) -> tuple[float, float, float, float] | None:
        element = lookup.get(element_id)
        return _box_xyxy(element.get("bbox")) if element else None

    group_boxes: dict[str, list[tuple[float, float, float, float]]] = {}
    for item in matches:
        gid = str(item.get("group_id") or "")
        for element_id in item.get("element_ids", []) or []:
            box = bounds(str(element_id))
            if box:
                group_boxes.setdefault(gid, []).append(box)

    visual_groups = [group for group in slide.get("visual_groups", []) or [] if isinstance(group, dict)]
    narrated_group_ids = {
        str(beat.get("group_id") or "")
        for beat in slide.get("narration_beats", []) or []
        if isinstance(beat, dict) and str(beat.get("group_id") or "")
    }
    title_target = next(
        (
            str(group.get("id") or "")
            for group in visual_groups
            if str(group.get("role") or "").strip().lower() == "title"
            and str(group.get("id") or "") in narrated_group_ids
        ),
        "",
    )
    if not title_target:
        return match_payload

    moved: list[dict[str, str]] = []
    for item in matches:
        gid = str(item.get("group_id") or "")
        if gid == title_target:
            continue
        keep: list[str] = []
        for element_id in [str(e) for e in item.get("element_ids", []) or []]:
            box = bounds(element_id)
            element = lookup.get(element_id)
            if not box or not element:
                keep.append(element_id)
                continue
            x1, y1, x2, y2 = box
            bbox_area = max(1.0, (x2 - x1) * (y2 - y1))
            if int(element.get("area", 0) or 0) / bbox_area > 0.25:
                keep.append(element_id)
                continue
            other_groups = 0
            for other_gid, other_boxes in group_boxes.items():
                if other_gid == gid:
                    continue
                if any(
                    x1 < (ox1 + ox2) / 2 < x2 and y1 < (oy1 + oy2) / 2 < y2
                    for ox1, oy1, ox2, oy2 in other_boxes
                ):
                    other_groups += 1
            if other_groups >= 2:
                moved.append({"element_id": element_id, "from_group_id": gid})
            else:
                keep.append(element_id)
        item["element_ids"] = keep
    if not moved:
        return match_payload

    title_item = next((item for item in matches if str(item.get("group_id") or "") == title_target), None)
    if title_item is None:
        beat_by_group = {
            str(beat.get("group_id") or ""): str(beat.get("id") or "")
            for beat in slide.get("narration_beats", []) or []
            if isinstance(beat, dict)
        }
        title_item = {
            "group_id": title_target,
            "narration_beat_id": beat_by_group.get(title_target, ""),
            "object_ids": [],
            "element_ids": [],
            "confidence": 1.0,
            "reason": "shared_container_geometry",
            "below_threshold": False,
        }
        matches.append(title_item)
    forced_owners = dict(match_payload.get("forced_element_owners") or {})
    warnings = list(match_payload.get("warnings", []) or [])
    for move in moved:
        if move["element_id"] not in title_item["element_ids"]:
            title_item["element_ids"].append(move["element_id"])
        forced_owners[move["element_id"]] = title_target
        warnings.append({
            "type": "shared_container_rebound",
            "group_id": move["from_group_id"],
            "to_group_id": title_target,
            "element_id": move["element_id"],
            "message": "共享外框/容器组件按几何包含关系改归标题组，请检查。",
        })
    result = dict(match_payload)
    surviving: list[dict[str, Any]] = []
    emptied_group_ids: list[str] = []
    for item in matches:
        if item.get("element_ids"):
            surviving.append(item)
        elif str(item.get("group_id") or ""):
            emptied_group_ids.append(str(item.get("group_id")))
    result["matches"] = surviving
    used = {str(eid) for item in surviving for eid in item.get("element_ids", []) or []}
    result["unmatched_elements"] = sorted(set(lookup) - used)
    result["unmatched_groups"] = list(dict.fromkeys([
        *(match_payload.get("unmatched_groups", []) or []),
        *(
            gid for gid in emptied_group_ids
            if gid not in {str(item.get("group_id") or "") for item in surviving}
        ),
    ]))
    result["forced_element_owners"] = forced_owners
    result["warnings"] = warnings
    return result


def _box_center(box: dict[str, Any]) -> tuple[float, float]:
    return (
        float(box.get("x", 0)) + float(box.get("w", 0)) / 2,
        float(box.get("y", 0)) + float(box.get("h", 0)) / 2,
    )


def _union_bounds(bounds_list: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    valid = [bounds for bounds in bounds_list if bounds]
    if not valid:
        return None
    return (
        min(bounds[0] for bounds in valid),
        min(bounds[1] for bounds in valid),
        max(bounds[2] for bounds in valid),
        max(bounds[3] for bounds in valid),
    )


def _layout_region(cx: float, cy: float, width: int, height: int) -> str:
    if cy < 220 * height / 1080:
        return "title"
    if cy >= 930 * height / 1080:
        return "subtitle"
    if cx < width / 3:
        return "content_left"
    if cx > width * 2 / 3:
        return "content_right"
    return "content_center"


def _compatible_regions(a: str, b: str) -> bool:
    if a == b:
        return True
    if "title" in {a, b} or "subtitle" in {a, b}:
        return False
    pairs = {frozenset({"content_left", "content_center"}), frozenset({"content_center", "content_right"})}
    return frozenset({a, b}) in pairs


def _configured_title_regions(capabilities: Any, width: int, height: int) -> dict[str, dict[str, int]]:
    """Read the canonical title/subtitle zones and scale them to this slide."""
    defaults = {
        "main_title": {"x": 110, "y": 55, "w": 1600, "h": 86},
        "subtitle": {"x": 110, "y": 150, "w": 1600, "h": 52},
    }
    canvas_width, canvas_height = 1920, 1080
    try:
        tokens = capabilities.read_style_tokens_data()
        canvas = tokens.get("canvas") if isinstance(tokens.get("canvas"), dict) else {}
        layout = tokens.get("layout") if isinstance(tokens.get("layout"), dict) else {}
        title_block = layout.get("title_block") if isinstance(layout.get("title_block"), dict) else {}
        canvas_width = max(1, int(canvas.get("width", canvas_width)))
        canvas_height = max(1, int(canvas.get("height", canvas_height)))
        for key in defaults:
            if isinstance(title_block.get(key), dict):
                defaults[key] = {**defaults[key], **title_block[key]}
    except Exception:
        pass

    scale_x, scale_y = width / canvas_width, height / canvas_height
    padding_x = max(4, round(24 * scale_x))
    padding_y = max(4, round(18 * scale_y))

    def scaled(source: dict[str, Any]) -> dict[str, int]:
        x1 = max(0, round(float(source.get("x", 0)) * scale_x) - padding_x)
        y1 = max(0, round(float(source.get("y", 0)) * scale_y) - padding_y)
        x2 = min(width, round((float(source.get("x", 0)) + float(source.get("w", 0))) * scale_x) + padding_x)
        y2 = min(height, round((float(source.get("y", 0)) + float(source.get("h", 0))) * scale_y) + padding_y)
        return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}

    main = scaled(defaults["main_title"])
    subtitle = scaled(defaults["subtitle"])
    x1 = min(main["x"], subtitle["x"])
    y1 = min(main["y"], subtitle["y"])
    x2 = max(main["x"] + main["w"], subtitle["x"] + subtitle["w"])
    y2 = max(main["y"] + main["h"], subtitle["y"] + subtitle["h"])
    return {
        "main_title": main,
        "subtitle": subtitle,
        "combined": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
    }


def _element_ids_in_region(elements_payload: dict[str, Any], region: dict[str, Any]) -> list[str]:
    result: list[str] = []
    rx1, ry1, rx2, ry2 = _box_xyxy(region) or (0, 0, 0, 0)
    for element in [
        *(elements_payload.get("elements", []) or []),
        *(elements_payload.get("residual_elements", []) or []),
    ]:
        if not isinstance(element, dict):
            continue
        box = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})
        bounds = _box_xyxy(box)
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
            element_id = str(element.get("element_id") or "")
            if element_id:
                result.append(element_id)
    return result


def _consolidate_title_regions(
    match_payload: dict[str, Any],
    elements_payload: dict[str, Any],
    slide: dict[str, Any],
    regions: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Assign title-band components to narrated title groups when available."""
    visual_groups = [group for group in slide.get("visual_groups", []) or [] if isinstance(group, dict)]
    group_roles = {
        str(group.get("id") or ""): str(group.get("role") or "").strip().lower()
        for group in visual_groups
        if str(group.get("id") or "")
    }
    title_group_ids = {group_id for group_id, role in group_roles.items() if role in {"title", "subtitle"}}
    beats = [beat for beat in slide.get("narration_beats", []) or [] if isinstance(beat, dict)]
    beat_by_group = {
        str(beat.get("group_id") or ""): beat
        for beat in beats
        if str(beat.get("group_id") or "")
    }
    narrated_group_ids = list(beat_by_group)
    narrated_title_groups = [
        group_id for group_id in narrated_group_ids if group_roles.get(group_id) == "title"
    ]
    narrated_subtitle_groups = [
        group_id for group_id in narrated_group_ids if group_roles.get(group_id) == "subtitle"
    ]
    # A title band may only belong to a narrated title group. Falling back to
    # the first narrated body group makes one visual title leak into several
    # body Masks during component completion. Legacy contracts without a
    # narrated title therefore keep the whole header static.
    main_target = narrated_title_groups[0] if narrated_title_groups else ""
    subtitle_target = (narrated_subtitle_groups or [main_target])[0] if main_target else ""

    main_ids = set(_element_ids_in_region(elements_payload, regions["main_title"]))
    subtitle_ids = (
        set(_element_ids_in_region(elements_payload, regions["subtitle"])) - main_ids
        if str(slide.get("subtitle") or "").strip()
        else set()
    )
    header_ids = main_ids | subtitle_ids
    dynamic_owners: dict[str, str] = {}
    if main_target:
        dynamic_owners.update({element_id: main_target for element_id in main_ids})
        dynamic_owners.update({element_id: subtitle_target for element_id in subtitle_ids})

    static_ids = {
        str(value)
        for value in match_payload.get("static_element_ids", []) or []
        if str(value) and str(value) not in dynamic_owners
    }
    if not dynamic_owners:
        static_ids.update(header_ids)

    matches: list[dict[str, Any]] = []
    for original in match_payload.get("matches", []) or []:
        if not isinstance(original, dict):
            continue
        item = dict(original)
        kept_ids = [
            str(element_id)
            for element_id in item.get("element_ids", []) or []
            if str(element_id) and str(element_id) not in header_ids
        ]
        item["element_ids"] = kept_ids
        stored_origins = item.get("element_origins") if isinstance(item.get("element_origins"), dict) else {}
        item["element_origins"] = {
            element_id: str(stored_origins.get(element_id) or _declared_origin(item))
            for element_id in kept_ids
        }
        matches.append(item)

    matches_by_group = {str(item.get("group_id") or ""): item for item in matches}
    for target_group in dict.fromkeys(dynamic_owners.values()):
        owned_ids = sorted(element_id for element_id, owner in dynamic_owners.items() if owner == target_group)
        item = matches_by_group.get(target_group)
        if item is None:
            beat = beat_by_group.get(target_group, {})
            item = {
                "group_id": target_group,
                "narration_beat_id": str(beat.get("id") or ""),
                "element_ids": [],
                "element_origins": {},
                "assignment_source": ASSIGNMENT_SOURCE_RULE,
                "confidence": 1.0,
                "reason": "title_region_geometry",
            }
            matches.append(item)
            matches_by_group[target_group] = item
        existing_ids = [] if group_roles.get(target_group) in {"title", "subtitle"} else item.get("element_ids", [])
        item["element_ids"] = list(dict.fromkeys([*existing_ids, *owned_ids]))
        # The header band is a contract rule, not a model decision, so the ids it
        # places keep their weaker provenance even though the group is accepted.
        origins = item.get("element_origins") if isinstance(item.get("element_origins"), dict) else {}
        for element_id in owned_ids:
            origins.setdefault(str(element_id), ASSIGNMENT_SOURCE_RULE)
        item["element_origins"] = origins
        item["below_threshold"] = False

    forced_owners = {
        str(element_id): str(group_id)
        for element_id, group_id in (match_payload.get("forced_element_owners") or {}).items()
        if str(element_id) not in header_ids
    }
    forced_owners.update(dynamic_owners)
    result = dict(match_payload)
    result["matches"] = matches
    result["forced_element_owners"] = forced_owners
    result["static_element_ids"] = sorted(static_ids)
    result["static_group_ids"] = sorted(title_group_ids) if not dynamic_owners else []
    result["title_region_policy"] = (
        "narrated_title_and_subtitle_masks"
        if dynamic_owners
        else "static_header_without_narration"
    )
    result["unmatched_groups"] = [
        group_id for group_id in result.get("unmatched_groups", []) or []
        if str(group_id) not in title_group_ids and str(group_id) not in dynamic_owners.values()
    ]
    return result


def _ensure_narrated_group_anchors(
    match_payload: dict[str, Any],
    elements_payload: dict[str, Any],
    slide: dict[str, Any],
) -> dict[str, Any]:
    """Guarantee one independent visual-island seed per narrated group."""
    beats = [beat for beat in slide.get("narration_beats", []) or [] if isinstance(beat, dict)]
    static_group_ids = {str(value) for value in match_payload.get("static_group_ids", []) or [] if str(value)}
    narrated_group_ids = list(dict.fromkeys(
        str(beat.get("group_id") or "") for beat in beats
        if str(beat.get("group_id") or "") and str(beat.get("group_id") or "") not in static_group_ids
    ))
    if not narrated_group_ids:
        return match_payload
    beat_by_group = {
        str(beat.get("group_id") or ""): str(beat.get("id") or "")
        for beat in beats
        if str(beat.get("group_id") or "")
    }
    matches = [dict(item) for item in match_payload.get("matches", []) or [] if isinstance(item, dict)]
    accepted_by_group = {
        str(item.get("group_id") or ""): item
        for item in matches
        if str(item.get("group_id") or "") in narrated_group_ids
        and not item.get("below_threshold")
        and item.get("element_ids")
    }
    missing_group_ids = [group_id for group_id in narrated_group_ids if group_id not in accepted_by_group]
    if not missing_group_ids:
        return match_payload

    all_elements = [
        element for element in [
            *(elements_payload.get("elements", []) or []),
            *(elements_payload.get("residual_elements", []) or []),
        ] if isinstance(element, dict) and str(element.get("element_id") or "")
    ]
    forced_owners = dict(match_payload.get("forced_element_owners") or {})
    title_locked_ids = set(forced_owners) | {
        str(value) for value in match_payload.get("static_element_ids", []) or [] if str(value)
    }
    canvas = elements_payload.get("canvas", {}) if isinstance(elements_payload.get("canvas"), dict) else {}
    canvas_area = max(1, int(canvas.get("width", 1920))) * max(1, int(canvas.get("height", 1080)))
    prominent_area = max(400, round(canvas_area * 0.003))
    # Protect ALL element_ids from already-accepted groups. When the semantic
    # patch is active, VL matches objects as wholes; stealing any element from
    # an accepted group would break the semantic_object boundary and cause the
    # same label/card to be split across multiple narration beats.
    protected_anchor_ids: set[str] = set()
    for item in accepted_by_group.values():
        protected_anchor_ids.update(
            str(element_id) for element_id in item.get("element_ids", []) or []
            if str(element_id)
        )
    unavailable_ids = title_locked_ids | protected_anchor_ids
    available = [element for element in all_elements if str(element.get("element_id") or "") not in unavailable_ids]
    available.sort(key=lambda element: int(element.get("area", 0)), reverse=True)
    prominent = [element for element in available if int(element.get("area", 0)) >= prominent_area]
    candidates = [*prominent, *[element for element in available if element not in prominent]]

    claimed_seed_ids: set[str] = set()
    for group_id in missing_group_ids:
        seed = next(
            (
                element for element in candidates
                if str(element.get("element_id") or "") not in claimed_seed_ids
                and str(element.get("element_id") or "") not in forced_owners
            ),
            None,
        )
        if seed is None:
            continue
        seed_id = str(seed.get("element_id") or "")
        claimed_seed_ids.add(seed_id)
        for item in matches:
            item["element_ids"] = [str(element_id) for element_id in item.get("element_ids", []) or [] if str(element_id) != seed_id]
            origins = item.get("element_origins") if isinstance(item.get("element_origins"), dict) else None
            if origins is not None:
                origins.pop(seed_id, None)
        seeded = {
            "group_id": group_id,
            "narration_beat_id": beat_by_group.get(group_id, ""),
            "element_ids": [seed_id],
            "element_origins": {seed_id: ASSIGNMENT_SOURCE_RULE},
            "assignment_source": ASSIGNMENT_SOURCE_RULE,
            "confidence": 0.82,
            "reason": "deterministic prominent visual-island anchor",
            "below_threshold": False,
        }
        matches.append(seeded)
        forced_owners[seed_id] = group_id

    anchored_groups = {
        str(item.get("group_id") or "") for item in matches
        if not item.get("below_threshold") and item.get("element_ids")
    }
    result = dict(match_payload)
    result["matches"] = matches
    result["forced_element_owners"] = forced_owners
    result["unmatched_groups"] = [group_id for group_id in narrated_group_ids if group_id not in anchored_groups]
    result["anchor_policy"] = "one_visual_island_per_narrated_group"
    return result


def _finalize_ownership_provenance(
    accepted: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    group_roles: dict[str, str],
    model_participated: bool,
) -> dict[str, Any]:
    """Freeze per-group ownership evidence and prove coverage bought no confidence.

    Coverage completion can hand a component an owner; it can never make that
    ownership semantically certain.  Each group therefore reports which source
    decided every one of its components, keeps the confidence it had before the
    completion passes (any later inflation is clamped back), and is listed as
    unconfirmed when the multimodal model never claimed any of its pixels.
    """
    groups: list[dict[str, Any]] = []
    unconfirmed_group_ids: list[str] = []
    large_forced_components: list[dict[str, Any]] = []
    for item in accepted:
        group_id = str(item.get("group_id") or "")
        element_ids = [str(value) for value in item.get("element_ids", []) or [] if str(value) in by_id]
        origins = _element_origins(item, element_ids, ASSIGNMENT_SOURCE_MODEL)
        item["element_origins"] = origins
        areas = {element_id: max(0, int(by_id[element_id].get("area", 0))) for element_id in element_ids}
        total_area = sum(areas.values())
        model_ids = [element_id for element_id in element_ids if origins[element_id] == ASSIGNMENT_SOURCE_MODEL]
        rule_ids = [element_id for element_id in element_ids if origins[element_id] == ASSIGNMENT_SOURCE_RULE]
        completion_ids = [
            element_id for element_id in element_ids
            if origins[element_id] == ASSIGNMENT_SOURCE_COMPLETION
        ]
        # Snapshot-first: the completion passes above never rewrite confidence, and
        # this guard keeps it that way for any future closer.
        before = _float(item.get("confidence_before_completion"), -1.0, -1.0, 1.0)
        if before < 0:
            before = _float(item.get("confidence"), 0.0, 0.0, 1.0)
        confidence = _float(item.get("confidence"), 0.0, 0.0, 1.0)
        if confidence > before:
            item["confidence"] = before
            item["confidence_capped"] = True
            confidence = before
        item["confidence_before_completion"] = before
        distinct_sources = set(origins.values())
        item["assignment_source"] = (
            next(iter(distinct_sources))
            if len(distinct_sources) == 1 and distinct_sources
            else "mixed"
        )
        item["model_element_count"] = len(model_ids)
        item["completion_element_count"] = len(completion_ids)
        item["semantically_confirmed"] = bool(model_ids) and len(model_ids) == len(element_ids) and not item.get("below_threshold")
        model_area = sum(areas[element_id] for element_id in model_ids)
        record = {
            "group_id": group_id,
            "role": group_roles.get(group_id, ""),
            "assignment_source": item["assignment_source"],
            "element_count": len(element_ids),
            "model_element_count": len(model_ids),
            "rule_element_count": len(rule_ids),
            "completion_element_count": len(completion_ids),
            "model_ownership_ratio": round(model_area / total_area, 4) if total_area else 0.0,
            "semantically_confirmed": item["semantically_confirmed"],
            "confidence": round(confidence, 4),
            "confidence_capped": bool(item.get("confidence_capped")),
        }
        groups.append(record)
        # Title and subtitle bands are owned by the narration contract's geometry
        # on purpose; only a body group without a single model claim is a real
        # ambiguity, because that group's whole story-to-pixel link is a guess.
        if (
            element_ids
            and not model_ids
            and record["role"] not in _MODEL_DECIDED_ROLES_EXCLUDED
        ):
            unconfirmed_group_ids.append(group_id)
        for element_id in completion_ids:
            ratio = areas[element_id] / total_area if total_area else 0.0
            if ratio >= LARGE_FORCED_COMPONENT_AREA_RATIO:
                large_forced_components.append({
                    "group_id": group_id,
                    "element_id": element_id,
                    "component_area": areas[element_id],
                    "group_area_ratio": round(ratio, 4),
                })
    return {
        "version": "ai_mask_assignment_provenance_v1",
        "groups": groups,
        "unconfirmed_group_ids": unconfirmed_group_ids,
        # Whether a multimodal answer contributed to this page at all.  The
        # evidence above is always recorded; this says whether an unconfirmed
        # group is something a person can act on, or simply the expected shape
        # of a page that ran on rules because no model answered.
        "model_participated": bool(model_participated),
        "large_forced_components": large_forced_components,
        "confidence_policy": "completion_never_raises_semantic_confidence",
    }


def _complete_component_coverage(
    match_payload: dict[str, Any],
    elements_payload: dict[str, Any],
    slide: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assign every foreground component to exactly one accepted narration group.

    The multimodal model chooses semantic anchors. Remaining visual-only,
    decorative, and tiny antialiased components are attached to the closest
    anchor by reading-row proximity. Anchor boxes are frozen before completion
    so a large decoration cannot pull later components into the wrong group.

    Ownership is recorded per component as a model claim, a deterministic rule,
    or coverage completion, and completion never raises a group's confidence.
    """
    candidates = [e for e in elements_payload.get("elements", []) or [] if isinstance(e, dict)]
    residual = [e for e in elements_payload.get("residual_elements", []) or [] if isinstance(e, dict)]
    complete_foreground = candidates + residual
    static_element_ids = {
        str(value) for value in match_payload.get("static_element_ids", []) or [] if str(value)
    }
    static_elements = [
        element for element in complete_foreground
        if str(element.get("element_id") or "") in static_element_ids
    ]
    all_elements = [
        element for element in complete_foreground
        if str(element.get("element_id") or "") not in static_element_ids
    ]
    by_id = {str(e.get("element_id") or ""): e for e in all_elements if str(e.get("element_id") or "")}
    accepted = [
        item for item in match_payload.get("matches", []) or []
        if isinstance(item, dict) and not item.get("below_threshold") and item.get("element_ids")
    ]
    for item in accepted:
        # Snapshot the incoming certainty so the completion passes below can be
        # proven not to have inflated it.
        item["confidence_before_completion"] = _float(item.get("confidence"), 0.0, 0.0, 1.0)
    assigned: set[str] = set()
    forced_owners = {
        str(element_id): str(group_id)
        for element_id, group_id in (match_payload.get("forced_element_owners") or {}).items()
        if str(element_id) and str(group_id)
    }
    anchors: dict[str, dict[str, float]] = {}
    member_boxes: dict[str, list[tuple[str, tuple[float, float, float, float]]]] = {}
    canvas = elements_payload.get("canvas", {}) if isinstance(elements_payload.get("canvas"), dict) else {}
    width = max(1, int(canvas.get("width", 1920)))
    height = max(1, int(canvas.get("height", 1080)))
    group_roles = {
        str(group.get("id") or ""): str(group.get("role") or "").strip().lower()
        for group in ((slide or {}).get("visual_groups", []) or [])
        if isinstance(group, dict) and str(group.get("id") or "")
    }
    for item in accepted:
        anchor_elements = [
            by_id[str(element_id)]
            for element_id in item.get("element_ids", []) or []
            if str(element_id) in by_id
        ]
        boxes = [element.get("raw_bbox", element.get("bbox", {})) for element in anchor_elements]
        if not boxes:
            continue
        largest = max(anchor_elements, key=lambda element: int(element.get("area", 0)))
        largest_box = largest.get("raw_bbox", largest.get("bbox", {}))
        largest_bounds = _box_xyxy(largest_box)
        if not largest_bounds:
            continue
        lx1, ly1, lx2, ly2 = largest_bounds
        dominant_w, dominant_h = lx2 - lx1, ly2 - ly1
        dominant_area = max(1, int(largest.get("area", 0)))
        absorb_padding = max(28.0, min(140.0, 0.18 * max(dominant_w, dominant_h)))

        # Build an island envelope from the dominant component plus only the
        # seed components that are genuinely adjacent to it. A stray semantic
        # ID on the other side of the page must not stretch the envelope.
        clustered_bounds: list[tuple[float, float, float, float]] = [largest_bounds]
        for box in boxes:
            bounds = _box_xyxy(box)
            if not bounds or bounds == largest_bounds:
                continue
            cx, cy = _box_center(box)
            dx = max(lx1 - cx, 0.0, cx - lx2)
            dy = max(ly1 - cy, 0.0, cy - ly2)
            if float(np.hypot(dx, dy)) <= absorb_padding:
                clustered_bounds.append(bounds)
        ax1 = min(value[0] for value in clustered_bounds)
        ay1 = min(value[1] for value in clustered_bounds)
        ax2 = max(value[2] for value in clustered_bounds)
        ay2 = max(value[3] for value in clustered_bounds)
        group_id = str(item.get("group_id") or "")
        anchors[group_id] = {
            "x": ax1,
            "y": ay1,
            "w": max(1.0, ax2 - ax1),
            "h": max(1.0, ay2 - ay1),
            "absorb_padding": absorb_padding,
            "dominant_area": float(dominant_area),
        }
        member_boxes[group_id] = [
            (str(element.get("element_id") or ""), bounds)
            for element in anchor_elements
            for bounds in (
                _box_xyxy(element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})),
            )
            if bounds
        ]

    # Recheck only small secondary components that the multimodal model placed
    # far from their group's dominant visual island. This is deliberately
    # conservative: dominant components never move, and a new owner must be at
    # least 1.5x closer to avoid geometry overriding a plausible semantic link.
    dominant_ids: dict[str, str] = {}
    for item in accepted:
        group_id = str(item.get("group_id") or "")
        owned = [by_id[str(value)] for value in item.get("element_ids", []) or [] if str(value) in by_id]
        if owned:
            dominant_ids[group_id] = str(max(owned, key=lambda element: int(element.get("area", 0))).get("element_id") or "")

    def anchor_distance(element: dict[str, Any], anchor: dict[str, float]) -> float:
        element_bounds = _box_xyxy(element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {}))
        anchor_bounds = _box_xyxy(anchor)
        if not element_bounds or not anchor_bounds:
            return float("inf")
        ex1, ey1, ex2, ey2 = element_bounds
        ax1, ay1, ax2, ay2 = anchor_bounds
        return float(np.hypot(max(ax1 - ex2, 0.0, ex1 - ax2), max(ay1 - ey2, 0.0, ey1 - ay2)))

    def group_gap(element: dict[str, Any], group_id: str, anchor: dict[str, float]) -> float:
        """Distance to a group = closer of its frozen envelope or any owned member box.

        The envelope only clusters members adjacent to the dominant component,
        so a group's sparse periphery (e.g. the left column of a card whose
        dominant block sits right of centre) can sit farther away than the
        neighbouring group's envelope. Comparing against the group's own
        accepted member boxes keeps gap-filling ownership local.
        """
        element_bounds = _box_xyxy(element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {}))
        best = anchor_distance(element, anchor)
        if element_bounds:
            element_id = str(element.get("element_id") or "")
            for member_id, bounds in member_boxes.get(group_id, []):
                if member_id == element_id:
                    continue
                ex1, ey1, ex2, ey2 = element_bounds
                bx1, by1, bx2, by2 = bounds
                best = min(best, float(np.hypot(max(bx1 - ex2, 0.0, ex1 - bx2), max(by1 - ey2, 0.0, ey1 - by2))))
        return best

    moves: list[tuple[str, str, str]] = []
    for item in accepted:
        current_group = str(item.get("group_id") or "")
        current_anchor = anchors.get(current_group)
        if not current_anchor:
            continue
        for value in list(item.get("element_ids", []) or []):
            element_id = str(value)
            if (
                element_id == dominant_ids.get(current_group)
                or element_id not in by_id
                or element_id in forced_owners
            ):
                continue
            element = by_id[element_id]
            if int(element.get("area", 0)) > float(current_anchor.get("dominant_area", 0)) * 0.35:
                continue
            # This pass must stay envelope-only. Comparing against the current
            # owner's own member boxes is circular: a mis-bound element sitting
            # next to its wrong group's cards would defend that wrong binding
            # and never be corrected. Only the frozen anchor envelope decides
            # whether a better-anchored group should steal the component.
            distances = sorted(
                (anchor_distance(element, anchor), group_id)
                for group_id, anchor in anchors.items()
            )
            if not distances or distances[0][1] == current_group:
                continue
            best_distance, best_group = distances[0]
            current_distance = anchor_distance(element, current_anchor)
            if current_distance >= max(24.0, best_distance * 1.5):
                moves.append((element_id, current_group, best_group))
    for element_id, old_group, new_group in moves:
        old_item = next((item for item in accepted if str(item.get("group_id") or "") == old_group), None)
        new_item = next((item for item in accepted if str(item.get("group_id") or "") == new_group), None)
        if old_item is None or new_item is None:
            continue
        old_item["element_ids"] = [value for value in old_item.get("element_ids", []) or [] if str(value) != element_id]
        new_item["element_ids"] = list(dict.fromkeys([*(new_item.get("element_ids", []) or []), element_id]))
        if isinstance(old_item.get("element_origins"), dict):
            old_item["element_origins"].pop(element_id, None)
        # Geometry overrode the first answer, so this ownership is no longer a
        # model claim even when the matcher originally proposed the pair.
        new_origins = new_item.setdefault("element_origins", {})
        if isinstance(new_origins, dict):
            new_origins[element_id] = ASSIGNMENT_SOURCE_RULE

    for item in accepted:
        seed_ids = [str(element_id) for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id]
        existing_seed_ids = item.get("seed_element_ids", []) or []
        item["seed_element_ids"] = list(dict.fromkeys([*existing_seed_ids, *seed_ids]))
        item["element_ids"] = list(dict.fromkeys(seed_ids))
        item["element_origins"] = _element_origins(item, item["element_ids"], ASSIGNMENT_SOURCE_MODEL)
        item["residual_element_ids"] = []
        assigned.update(item["element_ids"])

    residual_assignment_report: list[dict[str, Any]] = []
    # When the semantic_object patch is active, residual fragments are absorbed
    # into semantic_objects BEFORE VL matching and expanded via _expand_matches.
    # In that case most/all residual elements are already in 'assigned' and the
    # distance convergence below is a no-op.  We still run it for any truly
    # unassigned fragments (edge cases where absorption missed something).
    unassigned_residual = [
        element for element in residual
        if str(element.get("element_id") or "") not in assigned
        and str(element.get("element_id") or "") in by_id
    ]
    if accepted and anchors and unassigned_residual:
        CONVERGENCE_RATIO = 1.5

        def box_to_box_distance(anchor: dict[str, float], elem_bounds: tuple[float, float, float, float]) -> float:
            """Shortest gap between two axis-aligned rectangles (0 if overlapping)."""
            anchor_bounds = _box_xyxy(anchor)
            if not anchor_bounds:
                return float("inf")
            ax1, ay1, ax2, ay2 = anchor_bounds
            ex1, ey1, ex2, ey2 = elem_bounds
            dx = max(ax1 - ex2, 0.0, ex1 - ax2)
            dy = max(ay1 - ey2, 0.0, ey1 - ay2)
            return float(np.hypot(dx, dy))

        for element in sorted(unassigned_residual, key=lambda item: (
            float((item.get("center") or {}).get("y", 0)),
            float((item.get("center") or {}).get("x", 0))
        )):
            element_id = str(element.get("element_id") or "")
            if not element_id or element_id in assigned or element_id not in by_id:
                continue
            box = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})
            bounds = _box_xyxy(box)
            if not bounds:
                continue
            cx, cy = _box_center(box)
            element_region = _layout_region(cx, cy, width, height)

            # Compute box-to-box distance to every accepted group anchor
            dist_list = []
            for item in accepted:
                group_id = str(item.get("group_id") or "")
                anchor = anchors.get(group_id)
                if not anchor:
                    continue
                anchor_cx, anchor_cy = _box_center(anchor)
                anchor_region = _layout_region(anchor_cx, anchor_cy, width, height)
                if not _compatible_regions(element_region, anchor_region):
                    continue
                dist = min(box_to_box_distance(anchor, bounds), group_gap(element, group_id, anchor))
                dist_list.append((dist, item, anchor))

            dist_list.sort(key=lambda value: value[0])
            if not dist_list:
                residual_assignment_report.append({
                    "element_id": element_id,
                    "status": "unassigned",
                    "reason": "no_compatible_anchor",
                    "region": element_region
                })
                continue

            d1 = dist_list[0][0]
            d2 = dist_list[1][0] if len(dist_list) > 1 else float("inf")
            best = dist_list[0][1]

            # 1.5x convergence rule: converge if d2 >= 1.5 * d1, or only one anchor
            should_converge = (d2 >= CONVERGENCE_RATIO * d1) or len(dist_list) == 1
            if not should_converge:
                residual_assignment_report.append({
                    "element_id": element_id,
                    "status": "unassigned",
                    "reason": "ambiguous_zone",
                    "d1": round(d1, 2),
                    "d2": round(d2, 2),
                    "ratio": round(d2 / max(d1, 0.01), 3),
                    "region": element_region
                })
                continue

            best.setdefault("element_ids", []).append(element_id)
            best.setdefault("residual_element_ids", []).append(element_id)
            best.setdefault("element_origins", {})[element_id] = ASSIGNMENT_SOURCE_COMPLETION
            assigned.add(element_id)
            residual_assignment_report.append({
                "element_id": element_id,
                "status": "assigned",
                "group_id": str(best.get("group_id") or ""),
                "distance": round(d1, 2),
                "d2": round(d2, 2) if d2 != float("inf") else None,
                "ratio": round(d2 / max(d1, 0.01), 3) if d2 != float("inf") else None,
                "region": element_region
            })

    # The production contract requires every foreground component to have one
    # owner.  The vision model chooses semantic anchors; this final deterministic
    # pass only closes coverage gaps by attaching any remaining component to the
    # nearest compatible anchor.  It never changes an existing owner.
    forced_completion_assignments: list[dict[str, Any]] = []
    if accepted and anchors:
        residual_ids = {
            str(element.get("element_id") or "")
            for element in residual
            if str(element.get("element_id") or "")
        }
        for element_id in sorted(set(by_id) - assigned):
            element = by_id[element_id]
            box = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox", {})
            cx, cy = _box_center(box)
            element_region = _layout_region(cx, cy, width, height)
            ranked: list[tuple[int, float, dict[str, Any]]] = []
            for item in accepted:
                group_id = str(item.get("group_id") or "")
                anchor = anchors.get(group_id)
                if not anchor:
                    continue
                anchor_cx, anchor_cy = _box_center(anchor)
                anchor_region = _layout_region(anchor_cx, anchor_cy, width, height)
                compatible = _compatible_regions(element_region, anchor_region)
                ranked.append((0 if compatible else 1, group_gap(element, group_id, anchor), item))
            if not ranked:
                continue
            compatibility_rank, distance, owner = min(
                ranked,
                key=lambda value: (value[0], value[1], str(value[2].get("group_id") or "")),
            )
            owner.setdefault("element_ids", []).append(element_id)
            if element_id in residual_ids:
                owner.setdefault("residual_element_ids", []).append(element_id)
            owner.setdefault("element_origins", {})[element_id] = ASSIGNMENT_SOURCE_COMPLETION
            assigned.add(element_id)
            assignment = {
                "element_id": element_id,
                "status": "assigned",
                "group_id": str(owner.get("group_id") or ""),
                "distance": round(distance, 2),
                "region": element_region,
                "forced": True,
                "compatible_region": compatibility_rank == 0,
                "reason": "nearest_compatible_anchor_after_ambiguity" if compatibility_rank == 0 else "nearest_anchor_without_compatible_region",
                "candidate_component": element_id not in residual_ids,
            }
            previous = next(
                (item for item in residual_assignment_report if item.get("element_id") == element_id),
                None,
            )
            if previous is not None:
                previous.clear()
                previous.update(assignment)
            else:
                residual_assignment_report.append(assignment)
            forced_completion_assignments.append(assignment)

    provenance = _finalize_ownership_provenance(
        accepted,
        by_id,
        group_roles,
        # ``multimodal`` is only in the method name once the vision answer has
        # been merged in; a deterministic-prior page never claims model evidence.
        str(match_payload.get("matching_method") or "").startswith("multimodal"),
    )

    unassigned_ids = sorted(set(by_id) - assigned)
    target_rle = _merge_row_runs(complete_foreground, width, height)
    foreground_pixels = _rle_pixel_count(target_rle)
    group_rles = [
        _merge_row_runs(
            [by_id[str(element_id)] for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id],
            width,
            height,
        )
        for item in accepted
    ]
    assigned_elements = [by_id[element_id] for element_id in assigned if element_id in by_id]
    dynamic_assigned_rle = _merge_row_runs(assigned_elements, width, height)
    dynamic_assigned_pixels = _rle_pixel_count(dynamic_assigned_rle)
    assigned_rle = _merge_row_runs([*assigned_elements, *static_elements], width, height)
    assigned_pixels = _rle_pixel_count(assigned_rle)
    group_pixel_sum = sum(_rle_pixel_count(rle) for rle in group_rles)
    overlap_pixels = max(0, group_pixel_sum - dynamic_assigned_pixels)
    coverage = assigned_pixels / foreground_pixels if foreground_pixels else 0.0
    semantic_group_checks: list[dict[str, Any]] = []
    semantic_warnings: list[dict[str, Any]] = []
    forced_candidate_groups = sorted({
        str(item.get("group_id") or "")
        for item in forced_completion_assignments
        if item.get("candidate_component") and str(item.get("group_id") or "")
    })
    for group_id in forced_candidate_groups:
        semantic_warnings.append({
            "type": "forced_low_confidence_components",
            "group_id": group_id,
            "component_count": sum(
                1 for item in forced_completion_assignments
                if item.get("candidate_component") and str(item.get("group_id") or "") == group_id
            ),
        })
    provenance_records = {str(record["group_id"]): record for record in provenance["groups"]}
    if provenance["model_participated"]:
        for group_id in provenance["unconfirmed_group_ids"]:
            record = provenance_records.get(group_id) or {}
            semantic_warnings.append({
                "type": "unconfirmed_semantic_ownership",
                "group_id": group_id,
                "assignment_source": record.get("assignment_source", ASSIGNMENT_SOURCE_RULE),
                "element_count": int(record.get("element_count", 0)),
                "completion_element_count": int(record.get("completion_element_count", 0)),
            })
    for component in provenance["large_forced_components"]:
        semantic_warnings.append({
            "type": "forced_large_component_completed",
            "group_id": str(component["group_id"]),
            "element_id": component["element_id"],
            "component_area": component["component_area"],
            "group_area_ratio": component["group_area_ratio"],
        })
    existing_warnings = list(match_payload.get("warnings", []) or [])
    structural_model_warnings = [
        dict(warning)
        for warning in existing_warnings
        if isinstance(warning, dict)
        and warning.get("type") == "insufficient_visual_groups_for_independent_objects"
    ]
    blocking_errors: list[dict[str, Any]] = [
        dict(issue)
        for issue in visual_group_atomicity_issues(slide)
    ] + structural_model_warnings
    for item in accepted:
        group_id = str(item.get("group_id") or "")
        element_ids = [str(element_id) for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id]
        residual_ids = [str(element_id) for element_id in item.get("residual_element_ids", []) or [] if str(element_id)]
        bounds_list = [
            _box_xyxy(by_id[element_id].get("raw_bbox") if isinstance(by_id[element_id].get("raw_bbox"), dict) else by_id[element_id].get("bbox", {}))
            for element_id in element_ids
        ]
        regions = sorted({
            _layout_region(*_box_center(by_id[element_id].get("raw_bbox") if isinstance(by_id[element_id].get("raw_bbox"), dict) else by_id[element_id].get("bbox", {})), width, height)
            for element_id in element_ids
        })
        residual_ratio = len(residual_ids) / max(1, len(element_ids))
        provenance_record = provenance_records.get(group_id, {})
        check = {
            "group_id": group_id,
            "element_count": len(element_ids),
            "residual_count": len(residual_ids),
            "residual_ratio": round(residual_ratio, 3),
            "regions": regions,
            # Pixels owned and narration confirmed are two different statements:
            # the fields above describe the Mask geometry, this block reports how
            # much of that geometry the multimodal answer actually vouched for.
            "narration": {
                "assignment_source": provenance_record.get("assignment_source", ASSIGNMENT_SOURCE_RULE),
                "model_element_count": int(provenance_record.get("model_element_count", 0)),
                "rule_element_count": int(provenance_record.get("rule_element_count", 0)),
                "completion_element_count": int(provenance_record.get("completion_element_count", 0)),
                "model_ownership_ratio": float(provenance_record.get("model_ownership_ratio", 0.0)),
                "semantically_confirmed": bool(provenance_record.get("semantically_confirmed")),
                "confidence": float(provenance_record.get("confidence", 0.0)),
                "confidence_capped": bool(provenance_record.get("confidence_capped")),
            },
        }
        semantic_group_checks.append(check)
        if "subtitle" in regions:
            blocking_errors.append({"type": "dynamic_group_enters_subtitle_safe_zone", "group_id": group_id})
        title_element_ids = [
            element_id
            for element_id in element_ids
            if _layout_region(
                *_box_center(
                    by_id[element_id].get("raw_bbox")
                    if isinstance(by_id[element_id].get("raw_bbox"), dict)
                    else by_id[element_id].get("bbox", {})
                ),
                width,
                height,
            ) == "title"
        ]
        narrated_title_ownership = (
            match_payload.get("title_region_policy") == "narrated_title_and_subtitle_masks"
            and title_element_ids
            and group_roles.get(group_id) == "title"
            and all(forced_owners.get(element_id) == group_id for element_id in title_element_ids)
        )
        if "title" in regions and not narrated_title_ownership:
            blocking_errors.append({"type": "dynamic_group_owns_title_region_pixels", "group_id": group_id})
        content_regions = [region for region in regions if region.startswith("content_")]
        if "content_left" in content_regions and "content_right" in content_regions:
            # Wide comparisons and process diagrams legitimately span both
            # sides of a slide. Geometry alone is not strong enough evidence
            # to reject the multimodal semantic ownership, so route this to
            # human review instead of failing an otherwise exact Mask.
            semantic_warnings.append({"type": "group_crosses_left_and_right_regions", "group_id": group_id})
        if residual_ratio > 0.85:
            blocking_errors.append({"type": "too_many_residual_components", "group_id": group_id, "residual_ratio": round(residual_ratio, 3)})
        elif residual_ratio > 0.5:
            semantic_warnings.append({"type": "many_residual_components", "group_id": group_id, "residual_ratio": round(residual_ratio, 3)})
        union = _union_bounds(bounds_list)
        if union:
            check["bbox"] = {"x": round(union[0]), "y": round(union[1]), "w": round(union[2] - union[0]), "h": round(union[3] - union[1])}
    confirmed_group_count = sum(1 for record in provenance["groups"] if record["semantically_confirmed"])
    narration_contract_passed = bool(accepted) and not blocking_errors
    semantic_quality = {
        "version": "ai_mask_semantic_quality_v3",
        # Narration constraint: whether each group's ownership is defensible as
        # story-to-pixel mapping.  Kept apart from ``quality.pixel_contract_passed``
        # because a page can hold every foreground pixel and still group the
        # narration wrongly.
        "narration_contract_passed": narration_contract_passed,
        # Compatibility alias: existing advance logic only understands `passed`.
        "passed": narration_contract_passed,
        "confirmed_group_count": confirmed_group_count,
        "model_participated": provenance["model_participated"],
        "unconfirmed_group_ids": list(provenance["unconfirmed_group_ids"]),
        "group_checks": semantic_group_checks,
        "warnings": semantic_warnings,
        "blocking_errors": blocking_errors,
        "residual_assignment_summary": {
            "assigned": sum(1 for item in residual_assignment_report if item.get("status") == "assigned"),
            "unassigned": sum(1 for item in residual_assignment_report if item.get("status") == "unassigned"),
        },
    }
    pixel_contract_passed = (
        bool(accepted)
        and coverage >= AI_MASK_MIN_FOREGROUND_COVERAGE
        and len(unassigned_ids) == 0
        and overlap_pixels == 0
    )
    quality = {
        "version": "ai_mask_quality_v3",
        "foreground_pixel_count": foreground_pixels,
        "assigned_foreground_pixel_count": assigned_pixels,
        "static_header_pixel_count": _rle_pixel_count(_merge_row_runs(static_elements, width, height)),
        "foreground_coverage_ratio": round(coverage, 6),
        "unassigned_component_count": len(unassigned_ids),
        "overlap_pixel_count": overlap_pixels,
        "exclusive_component_ownership": overlap_pixels == 0,
        # Pixel constraint: every foreground component has exactly one owner.
        "pixel_contract_passed": pixel_contract_passed,
        "semantic_quality_passed": semantic_quality["passed"],
        "minimum_foreground_coverage_ratio": AI_MASK_MIN_FOREGROUND_COVERAGE,
        "passed": pixel_contract_passed and semantic_quality["passed"],
    }
    match_payload["unmatched_elements"] = unassigned_ids
    match_payload["quality"] = quality
    match_payload["semantic_quality"] = semantic_quality
    match_payload["assignment_provenance"] = provenance
    match_payload["residual_assignment_report"] = residual_assignment_report
    if quality["passed"] and not semantic_warnings and not existing_warnings:
        match_payload["warnings"] = []
    else:
        non_structural_model_warnings = [
            warning
            for warning in existing_warnings
            if not (
                isinstance(warning, dict)
                and warning.get("type") == "insufficient_visual_groups_for_independent_objects"
            )
        ]
        match_payload["warnings"] = [*non_structural_model_warnings, *semantic_warnings, *blocking_errors]
    match_payload["matching_method"] = str(match_payload.get("matching_method") or "unknown") + "+constrained_component_completion"
    match_payload["component_assignment_policy"] = "dominant_island_2d_absorption_v2"
    return match_payload


