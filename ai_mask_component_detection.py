"""Deterministic foreground component detection and exact RLE utilities."""

from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import numpy as np
from PIL import Image

from ai_mask_contracts import (
    LAYOUT_STATUS_DISABLED,
    LAYOUT_STATUS_NO_BOXES,
    LAYOUT_STATUS_OK,
    elapsed_ms as _elapsed_ms,
)
from ai_mask_object_graph import bind_atoms_to_boxes


# Detection cache identity.  ``v4`` separates raw ink from the morphological
# grouping assumption, so a v3 cache must never be reused for a v4 result.
AUTO_ELEMENTS_VERSION = "auto_elements_v4_ink_separated"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Missing JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON must be object: {path}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use open() with mode="w" to reliably overwrite existing files on Windows.
    # pathlib.write_text can raise FileExistsError when the file is read-only
    # or held by another process.
    if path.exists():
        try:
            path.chmod(0o666)
        except (OSError, PermissionError):
            pass
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _neighbors(connectivity: int) -> tuple[tuple[int, int], ...]:
    base = ((1, 0), (-1, 0), (0, 1), (0, -1))
    return base if connectivity == 4 else base + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _pad_box(box: dict[str, int], width: int, height: int, padding: int) -> dict[str, int]:
    x1 = max(0, box["x"] - padding)
    y1 = max(0, box["y"] - padding)
    x2 = min(width, box["x"] + box["w"] + padding)
    y2 = min(height, box["y"] + box["h"] + padding)
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}


def _position(cx: float, cy: float, width: int, height: int) -> str:
    xp = "left" if cx < width / 3 else "right" if cx > width * 2 / 3 else "center"
    yp = "top" if cy < height / 3 else "bottom" if cy > height * 2 / 3 else "middle"
    return f"{yp}_{xp}"


def _coords_to_row_runs(
    coords: list[tuple[int, int]],
    border: int,
    width: int,
    height: int,
) -> list[list[int]]:
    """Encode component pixels as compact [y, x_start, x_end) scanline runs."""
    rows: dict[int, list[int]] = {}
    for padded_x, padded_y in coords:
        x = padded_x - border
        y = padded_y - border
        if 0 <= x < width and 0 <= y < height:
            rows.setdefault(y, []).append(x)
    runs: list[list[int]] = []
    for y in sorted(rows):
        xs = sorted(set(rows[y]))
        if not xs:
            continue
        start = previous = xs[0]
        for x in xs[1:]:
            if x != previous + 1:
                runs.append([y, start, previous + 1])
                start = x
            previous = x
        runs.append([y, start, previous + 1])
    return runs


def _merge_row_runs(elements: list[dict[str, Any]], width: int, height: int) -> dict[str, Any]:
    """Union exact component RLE without expanding beyond source pixels."""
    rows: dict[int, list[tuple[int, int]]] = {}
    for element in elements:
        rle = element.get("mask_rle") if isinstance(element.get("mask_rle"), dict) else {}
        for run in rle.get("runs", []) or []:
            if not isinstance(run, list) or len(run) < 3:
                continue
            y, x1, x2 = (int(run[0]), int(run[1]), int(run[2]))
            if 0 <= y < height and x2 > x1:
                rows.setdefault(y, []).append((max(0, x1), min(width, x2)))
    merged: list[list[int]] = []
    for y in sorted(rows):
        intervals = sorted((x1, x2) for x1, x2 in rows[y] if x2 > x1)
        if not intervals:
            continue
        start, end = intervals[0]
        for x1, x2 in intervals[1:]:
            if x1 <= end:
                end = max(end, x2)
            else:
                merged.append([y, start, end])
                start, end = x1, x2
        merged.append([y, start, end])
    return {
        "encoding": "row_runs_v1",
        "width": width,
        "height": height,
        "runs": merged,
    }


def _rle_pixel_count(rle: dict[str, Any]) -> int:
    return sum(
        max(0, int(run[2]) - int(run[1]))
        for run in rle.get("runs", []) or []
        if isinstance(run, list) and len(run) >= 3
    )


