"""Semantic-object multimodal matcher for AI Mask annotation."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import ai_mask_engine
from llm_concurrency import governed_llm_request

MAX_IMAGE_WIDTH = 1280


def _box(element: dict[str, Any]) -> dict[str, float] | None:
    source = element.get("raw_bbox") if isinstance(element.get("raw_bbox"), dict) else element.get("bbox")
    if not isinstance(source, dict):
        return None
    try:
        x = float(source.get("x", 0)); y = float(source.get("y", 0))
        w = float(source.get("w", 0)); h = float(source.get("h", 0))
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _cx(box: dict[str, float]) -> float:
    return box["x"] + box["w"] / 2


def _cy(box: dict[str, float]) -> float:
    return box["y"] + box["h"] / 2


def _union(boxes: list[dict[str, float]]) -> dict[str, int]:
    x1 = min(box["x"] for box in boxes); y1 = min(box["y"] for box in boxes)
    x2 = max(box["x"] + box["w"] for box in boxes); y2 = max(box["y"] + box["h"] for box in boxes)
    return {"x": max(0, round(x1)), "y": max(0, round(y1)), "w": max(1, round(x2 - x1)), "h": max(1, round(y2 - y1))}


def _inside(parent: dict[str, float], child: dict[str, float], pad: float) -> bool:
    cx, cy = _cx(child), _cy(child)
    return parent["x"] - pad <= cx <= parent["x"] + parent["w"] + pad and parent["y"] - pad <= cy <= parent["y"] + parent["h"] + pad


def _position(cx: float, cy: float, width: int, height: int) -> str:
    xp = "left" if cx < width / 3 else "right" if cx > width * 2 / 3 else "center"
    yp = "top" if cy < height / 3 else "bottom" if cy > height * 2 / 3 else "middle"
    return f"{yp}_{xp}"


def _semantic_objects(elements: list[dict[str, Any]], width: int, height: int) -> list[dict[str, Any]]:
    items = []
    for element in elements:
        eid = str(element.get("element_id") or "") if isinstance(element, dict) else ""
        box = _box(element) if isinstance(element, dict) else None
        if eid and box:
            items.append({"id": eid, "element": element, "box": box, "area": float(element.get("area", 0) or 0)})
    canvas_area = max(1, width * height)
    objects: list[dict[str, Any]] = []

    def add(kind: str, ids: list[str], reason: str) -> None:
        unique = [eid for eid in dict.fromkeys(ids) if any(item["id"] == eid for item in items)]
        if not unique:
            return
        boxes = [item["box"] for item in items if item["id"] in unique]
        box = _union(boxes)
        cx = box["x"] + box["w"] / 2; cy = box["y"] + box["h"] / 2
        objects.append({
            "object_id": f"obj_{len(objects) + 1:03d}",
            "type": kind,
            "bbox": box,
            "center": {"x": round(cx, 2), "y": round(cy, 2)},
            "position": _position(cx, cy, width, height),
            "element_ids": unique,
            "element_count": len(unique),
            "reason": reason,
        })

    def is_island(item: dict[str, Any]) -> bool:
        box = item["box"]
        box_area = max(1.0, box["w"] * box["h"])
        return (box_area >= canvas_area * 0.018 or item["area"] >= canvas_area * 0.006) and (
            box["w"] >= width * 0.15 or box["h"] >= height * 0.12
        )

    # A row of same-height visual islands (grid cards) must not merge into one
    # rank-0 text line: that would strand every card after the first under a
    # single narrated group. Only sub-island fragments read as glyphs.
    text_items = [
        item for item in items
        if 5 <= item["box"]["h"] <= max(120, height * 0.14)
        and item["area"] <= canvas_area * 0.06
        and item["box"]["w"] <= width * 0.92
        and not is_island(item)
    ]
    text_items.sort(key=lambda item: (_cy(item["box"]), _cx(item["box"])))
    lines: list[list[dict[str, Any]]] = []
    for item in text_items:
        chosen = None
        for line in lines:
            line_box = _union([part["box"] for part in line])
            line_box_f = {key: float(value) for key, value in line_box.items()}
            last = sorted(line, key=lambda part: _cx(part["box"]))[-1]
            x_gap = max(0.0, item["box"]["x"] - (last["box"]["x"] + last["box"]["w"]))
            y_delta = abs(_cy(item["box"]) - _cy(line_box_f))
            allowed_gap = max(18.0, min(96.0, 1.9 * max(item["box"]["h"], line_box_f["h"])))
            if y_delta <= 0.55 * max(item["box"]["h"], line_box_f["h"]) and x_gap <= allowed_gap:
                chosen = line
                break
        if chosen is None:
            lines.append([item])
        else:
            chosen.append(item)
    for line in lines:
        if len(line) >= 2:
            box = _union([part["box"] for part in line])
            if box["w"] >= box["h"] * 1.2:
                add("text_line_or_label", [part["id"] for part in line], "merged disconnected glyph/label components")

    for item in sorted(items, key=lambda part: part["area"], reverse=True):
        box = item["box"]
        if not is_island(item):
            continue
        pad = max(24.0, min(96.0, 0.09 * max(box["w"], box["h"])))
        child_ids = [part["id"] for part in items if _inside(box, part["box"], pad)]
        add("container_or_illustration", child_ids or [item["id"]], "large visual island with inside/nearby components")

    covered = {eid for obj in objects for eid in obj.get("element_ids", [])}
    for item in items:
        if item["id"] not in covered:
            add("atomic_visual_component", [item["id"]], "single remaining component")

    def priority(obj: dict[str, Any]) -> tuple[int, int, int, int]:
        box = obj.get("bbox", {}) if isinstance(obj.get("bbox"), dict) else {}
        y = int(box.get("y", 0) or 0)
        x = int(box.get("x", 0) or 0)
        kind = str(obj.get("type") or "")
        if y < height * 0.22 and kind == "text_line_or_label":
            rank = 0
        elif kind == "container_or_illustration":
            rank = 1
        elif kind == "text_line_or_label":
            rank = 2
        else:
            rank = 3
        return (rank, y, x, -int(obj.get("element_count", 1) or 1))

    canonical: list[dict[str, Any]] = []
    owned: set[str] = set()
    for obj in sorted(objects, key=priority):
        ids = [str(eid) for eid in obj.get("element_ids", []) or [] if str(eid) and str(eid) not in owned]
        if not ids:
            continue
        next_obj = dict(obj)
        boxes = [item["box"] for item in items if item["id"] in ids]
        if boxes:
            box = _union(boxes)
            cx = box["x"] + box["w"] / 2; cy = box["y"] + box["h"] / 2
            next_obj["bbox"] = box
            next_obj["center"] = {"x": round(cx, 2), "y": round(cy, 2)}
            next_obj["position"] = _position(cx, cy, width, height)
        next_obj["element_ids"] = ids
        next_obj["element_count"] = len(ids)
        next_obj["exclusive"] = True
        canonical.append(next_obj)
        owned.update(ids)

    canonical.sort(key=lambda obj: (obj["bbox"]["y"], obj["bbox"]["x"], -int(obj.get("element_count", 1))))
    # Every atomic object keeps a stable ID: dropping the tail here used to make
    # the objects beyond the cap invisible to the model *and* to the coverage
    # gate, so a dense slide silently lost components.
    for index, obj in enumerate(canonical, start=1):
        obj["object_id"] = f"obj_{index:03d}"
    return canonical


def _png_bytes(image_path: Path, out_path: Path | None = None) -> bytes:
    image = Image.open(image_path).convert("RGB")
    if image.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / image.width
        image = image.resize((MAX_IMAGE_WIDTH, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path, format="PNG")
    buffer = io.BytesIO(); image.save(buffer, format="PNG")
    return buffer.getvalue()


def _expand_matches(value: Any, objects: list[dict[str, Any]], elements: list[dict[str, Any]]) -> Any:
    if not isinstance(value, dict):
        return value
    object_map = {str(obj.get("object_id") or ""): [str(eid) for eid in obj.get("element_ids", []) or []] for obj in objects}
    known = {str(element.get("element_id") or "") for element in elements if str(element.get("element_id") or "")}
    # Also include element_ids from objects so absorbed residual fragments
    # (which are not in the candidates list) are not filtered out.
    for obj in objects:
        known.update(str(eid) for eid in obj.get("element_ids", []) or [])
    matches = []
    for match in value.get("matches", []) or []:
        if not isinstance(match, dict):
            continue
        ids: list[str] = []
        valid_object_ids = []
        for object_id in match.get("object_ids", []) or []:
            object_id = str(object_id)
            if object_id in object_map:
                valid_object_ids.append(object_id)
                ids.extend(object_map[object_id])
        for element_id in match.get("element_ids", []) or []:
            if str(element_id) in known:
                ids.append(str(element_id))
        normalized = dict(match)
        normalized["object_ids"] = valid_object_ids
        normalized["expanded_from_object_ids"] = valid_object_ids
        normalized["element_ids"] = [element_id for element_id in dict.fromkeys(ids) if element_id in known]
        matches.append(normalized)
    result = dict(value)
    result["matches"] = matches
    return result


def _obj_bounds_xyxy(obj: dict[str, Any]) -> tuple[float, float, float, float] | None:
    box = obj.get("bbox") if isinstance(obj.get("bbox"), dict) else None
    if not box:
        return None
    try:
        x1 = float(box.get("x", 0)); y1 = float(box.get("y", 0))
        return x1, y1, x1 + float(box.get("w", 0)), y1 + float(box.get("h", 0))
    except (TypeError, ValueError):
        return None


def _elem_bounds_xyxy(elem: dict[str, Any]) -> tuple[float, float, float, float] | None:
    source = elem.get("raw_bbox") if isinstance(elem.get("raw_bbox"), dict) else elem.get("bbox")
    if not isinstance(source, dict):
        return None
    try:
        x1 = float(source.get("x", 0)); y1 = float(source.get("y", 0))
        return x1, y1, x1 + float(source.get("w", 0)), y1 + float(source.get("h", 0))
    except (TypeError, ValueError):
        return None


def _box_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Shortest gap between two axis-aligned rectangles (0 if overlapping)."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    dx = max(ax1 - bx2, 0.0, bx1 - ax2)
    dy = max(ay1 - by2, 0.0, by1 - ay2)
    return float((dx * dx + dy * dy) ** 0.5)


def _union_bounds_list(bounds_list: list[tuple[float, float, float, float]]) -> dict[str, int]:
    x1 = min(b[0] for b in bounds_list); y1 = min(b[1] for b in bounds_list)
    x2 = max(b[2] for b in bounds_list); y2 = max(b[3] for b in bounds_list)
    return {"x": max(0, round(x1)), "y": max(0, round(y1)), "w": max(1, round(x2 - x1)), "h": max(1, round(y2 - y1))}


def _absorb_residuals_into_objects(
    objects: list[dict[str, Any]],
    residual: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Absorb residual fragments into the nearest semantic_object by box-to-box distance.

    Each residual element is assigned to its single nearest object (no 1.5x
    ambiguity gate - we want every fragment absorbed before VL sees the crops).
    Object bbox and element_ids are updated to include absorbed fragments.
    """
    if not objects or not residual:
        return objects
    obj_bounds = []
    for obj in objects:
        bounds = _obj_bounds_xyxy(obj)
        obj_bounds.append(bounds if bounds else (0.0, 0.0, 0.0, 0.0))
    elem_map: dict[str, dict[str, Any]] = {}
    for elem in residual:
        eid = str(elem.get("element_id") or "")
        if eid:
            elem_map[eid] = elem
        eb = _elem_bounds_xyxy(elem)
        if not eb:
            continue
        best_idx = -1
        best_dist = float("inf")
        for idx, ob in enumerate(obj_bounds):
            d = _box_gap(ob, eb)
            if d < best_dist:
                best_dist = d
                best_idx = idx
        if best_idx < 0:
            continue
        obj = objects[best_idx]
        existing = list(obj.get("element_ids", []) or [])
        if eid not in existing:
            existing.append(eid)
            obj["element_ids"] = existing
            obj["element_count"] = len(existing)
            obj.setdefault("absorbed_residual_ids", []).append(eid)
    # Recompute bbox for objects that absorbed fragments
    for obj in objects:
        absorbed = obj.get("absorbed_residual_ids", [])
        if not absorbed:
            continue
        all_bounds = []
        ob = _obj_bounds_xyxy(obj)
        if ob:
            all_bounds.append(ob)
        for eid in absorbed:
            elem = elem_map.get(eid)
            if elem:
                eb = _elem_bounds_xyxy(elem)
                if eb:
                    all_bounds.append(eb)
        if len(all_bounds) > 1:
            obj["bbox"] = _union_bounds_list(all_bounds)
    return objects


