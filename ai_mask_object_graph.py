"""Layout boxes as candidates: order-independent binding of atomic components.

A DocLayout box is a *region hypothesis* from a document model, not a
segmentation answer.  This module therefore never consumes a component for the
first box that happens to be iterated: every atomic component scores all boxes,
the most specific eligible box wins, and near-ties are recorded instead of
silently resolved.  Geometry only, no numpy and no pixel buffers, so it stays
unit-testable with hand-written run lists.
"""

from __future__ import annotations

from typing import Any


# Initial weights, fixed before any measured arm was scored; ablate them with a
# settings override on the development bundle, never per page on the test set.
BINDING_WEIGHTS: dict[str, float] = {
    "ink_overlap": 0.55,
    "confidence": 0.15,
    "outside_ink": 0.10,
}
# Penalty per box nested inside a candidate: the container is the least specific
# owner of ink that a child box also claims.
BINDING_NESTING_PENALTY = 0.25
# A box must hold at least this share of an atom's ink to own it.
BINDING_MIN_INK_FRACTION = 0.5
# Two eligible boxes within this score margin are an ambiguous binding.
BINDING_AMBIGUOUS_MARGIN = 0.05
# Fraction of a smaller box's area inside a larger one that makes it a child.
BOX_NESTING_RATIO = 0.9
# How many scored candidates are kept per atom for the review trail.
BINDING_CANDIDATE_REPORT = 3


def _box_geometry(box_info: dict[str, Any]) -> dict[str, float]:
    box = box_info.get("box") if isinstance(box_info.get("box"), dict) else {}
    x = float(box.get("x", 0) or 0)
    y = float(box.get("y", 0) or 0)
    w = max(0.0, float(box.get("w", 0) or 0))
    h = max(0.0, float(box.get("h", 0) or 0))
    return {"x": x, "y": y, "w": w, "h": h, "x2": x + w, "y2": y + h, "area": w * h}


def _count_runs_in_box(runs: list[Any], geometry: dict[str, float]) -> int:
    """Pixels of row runs that fall inside the box, clipped on both axes."""
    total = 0
    for run in runs or []:
        if not isinstance(run, list) or len(run) < 3:
            continue
        y, x1, x2 = int(run[0]), int(run[1]), int(run[2])
        if x2 <= x1 or y < geometry["y"] or y >= geometry["y2"]:
            continue
        left = max(x1, geometry["x"])
        right = min(x2, geometry["x2"])
        if right > left:
            total += right - left
    return total


def _ink_fraction(atom: dict[str, Any], geometry: dict[str, float]) -> float:
    rle = atom.get("source_ink_rle") or atom.get("mask_rle") or {}
    runs = rle.get("runs", []) if isinstance(rle, dict) else []
    total = int(atom.get("source_ink_pixel_count") or atom.get("area") or 0)
    if total <= 0:
        return 0.0
    return _count_runs_in_box(runs, geometry) / total


def _nested_ratio(child: dict[str, float], parent: dict[str, float]) -> float:
    """Share of the child box that sits inside the parent box."""
    if child["area"] <= 0:
        return 0.0
    width = min(child["x2"], parent["x2"]) - max(child["x"], parent["x"])
    height = min(child["y2"], parent["y2"]) - max(child["y"], parent["y"])
    if width <= 0 or height <= 0:
        return 0.0
    return (width * height) / child["area"]