def _solidify_planar_component(
    runs: list[list[int]],
    raw_box: dict[str, int],
    source_area: int,
) -> list[list[int]]:
    """Close background leaks inside large card/panel components by scanline.

    Generated slides often use dashed borders and near-white gradients. A
    border flood can enter those panels through a dash gap and punch thousands
    of white pinholes. Large, dense components are therefore filled only
    between their first and last source pixel on each occupied row. Rounded
    outer silhouettes remain intact and small text/illustrations are untouched.
    """
    box_area = max(1, int(raw_box.get("w", 0)) * int(raw_box.get("h", 0)))
    density = source_area / box_area
    if box_area < 40_000 or source_area < 25_000 or density < 0.35:
        return runs
    rows: dict[int, tuple[int, int]] = {}
    for y, x1, x2 in runs:
        if y not in rows:
            rows[y] = (x1, x2)
        else:
            rows[y] = (min(rows[y][0], x1), max(rows[y][1], x2))
    return [[y, x1, x2] for y, (x1, x2) in sorted(rows.items()) if x2 > x1]


def _protect_other_foreground(
    solid_runs: list[list[int]],
    source_runs: list[list[int]],
    source_foreground: np.ndarray,
) -> list[list[int]]:
    """Prevent a filled panel from claiming pixels owned by another component."""
    if solid_runs == source_runs:
        return solid_runs
    own_rows: dict[int, list[tuple[int, int]]] = {}
    for y, x1, x2 in source_runs:
        own_rows.setdefault(y, []).append((x1, x2))
    protected: list[list[int]] = []
    for y, x1, x2 in solid_runs:
        allowed = ~source_foreground[y, x1:x2].copy()
        for own_x1, own_x2 in own_rows.get(y, []):
            left, right = max(x1, own_x1), min(x2, own_x2)
            if right > left:
                allowed[left - x1:right - x1] = True
        indexes = np.flatnonzero(allowed)
        if not len(indexes):
            continue
        start = previous = int(indexes[0])
        for value in indexes[1:]:
            current = int(value)
            if current != previous + 1:
                protected.append([y, x1 + start, x1 + previous + 1])
                start = current
            previous = current
        protected.append([y, x1 + start, x1 + previous + 1])
    return protected


def _rle_bounds(rle: dict[str, Any]) -> dict[str, int] | None:
    runs = rle.get("runs", []) if isinstance(rle, dict) else []
    valid = [run for run in runs if isinstance(run, list) and len(run) >= 3 and int(run[2]) > int(run[1])]
    if not valid:
        return None
    x1 = min(int(run[1]) for run in valid)
    y1 = min(int(run[0]) for run in valid)
    x2 = max(int(run[2]) for run in valid)
    y2 = max(int(run[0]) + 1 for run in valid)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _morph_dilate(mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Binary dilation without scipy/skimage (pure numpy)."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(mask, ((ph, ph), (pw, pw)), mode="constant", constant_values=0)
    result = np.zeros_like(mask)
    for dy in range(kh):
        for dx in range(kw):
            if kernel[dy, dx]:
                result = np.maximum(result, padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]])
    return result


def _morph_erode(mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Binary erosion without scipy/skimage (pure numpy)."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(mask, ((ph, ph), (pw, pw)), mode="constant", constant_values=0)
    result = np.full_like(mask, 255)
    for dy in range(kh):
        for dx in range(kw):
            if kernel[dy, dx]:
                result = np.minimum(result, padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]])
    return result


def _connected_sets(
    coords: list[tuple[int, int]],
    nbrs: tuple[tuple[int, int], ...],
) -> list[list[tuple[int, int]]]:
    """Split one pixel set into its own connected islands, in scan order."""
    pending = set(coords)
    islands: list[list[tuple[int, int]]] = []
    for seed in coords:
        if seed not in pending:
            continue
        pending.discard(seed)
        stack = [seed]
        island = [seed]
        while stack:
            x, y = stack.pop()
            for dx, dy in nbrs:
                neighbour = (x + dx, y + dy)
                if neighbour in pending:
                    pending.discard(neighbour)
                    stack.append(neighbour)
                    island.append(neighbour)
        islands.append(island)
    return islands


def _bbox_of(coords: list[tuple[int, int]], border: int, ow: int, oh: int) -> dict[str, int]:
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    return {
        "x": max(0, x_min - border),
        "y": max(0, y_min - border),
        "w": min(ow, x_max + 1 - x_min),
        "h": min(oh, y_max + 1 - y_min),
    }


def _rle(runs: list[list[int]], ow: int, oh: int) -> dict[str, Any]:
    return {"encoding": "row_runs_v1", "width": ow, "height": oh, "runs": runs}