def _plan_atomic_requests(
    objects: list[dict[str, Any]],
    settings: dict[str, Any],
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]], int]:
    """Plan VL batches under the request budget, growing instead of dropping.

    The Stage-C blind-verified invariant: every atomic object must reach the
    model. When the configured budget cannot cover all objects at the default
    batch size, the batch size grows so the remainder still fits inside
    ``vision_max_requests``; objects are never silently left to the
    deterministic fallback while the model still has request budget spare.
    """
    batch_size, max_requests = _batch_budget(settings)
    if not objects or -(-len(objects) // batch_size) <= max_requests:
        batches, beyond = _plan_object_batches(objects, settings)
        return batches, beyond, 0
    expanded_size = -(-len(objects) // max_requests)
    grown = dict(settings)
    grown["vision_object_batch_size"] = expanded_size
    batches, beyond = _plan_object_batches(objects, grown)
    return batches, beyond, expanded_size


def _spatial_cluster_objects(
    objects: list[dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]]:
    """Cluster spatially-adjacent semantic_objects into ~target_count groups.

    Uses agglomerative merging by nearest box-to-box distance. Each cluster
    becomes one composite object whose bbox is the union of its members. This
    is only the rollback path (``atomic_object_matching=false``); the atomic
    default keeps every object addressable.
    """
    if len(objects) <= target_count or target_count < 1:
        return objects
    clusters: list[list[dict[str, Any]]] = [[obj] for obj in objects]
    cluster_bounds: list[tuple[float, float, float, float]] = []
    for cluster in clusters:
        bounds_list = [_obj_bounds_xyxy(obj) for obj in cluster]
        bounds_list = [b for b in bounds_list if b]
        if bounds_list:
            x1 = min(b[0] for b in bounds_list); y1 = min(b[1] for b in bounds_list)
            x2 = max(b[2] for b in bounds_list); y2 = max(b[3] for b in bounds_list)
            cluster_bounds.append((x1, y1, x2, y2))
        else:
            cluster_bounds.append((0.0, 0.0, 0.0, 0.0))

    while len(clusters) > target_count:
        best_i = -1
        best_j = -1
        best_dist = float("inf")
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = _box_gap(cluster_bounds[i], cluster_bounds[j])
                if d < best_dist:
                    best_dist = d
                    best_i = i
                    best_j = j
        if best_i < 0:
            break
        merged_bounds_list = [cluster_bounds[best_i], cluster_bounds[best_j]]
        x1 = min(b[0] for b in merged_bounds_list); y1 = min(b[1] for b in merged_bounds_list)
        x2 = max(b[2] for b in merged_bounds_list); y2 = max(b[3] for b in merged_bounds_list)
        clusters[best_i] = clusters[best_i] + clusters[best_j]
        cluster_bounds[best_i] = (x1, y1, x2, y2)
        clusters.pop(best_j)
        cluster_bounds.pop(best_j)

    result: list[dict[str, Any]] = []
    for idx, cluster in enumerate(clusters):
        if len(cluster) == 1:
            obj = dict(cluster[0])
            obj["object_id"] = f"obj_{idx + 1:03d}"
            obj["cluster_member_count"] = 1
            result.append(obj)
            continue
        all_eids: list[str] = []
        for member in cluster:
            all_eids.extend(str(eid) for eid in member.get("element_ids", []) or [])
        unique_eids = list(dict.fromkeys(all_eids))
        bounds_list = [_obj_bounds_xyxy(obj) for obj in cluster]
        bounds_list = [b for b in bounds_list if b]
        bbox = _union_bounds_list(bounds_list) if bounds_list else {"x": 0, "y": 0, "w": 1, "h": 1}
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        result.append({
            "object_id": f"obj_{idx + 1:03d}",
            "type": "spatial_cluster",
            "bbox": bbox,
            "center": {"x": round(cx, 2), "y": round(cy, 2)},
            "element_ids": unique_eids,
            "element_count": len(unique_eids),
            "cluster_member_count": len(cluster),
            "member_object_ids": [str(m.get("object_id") or "") for m in cluster],
            "reason": f"spatial cluster of {len(cluster)} adjacent objects",
            "exclusive": True,
        })
    return result


DEFAULT_OBJECT_BATCH_SIZE = 12
DEFAULT_MAX_VISION_REQUESTS = 4


def _batch_budget(settings: dict[str, Any]) -> tuple[int, int]:
    def positive_int(key: str, default: int) -> int:
        try:
            value = int(settings.get(key, default) or default)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    return positive_int("vision_object_batch_size", DEFAULT_OBJECT_BATCH_SIZE), positive_int(
        "vision_max_requests", DEFAULT_MAX_VISION_REQUESTS
    )


def _plan_object_batches(
    objects: list[dict[str, Any]],
    settings: dict[str, Any],
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    """Split atomic objects into budgeted requests instead of merging them away.

    Objects the budget cannot cover are returned as the remainder: they stay
    visible to the deterministic fallback and the review gate, which is the
    honest alternative to forcing them into an unrelated cluster.
    """
    batch_size, max_requests = _batch_budget(settings)
    covered = batch_size * max_requests
    sent = objects[:covered]
    batches = [sent[start : start + batch_size] for start in range(0, len(sent), batch_size)]
    return batches, objects[covered:]


def _match_confidence(match: dict[str, Any]) -> float:
    try:
        return float(match.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _merge_batch_results(
    batch_results: list[tuple[int, dict[str, Any]]],
    group_ids: list[str],
    beyond_budget: list[dict[str, Any]] | None = None,
    known_object_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Combine per-batch model answers so every object has exactly one owner.

    A cross-batch conflict must not be decided by arrival order. The strongest
    confidence wins, and ties fall back to the slide's own group order and then
    the batch index, so the merge stays a deterministic function of its inputs.
    IDs the model invented are dropped here rather than reaching the Mask builder.
    """
    group_rank = {gid: index for index, gid in enumerate(group_ids)}
    entries: list[tuple[int, str, dict[str, Any]]] = []
    rejected_group_ids: set[str] = set()
    rejected_object_ids: set[str] = set()
    unmatched_objects: list[str] = []
    unmatched_elements: list[str] = []
    warnings: list[dict[str, Any]] = []
    seen_warnings: set[tuple[Any, ...]] = set()
    slide_id = ""

    def claimed_objects(raw: dict[str, Any]) -> list[str]:
        claimed = []
        for oid in [str(oid) for oid in raw.get("object_ids", []) or [] if str(oid)]:
            if known_object_ids is not None and oid not in known_object_ids:
                rejected_object_ids.add(oid)
                continue
            claimed.append(oid)
        return claimed

    def precedence(batch_index: int, group_id: str, raw: dict[str, Any]) -> tuple[float, int, int]:
        # Higher wins: confidence first, then the slide's own group order, then
        # the earlier batch.  Arrival order alone never decides an owner.
        return (
            _match_confidence(raw),
            -group_rank.get(group_id, len(group_rank)),
            -batch_index,
        )

    for batch_index, value in batch_results:
        if not isinstance(value, dict):
            continue
        slide_id = slide_id or str(value.get("slide_id") or "")
        for raw in value.get("matches", []) or []:
            if not isinstance(raw, dict):
                continue
            group_id = str(raw.get("group_id") or "")
            if not group_id:
                continue
            if group_id not in group_rank:
                rejected_group_ids.add(group_id)
                continue
            entries.append((batch_index, group_id, raw))
        unmatched_objects.extend(
            str(oid) for oid in value.get("unmatched_objects", []) or [] if str(oid)
        )
        unmatched_elements.extend(
            str(eid) for eid in value.get("unmatched_elements", []) or [] if str(eid)
        )
        for warning in value.get("warnings", []) or []:
            if not isinstance(warning, dict):
                continue
            key = (
                str(warning.get("type") or ""),
                str(warning.get("group_id") or ""),
                tuple(sorted(claimed_objects(warning))),
            )
            if key not in seen_warnings:
                seen_warnings.add(key)
                warnings.append(dict(warning))

    owners: dict[str, tuple[tuple[float, int, int], str]] = {}
    for batch_index, group_id, raw in entries:
        rank = precedence(batch_index, group_id, raw)
        for object_id in claimed_objects(raw):
            current = owners.get(object_id)
            if current is None or rank > current[0]:
                owners[object_id] = (rank, group_id)

    conflicts: list[dict[str, Any]] = []
    for object_id in sorted(owners):
        claimants = {
            group_id
            for _, group_id, raw in entries
            if object_id in claimed_objects(raw)
        }
        if len(claimants) > 1:
            conflicts.append({
                "object_id": object_id,
                "kept_group_id": owners[object_id][1],
                "competing_group_ids": sorted(claimants - {owners[object_id][1]}),
                "decided_by": "confidence_then_group_order_then_batch",
            })

    grouped: dict[str, dict[str, Any]] = {}
    for batch_index, group_id, raw in entries:
        match = grouped.get(group_id)
        if match is None:
            match = {
                "group_id": group_id,
                "narration_beat_id": "",
                "object_ids": [],
                "element_ids": [],
                "confidence": 0.0,
                "reason": "",
                "source_batch_index": batch_index,
                "merged_from_batches": [],
                "_precedence": None,
            }
            grouped[group_id] = match
        for object_id in claimed_objects(raw):
            if owners.get(object_id, (None, group_id))[1] != group_id:
                continue
            if object_id not in match["object_ids"]:
                match["object_ids"].append(object_id)
        for element_id in [str(eid) for eid in raw.get("element_ids", []) or [] if str(eid)]:
            if element_id not in match["element_ids"]:
                match["element_ids"].append(element_id)
        if batch_index not in match["merged_from_batches"]:
            match["merged_from_batches"].append(batch_index)
        rank = precedence(batch_index, group_id, raw)
        if match["_precedence"] is None or rank > match["_precedence"]:
            match["_precedence"] = rank
            match["source_batch_index"] = batch_index
            match["narration_beat_id"] = str(raw.get("narration_beat_id") or "")
            match["confidence"] = _match_confidence(raw)
            match["reason"] = str(raw.get("reason") or "")

    matches: list[dict[str, Any]] = []
    for match in grouped.values():
        match.pop("_precedence", None)
        if not match["object_ids"] and not match["element_ids"]:
            continue
        matches.append(match)
    matches.sort(
        key=lambda match: group_rank.get(str(match.get("group_id") or ""), len(group_rank))
    )

    matched_groups = {str(match.get("group_id") or "") for match in matches}
    matched_objects = {oid for match in matches for oid in match["object_ids"]}
    unmatched = [oid for oid in dict.fromkeys(unmatched_objects) if oid not in matched_objects]
    unmatched.extend(
        str(obj.get("object_id") or "")
        for obj in beyond_budget or []
        if str(obj.get("object_id") or "") not in matched_objects
    )
    return {
        "slide_id": slide_id,
        "matches": matches,
        "unmatched_objects": list(dict.fromkeys(unmatched)),
        "unmatched_elements": list(dict.fromkeys(unmatched_elements)),
        "unmatched_groups": [gid for gid in group_ids if gid not in matched_groups],
        "warnings": warnings,
        "vision_batches": {
            "request_count": len(batch_results),
            "matches_per_batch": [
                len(value.get("matches", []) or []) if isinstance(value, dict) else 0
                for _, value in batch_results
            ],
            "ownership_conflicts": conflicts,
            "beyond_budget_object_ids": [
                str(obj.get("object_id") or "") for obj in beyond_budget or []
            ],
            "rejected_group_ids": sorted(rejected_group_ids),
            "rejected_object_ids": sorted(rejected_object_ids),
        },
    }


def _crop_object_bytes(image_path: Path, obj: dict[str, Any], max_width: int = 400) -> bytes | None:
    """Crop a single semantic_object region from the slide image and return PNG bytes.

    Adds a small padding around the bbox and draws the object_id label on top
    so VL can identify which crop is which object.
    """
    box = obj.get("bbox") if isinstance(obj.get("bbox"), dict) else None
    if not box:
        return None
    try:
        image = Image.open(image_path).convert("RGB")
        ow, oh = image.size
        sx = MAX_IMAGE_WIDTH / ow if ow > MAX_IMAGE_WIDTH else 1.0
        if ow > MAX_IMAGE_WIDTH:
            ratio = MAX_IMAGE_WIDTH / ow
            image = image.resize((MAX_IMAGE_WIDTH, max(1, int(oh * ratio))), Image.Resampling.LANCZOS)
        x = int(float(box.get("x", 0)) * sx)
        y = int(float(box.get("y", 0)) * sx)
        w = int(float(box.get("w", 0)) * sx)
        h = int(float(box.get("h", 0)) * sx)
        # Add padding so VL sees context around the element
        pad = max(8, min(20, w // 10))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(image.width, x + w + pad)
        y2 = min(image.height, y + h + pad)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = image.crop((x1, y1, x2, y2))
        # Resize if too wide, but keep aspect ratio
        if crop.width > max_width:
            ratio = max_width / crop.width
            crop = crop.resize((max_width, max(1, int(crop.height * ratio))), Image.Resampling.LANCZOS)
        # Draw object_id label at top-left
        draw = ImageDraw.Draw(crop)
        label = str(obj.get("object_id") or "")
        label_bg = (255, 255, 200)
        label_fg = (180, 30, 50)
        try:
            bbox = draw.textbbox((4, 2), label)
            draw.rectangle(bbox, fill=label_bg)
            draw.text((4, 2), label, fill=label_fg)
        except Exception:
            pass
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def _flag(settings: dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    return value if isinstance(value, bool) else default


ATOMIC_BATCH_INSTRUCTION = (
    "先看完整原图理解全局版式与阅读顺序，再看本批每个 object_XXX 的切片图及其 bbox。"
    "切片图按 semantic_objects 顺序提供，图片上的标签与 object_id 一致。"
    "只对本批列出的 object_id 做归属决定：其余对象由其它批次处理，不要为它们编造归属，"
    "也不要把本批对象因为“主题相近”硬塞进同一个 group。"
    "每个 object 只能属于一个 group，输出 object_ids（element_ids 留空，系统自行展开）。"
)

CLUSTERED_BATCH_INSTRUCTION = (
    "先看完整原图理解全局版式和阅读顺序，再看每个 object_XXX 的切片图及其 bbox 坐标。"
    "根据切片图视觉内容和空间位置（bbox 的 x/y/w/h），选择 object_id 对应到 visual_groups 和 narration_beats。"
    "一个 object 可能包含多个空间相邻的语义元素（cluster_member_count>1），应作为整体归属。输出 object_ids 和 element_ids。"
)


def _batch_payload(
    slide: dict[str, Any],
    batch: list[dict[str, Any]],
    index: int,
    total: int,
    atomic: bool,
) -> dict[str, Any]:
    objects_payload = []
    for obj in batch:
        entry: dict[str, Any] = {
            "object_id": obj.get("object_id"),
            "type": obj.get("type"),
            "element_count": obj.get("element_count"),
            "bbox": obj.get("bbox", {}),
            "center": obj.get("center", {}),
        }
        if not atomic:
            entry["cluster_member_count"] = obj.get("cluster_member_count", 1)
        objects_payload.append(entry)
    payload: dict[str, Any] = {
        "slide": {
            key: slide.get(key)
            for key in (
                "slide_id", "main_title", "subtitle", "core_message", "body_content",
                "visual_groups", "narration_beats",
            )
        },
        "semantic_objects": objects_payload,
        "instruction": ATOMIC_BATCH_INSTRUCTION if atomic else CLUSTERED_BATCH_INSTRUCTION,
    }
    if total > 1:
        # The model only needs to know the scope is partial when it really is.
        payload["batch"] = {"index": index + 1, "total": total}
    return payload


def _request_object_batch(
    capabilities: Any,
    base_module: Any,
    client: Any,
    *,
    model: str,
    settings: dict[str, Any],
    vendor_options: dict[str, Any],
    prompt: str,
    clean_bytes: bytes,
    image_path: Path,
    slide: dict[str, Any],
    batch: list[dict[str, Any]],
    index: int,
    total: int,
    atomic: bool,
    base_url: str = "",
) -> dict[str, Any]:
    payload = _batch_payload(slide, batch, index, total, atomic)
    user_content: list[dict[str, Any]] = [
        {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)},
        {"type": "text", "text": "完整原图（image_full）：理解全局版式和阅读顺序。"},
        {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(clean_bytes).decode("ascii")
        }},
    ]
    for obj in batch:
        crop_bytes = _crop_object_bytes(image_path, obj)
        if not crop_bytes:
            continue
        user_content.append({
            "type": "text",
            "text": f"{obj.get('object_id')}（类型:{obj.get('type')}）：此对象的切片图。",
        })
        user_content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(crop_bytes).decode("ascii")},
        })
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]
    # One match record per object plus Chinese reasons can exceed the legacy
    # flat 12000 budget on dense batches and truncate mid-string.
    max_tokens = min(24000, 12000 + 600 * len(batch))
    try:
        # 每次 VL 请求都是一次真实上游调用：逐请求申请项目槽 + 网关全局额度，
        # 结束即释放；额度排队超时按 GovernorTimeout 上抛，由调用方明确标记。
        with governed_llm_request(base_url):
            response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=max_tokens, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, response_format={"type": "json_object"}, messages=messages, **vendor_options)
    except Exception as exc:
        import generation_governor
        if isinstance(exc, generation_governor.GovernorTimeout) or base_module._is_timeout(capabilities, exc):
            raise
        # 只有明确的格式不兼容才去掉 response_format 重试；限流/认证/超时
        # 原样上抛，避免把额度问题伪装成参数问题多打一次请求。
        from llm_concurrency import is_llm_format_incompatibility
        if not is_llm_format_incompatibility(exc):
            raise
        with governed_llm_request(base_url):
            response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=max_tokens, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, messages=messages, **vendor_options)
    content = str(response.choices[0].message.content or "").strip()
    cleaned = capabilities.clean_json_markdown(content)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        # A truncated or malformed completion is usually transient; one fresh
        # retry recovers the batch without degrading to the deterministic prior.
        with governed_llm_request(base_url):
            response = client.chat.completions.create(model=model, temperature=float(settings["llm_temperature"]), max_tokens=max_tokens, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, messages=messages, **vendor_options)
        content = str(response.choices[0].message.content or "").strip()
        cleaned = capabilities.clean_json_markdown(content)
        value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError(f"AI Mask vision batch {index + 1}/{total} returned a non-object JSON body")
    return value


class SemanticVisionMatcher:
    """Match detected slide components to narrated groups by semantic object."""

    def __call__(
        self,
        capabilities: Any,
        project: Any,
        slide: dict[str, Any],
        elements: list[dict[str, Any]],
        image_path: Path,
        overlay_path: Path,
        methodology: str,
        output_structure: str,
        settings: dict[str, Any],
    ) -> dict[str, Any] | None:
        base_module = ai_mask_engine
        api_key = capabilities.get_setting("llm_api_key")
        if not api_key:
            return None
        with Image.open(image_path) as image:
            width, height = image.size
        objects = _semantic_objects(elements, width, height)
        # Read residual fragments from auto_elements.json so we can absorb them
        # into semantic_objects BEFORE VL sees the crops.  This ensures VL
        # gets complete object crops that include nearby stray fragments.
        residual_elements: list[dict[str, Any]] = []
        try:
            ae_path = overlay_path.parent / "auto_elements.json"
            if ae_path.exists():
                ae_data = json.loads(ae_path.read_text(encoding="utf-8"))
                residual_elements = list(ae_data.get("residual_elements", []) or [])
        except Exception:
            pass
        objects = _absorb_residuals_into_objects(objects, residual_elements)
        # The pre-v4 strategy merged objects down to (beats + 3) spatial clusters
        # so a slide always fitted in one request. That made it impossible for a
        # slide with more narrated groups than clusters to give each group its own
        # candidate, and it threw away the atomic ownership evidence.
        atomic_matching = _flag(settings, "atomic_object_matching", True)
        beat_count = len(slide.get("narration_beats", []) or [])
        target_count = max(1, min(12, beat_count + 3))
        pre_cluster_count = len(objects)
        batch_size_expanded_to = 0
        if atomic_matching:
            batches, beyond_budget, batch_size_expanded_to = _plan_atomic_requests(objects, settings)
        else:
            objects = _spatial_cluster_objects(objects, target_count)
            batches, beyond_budget = [objects], []
        group_ids = [
            str(group.get("id") or "")
            for group in slide.get("visual_groups", []) or []
            if isinstance(group, dict) and str(group.get("id") or "")
        ]
        model, _ = base_module._resolved_vision_model(capabilities)
        prompt = methodology.strip() + "\n\n--- OUTPUT STRUCTURE / 输出结构 ---\n" + output_structure.strip()
        try:
            base_module._write_json(overlay_path.parent / "semantic_objects.json", {
                "version": "semantic_objects_v3_atomic" if atomic_matching else "semantic_objects_v2_clustered",
                "slide_id": slide.get("slide_id"),
                "canvas": {"width": width, "height": height},
                "objects": objects,
                "source_auto_element_count": len(elements),
                "residual_absorbed_count": len(residual_elements),
                "pre_cluster_object_count": pre_cluster_count,
                "target_cluster_count": target_count,
                "batch_size_expanded_to": batch_size_expanded_to,
                "request_batches": [
                    {"index": index, "total": len(batches), "object_ids": [
                        str(obj.get("object_id") or "") for obj in batch
                    ]}
                    for index, batch in enumerate(batches, start=1)
                ],
                "beyond_budget_object_ids": [
                    str(obj.get("object_id") or "") for obj in beyond_budget
                ],
                "vision_model": model,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            })
        except Exception:
            pass
        if not batches:
            return None
        clean_bytes = _png_bytes(image_path, overlay_path.with_name("clean_original_for_vision.png"))
        base_url = capabilities.get_setting("llm_base_url")
        vendor_options = capabilities.step2_llm_vendor_options(model, base_url) or {}
        client = capabilities.get_openai_client(api_key=api_key, base_url=base_url, timeout=base_module.AI_MASK_VISION_TIMEOUT_SEC, max_retries=0)
        # VL sees the full page once per request plus this batch's crops, so the
        # number of requests and images stays inside the configured budget while
        # every atomic object keeps its own identity.
        batch_results: list[tuple[int, dict[str, Any]]] = []
        failed_batches: list[int] = []
        first_error: Exception | None = None
        try:
            for index, batch in enumerate(batches):
                try:
                    value = _request_object_batch(
                        capabilities,
                        base_module,
                        client,
                        model=model,
                        settings=settings,
                        vendor_options=vendor_options,
                        prompt=prompt,
                        clean_bytes=clean_bytes,
                        image_path=image_path,
                        slide=slide,
                        batch=batch,
                        index=index,
                        total=len(batches),
                        atomic=atomic_matching,
                        base_url=str(base_url or ""),
                    )
                except Exception as exc:
                    # A timeout or the first batch failing means the whole slide
                    # has no usable multimodal evidence; the engine then applies
                    # its deterministic prior instead of a half-populated merge.
                    if index == 0 or base_module._is_timeout(capabilities, exc):
                        raise
                    first_error = exc
                    failed_batches.append(index)
                    continue
                batch_results.append((index, value))
        finally:
            try:
                client.close()
            except Exception:
                pass
        if not batch_results:
            return None
        merged = _merge_batch_results(
            batch_results,
            group_ids,
            beyond_budget,
            # Only the objects the model was actually shown may be claimed; a
            # beyond-budget object id in a match is a hallucination by definition.
            {str(obj.get("object_id") or "") for batch in batches for obj in batch},
        )
        # Budget accounting counts what was sent upstream, not what came back.
        merged["vision_batches"]["request_count"] = len(batches)
        merged["vision_batches"]["object_count"] = sum(len(batch) for batch in batches)
        merged["vision_batches"]["batch_size_expanded_to"] = batch_size_expanded_to
        if failed_batches:
            merged["vision_batches"]["failed_batch_indices"] = failed_batches
            merged["vision_batches"]["failed_batch_error_type"] = type(first_error).__name__
        return _expand_matches(merged, objects, elements)


semantic_vision_matcher = SemanticVisionMatcher()