def canonicalize_boxes(layout_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort and de-duplicate boxes by content, so input order cannot matter.

    The stable key is derived from geometry, role and confidence only: never the
    position of a box in the model output, which is what made the previous
    binding order-dependent.
    """
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for box_info in layout_boxes or []:
        if not isinstance(box_info, dict):
            continue
        geometry = _box_geometry(box_info)
        if geometry["area"] <= 0:
            continue
        key = (
            round(geometry["x"], 1),
            round(geometry["y"], 1),
            round(geometry["w"], 1),
            round(geometry["h"], 1),
            str(box_info.get("role") or ""),
            round(float(box_info.get("confidence", 0) or 0), 4),
        )
        seen.setdefault(key, {
            "geometry": geometry,
            "role": str(box_info.get("role") or "text"),
            "confidence": float(box_info.get("confidence", 0) or 0),
            "class_id": int(box_info.get("class_id", -1) or -1),
            "key": key,
        })
    boxes = list(seen.values())
    boxes.sort(key=lambda box: (
        box["geometry"]["area"],
        box["geometry"]["y"],
        box["geometry"]["x"],
        box["key"][4],
    ))
    for index, box in enumerate(boxes):
        box["index"] = index
    return boxes


def _nested_child_counts(boxes: list[dict[str, Any]]) -> dict[int, int]:
    """Count the boxes nested inside each candidate container."""
    counts: dict[int, int] = {}
    for outer in boxes:
        counts[outer["index"]] = sum(
            1
            for box in boxes
            if box["index"] != outer["index"]
            and box["geometry"]["area"] < outer["geometry"]["area"]
            and _nested_ratio(box["geometry"], outer["geometry"]) >= BOX_NESTING_RATIO
        )
    return counts


def _score(
    ink_fraction: float,
    confidence: float,
    nested_children: int,
    weights: dict[str, float],
) -> float:
    return (
        weights["ink_overlap"] * ink_fraction
        + weights["confidence"] * confidence
        - weights["outside_ink"] * (1.0 - ink_fraction)
        - BINDING_NESTING_PENALTY * nested_children
    )


def bind_atoms_to_boxes(
    atoms: list[dict[str, Any]],
    layout_boxes: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assign every atomic component to its most specific eligible box.

    Returns ``assignments`` (atom id -> box index or ``None``), ``groups`` (one
    entry per box that won at least one atom, in canonical box order) and the
    atoms no box may own.  Atoms of the same detection group are never split by
    traversal order: a container box loses ink that a nested box also claims.
    """
    settings = settings or {}
    weights = {**BINDING_WEIGHTS, **(settings.get("layout_binding_weights") or {})}
    min_fraction = float(
        settings.get("layout_binding_min_ink_fraction", BINDING_MIN_INK_FRACTION)
    )
    boxes = canonicalize_boxes(layout_boxes)
    nested_children = _nested_child_counts(boxes)

    assignments: dict[str, int | None] = {}
    candidates_by_atom: dict[str, list[dict[str, Any]]] = {}
    ambiguous_atom_ids: set[str] = set()

    for atom in atoms:
        atom_id = str(atom.get("element_id") or "")
        if not atom_id:
            continue
        scored: list[dict[str, Any]] = []
        for box in boxes:
            geometry = box["geometry"]
            fraction = _ink_fraction(atom, geometry)
            if fraction <= 0:
                continue
            score = _score(
                fraction,
                box["confidence"],
                nested_children.get(box["index"], 0),
                weights,
            )
            scored.append({
                "box_index": box["index"],
                "role": box["role"],
                "class_id": box["class_id"],
                "confidence": round(box["confidence"], 4),
                "box": {
                    "x": geometry["x"],
                    "y": geometry["y"],
                    "w": geometry["w"],
                    "h": geometry["h"],
                },
                "nested_box_count": nested_children.get(box["index"], 0),
                "ink_fraction": round(fraction, 6),
                "score": round(score, 6),
                "eligible": fraction >= min_fraction,
            })
        scored.sort(key=lambda item: (-item["score"], item["box_index"]))
        candidates_by_atom[atom_id] = scored[:BINDING_CANDIDATE_REPORT]
        eligible = [item for item in scored if item["eligible"]]
        if not eligible:
            assignments[atom_id] = None
            continue
        winner = eligible[0]
        if (
            len(eligible) > 1
            and winner["score"] - eligible[1]["score"] < BINDING_AMBIGUOUS_MARGIN
        ):
            ambiguous_atom_ids.add(atom_id)
        assignments[atom_id] = int(winner["box_index"])

    groups: list[dict[str, Any]] = []
    for box in boxes:
        member_ids = sorted(
            str(atom.get("element_id"))
            for atom in atoms
            if assignments.get(str(atom.get("element_id") or "")) == box["index"]
        )
        if member_ids:
            groups.append({
                "box_index": box["index"],
                "role": box["role"],
                "class_id": box["class_id"],
                "confidence": box["confidence"],
                "box": {
                    "x": box["geometry"]["x"],
                    "y": box["geometry"]["y"],
                    "w": box["geometry"]["w"],
                    "h": box["geometry"]["h"],
                },
                "member_element_ids": member_ids,
                "ambiguous_element_ids": [
                    atom_id for atom_id in member_ids if atom_id in ambiguous_atom_ids
                ],
            })

    unbound = sorted(
        str(atom.get("element_id"))
        for atom in atoms
        if assignments.get(str(atom.get("element_id") or "")) is None
    )
    return {
        "assignments": assignments,
        "groups": groups,
        "unbound_element_ids": unbound,
        "candidates_by_atom": candidates_by_atom,
        "ambiguous_element_ids": sorted(ambiguous_atom_ids),
        "box_count": len(boxes),
        "binding": {
            "method": "layout_binding_v2",
            "weights": weights,
            "min_ink_fraction": min_fraction,
            "ambiguous_margin": BINDING_AMBIGUOUS_MARGIN,
            "nesting_ratio": BOX_NESTING_RATIO,
            "nesting_penalty": BINDING_NESTING_PENALTY,
        },
    }
