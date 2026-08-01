"""Semantic ownership cleanup and deterministic component completion for AI Mask."""

from __future__ import annotations

from typing import Any

import numpy as np

from ai_mask_component_detection import _merge_row_runs, _rle_pixel_count
from ai_mask_contracts import AI_MASK_MIN_FOREGROUND_COVERAGE
from scripts.visual_group_semantics import visual_group_atomicity_issues


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
    matches = [item for item in result.get("matches", []) or [] if isinstance(item, dict)]
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
        matches.append({"group_id": gid, "narration_beat_id": bid, "object_ids": object_ids, "expanded_from_object_ids": object_ids, "element_ids": eids, "seed_element_ids": list(eids), "confidence": conf, "reason": str(item.get("reason") or ""), "below_threshold": conf < float(settings["llm_confidence_threshold"])})
        used.update(eids)
    matched_groups = {str(item.get("group_id") or "") for item in matches}
    return {
        "slide_id": slide.get("slide_id"),
        "matches": matches,
        "unmatched_elements": sorted(known_elements - used),
        "unmatched_groups": sorted(known_groups - matched_groups),
        "warnings": result.get("warnings", []) if isinstance(result.get("warnings"), list) else [],
        "matching_method": result.get("matching_method") or fallback.get("matching_method") or "unknown",
    }


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


def _bounds_area(bounds: tuple[float, float, float, float] | None) -> float:
    if not bounds:
        return 0.0
    return max(0.0, bounds[2] - bounds[0]) * max(0.0, bounds[3] - bounds[1])


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


def _speech_signature(value: Any) -> str:
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())


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
        item["element_ids"] = [
            str(element_id)
            for element_id in item.get("element_ids", []) or []
            if str(element_id) and str(element_id) not in header_ids
        ]
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
                "confidence": 1.0,
                "reason": "title_region_geometry",
            }
            matches.append(item)
            matches_by_group[target_group] = item
        existing_ids = [] if group_roles.get(target_group) in {"title", "subtitle"} else item.get("element_ids", [])
        item["element_ids"] = list(dict.fromkeys([*existing_ids, *owned_ids]))
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
        seeded = {
            "group_id": group_id,
            "narration_beat_id": beat_by_group.get(group_id, ""),
            "element_ids": [seed_id],
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
    assigned: set[str] = set()
    forced_owners = {
        str(element_id): str(group_id)
        for element_id, group_id in (match_payload.get("forced_element_owners") or {}).items()
        if str(element_id) and str(group_id)
    }
    anchors: dict[str, dict[str, float]] = {}
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
        anchors[str(item.get("group_id") or "")] = {
            "x": ax1,
            "y": ay1,
            "w": max(1.0, ax2 - ax1),
            "h": max(1.0, ay2 - ay1),
            "absorb_padding": absorb_padding,
            "dominant_area": float(dominant_area),
        }

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

    for item in accepted:
        seed_ids = [str(element_id) for element_id in item.get("element_ids", []) or [] if str(element_id) in by_id]
        existing_seed_ids = item.get("seed_element_ids", []) or []
        item["seed_element_ids"] = list(dict.fromkeys([*existing_seed_ids, *seed_ids]))
        item["element_ids"] = list(dict.fromkeys(seed_ids))
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
                dist = box_to_box_distance(anchor, bounds)
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
                ranked.append((0 if compatible else 1, anchor_distance(element, anchor), item))
            if not ranked:
                continue
            compatibility_rank, distance, owner = min(
                ranked,
                key=lambda value: (value[0], value[1], str(value[2].get("group_id") or "")),
            )
            owner.setdefault("element_ids", []).append(element_id)
            if element_id in residual_ids:
                owner.setdefault("residual_element_ids", []).append(element_id)
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
        check = {
            "group_id": group_id,
            "element_count": len(element_ids),
            "residual_count": len(residual_ids),
            "residual_ratio": round(residual_ratio, 3),
            "regions": regions,
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
    semantic_quality = {
        "version": "ai_mask_semantic_quality_v2",
        "passed": bool(accepted) and not blocking_errors,
        "group_checks": semantic_group_checks,
        "warnings": semantic_warnings,
        "blocking_errors": blocking_errors,
        "residual_assignment_summary": {
            "assigned": sum(1 for item in residual_assignment_report if item.get("status") == "assigned"),
            "unassigned": sum(1 for item in residual_assignment_report if item.get("status") == "unassigned"),
        },
    }
    quality = {
        "version": "ai_mask_quality_v2",
        "foreground_pixel_count": foreground_pixels,
        "assigned_foreground_pixel_count": assigned_pixels,
        "static_header_pixel_count": _rle_pixel_count(_merge_row_runs(static_elements, width, height)),
        "foreground_coverage_ratio": round(coverage, 6),
        "unassigned_component_count": len(unassigned_ids),
        "overlap_pixel_count": overlap_pixels,
        "exclusive_component_ownership": overlap_pixels == 0,
        "semantic_quality_passed": semantic_quality["passed"],
        "minimum_foreground_coverage_ratio": AI_MASK_MIN_FOREGROUND_COVERAGE,
        "passed": (
            bool(accepted)
            and coverage >= AI_MASK_MIN_FOREGROUND_COVERAGE
            and len(unassigned_ids) == 0
            and overlap_pixels == 0
            and semantic_quality["passed"]
        ),
    }
    match_payload["unmatched_elements"] = unassigned_ids
    match_payload["quality"] = quality
    match_payload["semantic_quality"] = semantic_quality
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