def _build_atom(
    coords: list[tuple[int, int]],
    border: int,
    ow: int,
    oh: int,
    index: int,
    padding: int,
) -> dict[str, Any]:
    """One connected ink island: the atomic unit a layout box may own.

    An atom carries exact pixels only.  Panel solidification and foreign-pixel
    protection are grouping-level decisions and belong to the element adapter.
    """
    runs = _coords_to_row_runs(coords, border, ow, oh)
    raw = _bbox_of(coords, border, ow, oh)
    box = _pad_box(raw, ow, oh, padding)
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    return {
        "element_id": f"el_atom_{index:04d}",
        "bbox": box,
        "raw_bbox": raw,
        "center": {"x": round(cx, 2), "y": round(cy, 2)},
        "area": len(coords),
        "source_ink_pixel_count": len(coords),
        "mask_pixel_count": len(coords),
        "position": _position(cx, cy, ow, oh),
        "ocr_text": "",
        "source_ink_rle": _rle(runs, ow, oh),
        "mask_rle": _rle(runs, ow, oh),
    }


def _build_element_from_atoms(
    members: list[dict[str, Any]],
    ow: int,
    oh: int,
    padding: int,
    source_foreground: np.ndarray,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Adapter from atomic ink evidence to the saved Mask processing boundary."""
    ink_rle = _merge_row_runs(members, ow, oh)
    x1 = min(int(member["raw_bbox"]["x"]) for member in members)
    y1 = min(int(member["raw_bbox"]["y"]) for member in members)
    x2 = max(
        int(member["raw_bbox"]["x"]) + int(member["raw_bbox"]["w"]) for member in members
    )
    y2 = max(
        int(member["raw_bbox"]["y"]) + int(member["raw_bbox"]["h"]) for member in members
    )
    raw = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
    box = _pad_box(raw, ow, oh, padding)
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    ink_runs = ink_rle["runs"]
    total_ink = sum(int(member["area"]) for member in members)
    # Solidify is an interior-white repair for one dense panel, so it runs per
    # atom: filling the union's scanlines would re-bridge the white gap between
    # two bound atoms and put non-ink pixels inside the saved Mask.
    solidified = [
        {
            "mask_rle": _rle(
                _protect_other_foreground(
                    _solidify_planar_component(
                        member["mask_rle"]["runs"],
                        member["raw_bbox"],
                        int(member["area"]),
                    ),
                    member["mask_rle"]["runs"],
                    source_foreground,
                ),
                ow,
                oh,
            )
        }
        for member in members
    ]
    mask_runs = _merge_row_runs(solidified, ow, oh)["runs"]
    return {
        "element_id": "",
        "bbox": box,
        "raw_bbox": raw,
        "center": {"x": round(cx, 2), "y": round(cy, 2)},
        "area": total_ink,
        "mask_pixel_count": sum(run[2] - run[1] for run in mask_runs),
        "position": _position(cx, cy, ow, oh),
        "ocr_text": "",
        "source_ink_rle": ink_rle,
        "source_ink_pixel_count": total_ink,
        "grouping_pixel_count": total_ink,
        "bridge_pixel_count": 0,
        "mask_rle": _rle(mask_runs, ow, oh),
        **details,
    }


def _finalize_binding_v2(
    groups: list[dict[str, Any]],
    atoms: list[dict[str, Any]],
    layout_boxes: list[dict[str, Any]],
    ow: int,
    oh: int,
    settings: dict[str, Any],
    source_foreground: np.ndarray,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Regroup atomic components by scored layout candidate instead of by order."""
    binding = bind_atoms_to_boxes(atoms, layout_boxes, settings)
    by_id = {str(atom["element_id"]): atom for atom in atoms}
    padding = int(settings["component_padding_px"])
    min_element_area = int(settings["min_element_area"])
    merged: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for box_group in binding["groups"]:
        members = [
            by_id[element_id]
            for element_id in box_group["member_element_ids"]
            if element_id in by_id
        ]
        if not members:
            continue
        total_ink = sum(int(member["area"]) for member in members)
        if total_ink < min_element_area:
            # Too little real content to be an element: leave the fragments to
            # their detection group instead of inventing one here.
            continue
        merged.append(_build_element_from_atoms(
            members,
            ow,
            oh,
            padding,
            source_foreground,
            {
                "detection_source": "doclayout",
                "layout_role": box_group["role"],
                "layout_class_id": box_group["class_id"],
                "layout_confidence": box_group["confidence"],
                "layout_member_count": len(members),
                "atomic_component_ids": [member["element_id"] for member in members],
                "layout_binding": {
                    "method": binding["binding"]["method"],
                    "box": box_group["box"],
                    "ambiguous": bool(box_group["ambiguous_element_ids"]),
                    "ambiguous_candidates": {
                        element_id: binding["candidates_by_atom"].get(element_id, [])
                        for element_id in box_group["ambiguous_element_ids"]
                    },
                },
            },
        ))
        consumed.update(member["element_id"] for member in members)

    candidates: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    for group in groups:
        remaining = [
            atom for atom in group["atoms"] if atom["element_id"] not in consumed
        ]
        if not remaining:
            continue
        if len(remaining) == len(group["atoms"]):
            component = group["component"]
        else:
            component = _build_element_from_atoms(
                remaining,
                ow,
                oh,
                padding,
                source_foreground,
                {
                    "atomic_component_ids": [atom["element_id"] for atom in remaining],
                    "binding_note": "layout_box_partially_bound",
                },
            )
        if int(component["area"]) >= min_element_area:
            candidates.append(component)
        else:
            residual.append(component)
    candidates.extend(merged)
    report = {
        key: binding[key]
        for key in (
            "box_count",
            "unbound_element_ids",
            "ambiguous_element_ids",
            "binding",
        )
    }
    report.update({
        "atom_count": len(atoms),
        "bound_atom_count": len(consumed),
        "merged_element_count": len(merged),
        "boxes_bound": len([g for g in binding["groups"] if g["member_element_ids"]]),
    })
    return candidates, residual, report


def _assign_ids_and_crops(
    candidates: list[dict[str, Any]],
    residual: list[dict[str, Any]],
    image: Image.Image,
    crop_dir: Path,
) -> None:
    for i, element in enumerate(candidates, 1):
        element["element_id"] = f"el_auto_{i:03d}"
        box = element["bbox"]
        image.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(
            crop_dir / f"{element['element_id']}.png"
        )
    for i, element in enumerate(residual, 1):
        element["element_id"] = f"el_residual_{i:04d}"


def _layout_detection_record(
    layout_boxes: list[dict[str, Any]] | None,
    layout_status: dict[str, Any] | None,
) -> dict[str, Any]:
    """Describe the layout stage as an explicit state instead of "no boxes".

    ``layout_boxes`` alone cannot tell a disabled run apart from a missing model
    or a swallowed inference error, so the detector status record is merged in
    and kept as the source of truth for ``box_count``.
    """
    record: dict[str, Any] = {
        "enabled": layout_boxes is not None,
        "available": layout_boxes is not None,
        "box_count": len(layout_boxes) if layout_boxes else 0,
        "status": LAYOUT_STATUS_OK if layout_boxes else LAYOUT_STATUS_DISABLED,
    }
    if isinstance(layout_status, dict):
        record.update(layout_status)
        record["box_count"] = len(layout_boxes) if layout_boxes else 0
        if not layout_boxes and record.get("status") == LAYOUT_STATUS_OK:
            record["status"] = LAYOUT_STATUS_NO_BOXES
    return record


def detect_elements(
    image_path: Path,
    slide_dir: Path,
    settings: dict[str, Any],
    layout_boxes: list[dict[str, Any]] | None = None,
    layout_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out_dir = slide_dir / "auto_mask"
    cache_path = out_dir / "auto_elements.json"
    detection_settings = {
        key: settings.get(key)
        for key in (
            "white_threshold",
            "color_tolerance",
            "closing_radius",
            "add_border",
            "connectivity",
            "min_element_area",
            "component_padding_px",
            "pixel_evidence_separation",
            "layout_binding_v2",
        )
    }
    layout_fingerprint = _layout_fingerprint(layout_boxes)
    hash_started = time.perf_counter()
    source_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    settings_fingerprint = hashlib.sha256(
        json.dumps(detection_settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_read_ms = _elapsed_ms(hash_started)
    stage_timing_ms: dict[str, float] = {"source_hash": cache_read_ms}
    if cache_path.exists():
        try:
            cached = _read_json(cache_path)
            if (
                cached.get("version") == AUTO_ELEMENTS_VERSION
                and cached.get("source_sha256") == source_sha256
                and cached.get("detection_settings_fingerprint") == settings_fingerprint
                and cached.get("layout_fingerprint") == layout_fingerprint
            ):
                # The cached payload keeps the stage timings of the run that
                # produced it; ``cache_hit`` says no pixel work happened here.
                cached["cache_hit"] = True
                cached.setdefault("stage_timing_ms", {})["source_hash"] = cache_read_ms
                return cached
        except Exception:
            pass

    foreground_started = time.perf_counter()
    image = Image.open(image_path).convert("RGB")
    ow, oh = image.size
    border = int(settings["add_border"])
    if border:
        padded = Image.new("RGB", (ow + border * 2, oh + border * 2), (255, 255, 255))
        padded.paste(image, (border, border))
    else:
        padded = image
    arr = np.asarray(padded, dtype=np.uint8)
    h, w = arr.shape[:2]
    hi = arr.max(axis=2).astype(np.int16)
    lo = arr.min(axis=2).astype(np.int16)
    white = (lo >= int(settings["white_threshold"])) & ((hi - lo) <= int(settings["color_tolerance"]))
    bg = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def seed(x: int, y: int) -> None:
        if white[y, x] and not bg[y, x]:
            bg[y, x] = True
            q.append((x, y))

    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(h):
        seed(0, y)
        seed(w - 1, y)
    nbrs = _neighbors(int(settings["connectivity"]))
    while q:
        x, y = q.popleft()
        for dx, dy in nbrs:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and white[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                q.append((nx, ny))

    # ``ink_foreground`` is the pixel evidence: what the source bitmap actually
    # paints.  ``grouping_mask`` is the assumption layer built on top of it.
    ink_foreground = ~bg
    grouping_mask = ink_foreground
    stage_timing_ms["foreground"] = _elapsed_ms(foreground_started)

    # Morphological closing: dilate then erode to bridge small gaps (<=
    # closing_radius pixels) caused by hand-drawn stroke breaks.  This merges
    # fragmented strokes of the same element BEFORE connected-component
    # detection, drastically reducing the number of fragments.  The bridged
    # pixels are connectivity only: they are reported as ``bridge_pixel_count``
    # and never become content in a saved Mask.
    morphology_started = time.perf_counter()
    closing_radius = int(settings.get("closing_radius", 6))
    if closing_radius > 0:
        fg_uint8 = ink_foreground.astype(np.uint8) * 255
        kernel_size = closing_radius * 2 + 1
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        # dilation: bridge gaps; erosion: restore original size
        dilated = _morph_dilate(fg_uint8, kernel)
        closed = _morph_erode(dilated, kernel)
        grouping_mask = closed > 0
    if not _bool(settings.get("pixel_evidence_separation"), True):
        # Rollback switch: the v3 detector let the closing result overwrite the
        # ink evidence, so bridged gap pixels were saved as Mask content.
        ink_foreground = grouping_mask
    stage_timing_ms["morphology"] = _elapsed_ms(morphology_started)

    components_started = time.perf_counter()
    source_foreground = (
        ink_foreground[border:border + oh, border:border + ow] if border else ink_foreground
    )
    visited = np.zeros((h, w), dtype=bool)
    ys, xs = np.nonzero(grouping_mask)
    # Binding v2 owns ink at the atomic level, so the connected islands inside a
    # closing group are only recovered when layout boxes are actually present.
    recover_atoms = bool(
        layout_boxes
        and _bool(settings.get("pixel_evidence_separation"), True)
        and _bool(settings.get("layout_binding_v2"), True)
    )
    groups: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    padding = int(settings["component_padding_px"])
    atom_seq = 0
    crop_dir = out_dir / "elements"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for stale_crop in crop_dir.glob("*.png"):
        stale_crop.unlink(missing_ok=True)
    for sx, sy in zip(xs.tolist(), ys.tolist()):
        if visited[sy, sx] or not grouping_mask[sy, sx]:
            continue
        q.clear()
        q.append((sx, sy))
        visited[sy, sx] = True
        coords: list[tuple[int, int]] = []
        while q:
            x, y = q.popleft()
            coords.append((x, y))
            for dx, dy in nbrs:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and grouping_mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    q.append((nx, ny))
        # Projection splitting: if this connected component is oversized
        # (bridged by morphological closing), split it at projection valleys.
        canvas_area = ow * oh
        segments = _projection_split(coords, border, ow, oh, canvas_area)
        for seg_coords, raw in segments:
            if not seg_coords:
                continue
            ink_coords = [(x, y) for x, y in seg_coords if ink_foreground[y, x]]
            if not ink_coords:
                continue
            sx = [c[0] for c in seg_coords]
            sy = [c[1] for c in seg_coords]
            x1 = raw["x"]; y1 = raw["y"]
            x2 = x1 + raw["w"]; y2 = y1 + raw["h"]
            if x2 <= x1 or y2 <= y1:
                continue
            box = _pad_box(raw, ow, oh, int(settings["component_padding_px"]))
            cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
            source_runs = _coords_to_row_runs(ink_coords, border, ow, oh)
            component_runs = _solidify_planar_component(source_runs, raw, len(ink_coords))
            component_runs = _protect_other_foreground(component_runs, source_runs, source_foreground)
            component = {
                "element_id": "",
                "bbox": box,
                "raw_bbox": raw,
                "center": {"x": round(cx, 2), "y": round(cy, 2)},
                "area": len(ink_coords),
                "mask_pixel_count": sum(run[2] - run[1] for run in component_runs),
                "position": _position(cx, cy, ow, oh),
                "ocr_text": "",
                # Exact ink evidence of this component, before the panel
                # solidification and foreign-pixel protection steps.
                "source_ink_rle": {
                    "encoding": "row_runs_v1",
                    "width": ow,
                    "height": oh,
                    "runs": source_runs,
                },
                "source_ink_pixel_count": len(ink_coords),
                "grouping_pixel_count": len(seg_coords),
                "bridge_pixel_count": len(seg_coords) - len(ink_coords),
                "mask_rle": {
                    "encoding": "row_runs_v1",
                    "width": ow,
                    "height": oh,
                    "runs": component_runs,
                },
            }
            atoms: list[dict[str, Any]] = []
            if recover_atoms:
                for atom_coords in _connected_sets(ink_coords, nbrs):
                    atom_seq += 1
                    atoms.append(
                        _build_atom(atom_coords, border, ow, oh, atom_seq, padding)
                    )
                component["atomic_component_ids"] = [atom["element_id"] for atom in atoms]
            groups.append({"component": component, "atoms": atoms})
    candidates.extend(
        group["component"]
        for group in groups
        if int(group["component"]["area"]) >= int(settings["min_element_area"])
    )
    residual.extend(
        group["component"]
        for group in groups
        if int(group["component"]["area"]) < int(settings["min_element_area"])
    )
    candidates.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    residual.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    atoms = [atom for group in groups for atom in group["atoms"]]
    binding_report: dict[str, Any] | None = None
    if layout_boxes is not None and atoms:
        # Binding v2: a box owns atomic ink, never a traversal-order claim.
        candidates, residual, binding_report = _finalize_binding_v2(
            groups, atoms, layout_boxes, ow, oh, settings, source_foreground
        )
        candidates.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
        residual.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
        _assign_ids_and_crops(candidates, residual, image, crop_dir)
    else:
        _assign_ids_and_crops(candidates, residual, image, crop_dir)
        if layout_boxes is not None:
            # Rollback path: the v1 merge consumes components in box order.
            candidates, residual = _apply_layout_binding(
                candidates, residual, layout_boxes, ow, oh, settings
            )

    all_components = candidates + residual
    exact_foreground = _merge_row_runs(all_components, ow, oh)
    stage_timing_ms["components"] = _elapsed_ms(components_started)
    grouping_region = (
        grouping_mask[border:border + oh, border:border + ow] if border else grouping_mask
    )
    payload = {
        "version": AUTO_ELEMENTS_VERSION,
        "layout_fingerprint": layout_fingerprint,
        "cache_hit": False,
        "stage_timing_ms": stage_timing_ms,
        "layout_detection": _layout_detection_record(layout_boxes, layout_status),
        "layout_binding": binding_report,
        "slide_id": slide_dir.name,
        "source_sha256": source_sha256,
        "detection_settings_fingerprint": settings_fingerprint,
        "detection_settings": detection_settings,
        "canvas": {"width": ow, "height": oh},
        "elements": candidates,
        "residual_elements": residual,
        # ``source_foreground_pixel_count`` is true ink; ``grouping_pixel_count``
        # is the closing hypothesis that only decides which ink may share a Mask.
        "source_foreground_pixel_count": int(np.count_nonzero(source_foreground)),
        "grouping_pixel_count": int(np.count_nonzero(grouping_region)),
        "pixel_evidence_separation": _bool(
            settings.get("pixel_evidence_separation"), True
        ),
        "foreground_pixel_count": _rle_pixel_count(exact_foreground),
    }
    _write_json(out_dir / "auto_elements.json", payload)
    return payload



def _projection_split(
    coords: list[tuple[int, int]],
    border: int,
    ow: int,
    oh: int,
    canvas_area: int,
) -> list[tuple[list[tuple[int, int]], dict[str, int]]]:
    """Split an oversized connected component via projection valleys.

    Returns a list of (coords, raw_bbox) pairs. If no split is needed,
    returns a single-element list with the original component.
    """
    if not coords:
        return []
    px = [c[0] for c in coords]
    py = [c[1] for c in coords]
    x_min, x_max = min(px), max(px)
    y_min, y_max = min(py), max(py)
    w = x_max - x_min + 1
    h = y_max - y_min + 1
    bbox_area = w * h

    # Only split if the component is very large (>15% of canvas) AND
    # has a wide aspect ratio (w > 2*h or h > 2*w), indicating a
    # multi-module row/column that was bridged by morphological closing.
    if bbox_area < canvas_area * 0.15:
        return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                          "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]

    # Determine split direction: horizontal if wider than tall, vertical if taller
    split_horizontal = w > h * 1.5
    split_vertical = h > w * 1.5
    if not split_horizontal and not split_vertical:
        # Roughly square — try horizontal first if slightly wider
        split_horizontal = w >= h

    def find_valleys(projection: np.ndarray, length: int) -> list[int]:
        """Find valley points in a 1D projection curve.

        A valley is a local minimum where the projection drops below
        25% of the median peak height, with width >= 3 pixels.
        """
        if length < 20:
            return []
        # Smooth with a simple moving average (window=3)
        smoothed = np.convolve(projection, np.ones(3) / 3, mode="same")
        # Find peak height threshold
        peak_median = float(np.median(smoothed[smoothed > 0])) if np.any(smoothed > 0) else 0.0
        if peak_median < 1:
            return []
        threshold = peak_median * 0.25
        valleys: list[int] = []
        in_valley = False
        valley_start = 0
        for i in range(length):
            if smoothed[i] <= threshold:
                if not in_valley:
                    in_valley = True
                    valley_start = i
            else:
                if in_valley:
                    valley_end = i - 1
                    valley_width = valley_end - valley_start + 1
                    if valley_width >= 3:
                        valleys.append((valley_start + valley_end) // 2)
                    in_valley = False
        return valleys

    if split_horizontal:
        # X-axis projection: count pixels per column
        col_counts = np.zeros(w, dtype=np.int32)
        for cx in px:
            col_counts[cx - x_min] += 1
        valleys = find_valleys(col_counts, w)
        if len(valleys) < 1:
            return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                              "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]
        # Split at valley points
        cut_x_positions = [x_min + v for v in valleys]
        cut_x_positions.append(x_max + 1)
        prev = x_min
        segments: list[tuple[list[tuple[int, int]], dict[str, int]]] = []
        for cut_x in cut_x_positions:
            seg_coords = [(cx, cy) for cx, cy in coords if prev <= cx < cut_x]
            if seg_coords:
                sx_min = min(c[0] for c in seg_coords)
                sy_min = min(c[1] for c in seg_coords)
                sx_max = max(c[0] for c in seg_coords)
                sy_max = max(c[1] for c in seg_coords)
                raw = {"x": max(0, sx_min - border), "y": max(0, sy_min - border),
                       "w": min(ow, sx_max + 1 - sx_min), "h": min(oh, sy_max + 1 - sy_min)}
                segments.append((seg_coords, raw))
            prev = cut_x
        if len(segments) >= 2:
            return segments
    elif split_vertical:
        # Y-axis projection: count pixels per row
        row_counts = np.zeros(h, dtype=np.int32)
        for cy in py:
            row_counts[cy - y_min] += 1
        valleys = find_valleys(row_counts, h)
        if len(valleys) < 1:
            return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                              "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]
        cut_y_positions = [y_min + v for v in valleys]
        cut_y_positions.append(y_max + 1)
        prev = y_min
        segments: list[tuple[list[tuple[int, int]], dict[str, int]]] = []
        for cut_y in cut_y_positions:
            seg_coords = [(cx, cy) for cx, cy in coords if prev <= cy < cut_y]
            if seg_coords:
                sx_min = min(c[0] for c in seg_coords)
                sy_min = min(c[1] for c in seg_coords)
                sx_max = max(c[0] for c in seg_coords)
                sy_max = max(c[1] for c in seg_coords)
                raw = {"x": max(0, sx_min - border), "y": max(0, sy_min - border),
                       "w": min(ow, sx_max + 1 - sx_min), "h": min(oh, sy_max + 1 - sy_min)}
                segments.append((seg_coords, raw))
            prev = cut_y
        if len(segments) >= 2:
            return segments

    return [(coords, {"x": max(0, x_min - border), "y": max(0, y_min - border),
                      "w": min(ow, x_max + 1 - x_min), "h": min(oh, y_max + 1 - y_min)})]





def _apply_layout_binding(
    candidates: list[dict[str, Any]],
    residual: list[dict[str, Any]],
    layout_boxes: list[dict[str, Any]] | None,
    width: int,
    height: int,
    settings: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把 flood-fill 组件按 DocLayout 候选框聚合成语义元素。

    同一候选框内的组件（candidates 与 residual 均可被吸收）合并为一个
    layout 元素；聚合后面积小于 min_element_area 时保留原组件不合并。
    未命中任何候选框的组件保持独立，candidates / residual 身份不丢失。
    """
    if not layout_boxes:
        return candidates, residual

    candidate_ids = {id(comp) for comp in candidates}
    all_components = list(candidates) + list(residual)
    used: set[int] = set()
    merged: list[dict[str, Any]] = []
    min_element_area = int(settings.get("min_element_area", 120))

    for box_info in layout_boxes:
        box = box_info.get("box") if isinstance(box_info.get("box"), dict) else {}
        bx = float(box.get("x", 0))
        by = float(box.get("y", 0))
        bx2 = bx + float(box.get("w", 0))
        by2 = by + float(box.get("h", 0))
        role = str(box_info.get("role") or "text")
        confidence = float(box_info.get("confidence", 0) or 0)
        class_id = int(box_info.get("class_id", -1))

        members: list[dict[str, Any]] = []
        for comp in all_components:
            if id(comp) in used:
                continue
            center = comp.get("center") if isinstance(comp.get("center"), dict) else {}
            cx = float(center.get("x", 0))
            cy = float(center.get("y", 0))
            if bx <= cx <= bx2 and by <= cy <= by2:
                members.append(comp)

        total_area = sum(int(member.get("area", 0) or 0) for member in members)
        if not members or total_area < min_element_area:
            continue

        member_ids = {id(member) for member in members}
        x1 = min(float(member["bbox"]["x"]) for member in members)
        y1 = min(float(member["bbox"]["y"]) for member in members)
        x2 = max(float(member["bbox"]["x"]) + float(member["bbox"]["w"]) for member in members)
        y2 = max(float(member["bbox"]["y"]) + float(member["bbox"]["h"]) for member in members)
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        mask_rle = _merge_row_runs(members, width, height)

        merged.append({
            "element_id": f"el_layout_{len(merged) + 1:03d}",
            "bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
            "raw_bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
            "center": {"x": round(cx, 2), "y": round(cy, 2)},
            "area": total_area,
            "mask_pixel_count": _rle_pixel_count(mask_rle),
            "position": _position(cx, cy, width, height),
            "ocr_text": "",
            "mask_rle": mask_rle,
            "detection_source": "doclayout",
            "layout_role": role,
            "layout_class_id": class_id,
            "layout_confidence": confidence,
            "layout_member_count": len(members),
        })
        used.update(member_ids)

    new_candidates = merged
    new_residual: list[dict[str, Any]] = []
    for comp in all_components:
        if id(comp) in used:
            continue
        if id(comp) in candidate_ids:
            new_candidates.append(comp)
        else:
            new_residual.append(comp)
    new_candidates.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    new_residual.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    return new_candidates, new_residual

def _layout_fingerprint(layout_boxes: list[dict[str, Any]] | None) -> str:
    """生成 DocLayout 候选框的稳定指纹，用于缓存区分（无布局框返回空串）。

    行序与模型输出顺序无关：同一组版面框无论以什么顺序返回都是同一份输入，
    否则仅仅换序就会击穿缓存。
    """
    if not layout_boxes:
        return ""
    try:
        rows = []
        for box in layout_boxes:
            b = box.get("box") if isinstance(box.get("box"), dict) else {}
            rows.append(
                "{r}|{c}|{x}|{y}|{w}|{h}".format(
                    r=str(box.get("role") or ""),
                    c=round(float(box.get("confidence", 0) or 0), 4),
                    x=int(b.get("x", 0)), y=int(b.get("y", 0)),
                    w=int(b.get("w", 0)), h=int(b.get("h", 0)),
                )
            )
        return hashlib.sha256(
            json.dumps(sorted(rows), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    except Exception:
        return ""
