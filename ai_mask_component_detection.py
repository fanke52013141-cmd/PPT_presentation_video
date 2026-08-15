"""Deterministic foreground component detection and exact RLE utilities."""

from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


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


def detect_elements(image_path: Path, slide_dir: Path, settings: dict[str, Any], layout_boxes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        )
    }
    layout_fingerprint = _layout_fingerprint(layout_boxes)
    source_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    settings_fingerprint = hashlib.sha256(
        json.dumps(detection_settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if cache_path.exists():
        try:
            cached = _read_json(cache_path)
            if (
                cached.get("version") == "auto_elements_v3_exact_rle_cached"
                and cached.get("source_sha256") == source_sha256
                and cached.get("detection_settings_fingerprint") == settings_fingerprint
                and cached.get("layout_fingerprint") == layout_fingerprint
            ):
                return cached
        except Exception:
            pass

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

    fg = ~bg

    # Morphological closing: dilate then erode the foreground mask to bridge
    # small gaps (<= closing_radius pixels) caused by hand-drawn stroke breaks.
    # This merges fragmented strokes of the same element BEFORE connected-
    # component detection, drastically reducing the number of fragments.
    closing_radius = int(settings.get("closing_radius", 6))
    if closing_radius > 0:
        fg_uint8 = fg.astype(np.uint8) * 255
        kernel_size = closing_radius * 2 + 1
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        # dilation: bridge gaps; erosion: restore original size
        dilated = _morph_dilate(fg_uint8, kernel)
        closed = _morph_erode(dilated, kernel)
        fg = closed > 0

    source_foreground = fg[border:border + oh, border:border + ow] if border else fg
    visited = np.zeros((h, w), dtype=bool)
    ys, xs = np.nonzero(fg)
    candidates: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    crop_dir = out_dir / "elements"
    crop_dir.mkdir(parents=True, exist_ok=True)
    for stale_crop in crop_dir.glob("*.png"):
        stale_crop.unlink(missing_ok=True)
    for sx, sy in zip(xs.tolist(), ys.tolist()):
        if visited[sy, sx] or not fg[sy, sx]:
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
                if 0 <= nx < w and 0 <= ny < h and fg[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    q.append((nx, ny))
        # Projection splitting: if this connected component is oversized
        # (bridged by morphological closing), split it at projection valleys.
        canvas_area = ow * oh
        segments = _projection_split(coords, border, ow, oh, canvas_area)
        for seg_coords, raw in segments:
            if not seg_coords:
                continue
            sx = [c[0] for c in seg_coords]
            sy = [c[1] for c in seg_coords]
            x1 = raw["x"]; y1 = raw["y"]
            x2 = x1 + raw["w"]; y2 = y1 + raw["h"]
            if x2 <= x1 or y2 <= y1:
                continue
            box = _pad_box(raw, ow, oh, int(settings["component_padding_px"]))
            cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
            source_runs = _coords_to_row_runs(seg_coords, border, ow, oh)
            component_runs = _solidify_planar_component(source_runs, raw, len(seg_coords))
            component_runs = _protect_other_foreground(component_runs, source_runs, source_foreground)
            component = {
                "element_id": "",
                "bbox": box,
                "raw_bbox": raw,
                "center": {"x": round(cx, 2), "y": round(cy, 2)},
                "area": len(seg_coords),
                "mask_pixel_count": sum(run[2] - run[1] for run in component_runs),
                "position": _position(cx, cy, ow, oh),
                "ocr_text": "",
                "mask_rle": {
                    "encoding": "row_runs_v1",
                    "width": ow,
                    "height": oh,
                    "runs": component_runs,
                },
            }
            if len(seg_coords) >= int(settings["min_element_area"]):
                candidates.append(component)
            else:
                residual.append(component)
    candidates.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    residual.sort(key=lambda e: (e["bbox"]["y"], e["bbox"]["x"]))
    for i, element in enumerate(candidates, 1):
        element["element_id"] = f"el_auto_{i:03d}"
        box = element["bbox"]
        image.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(
            crop_dir / f"{element['element_id']}.png"
        )
    for i, element in enumerate(residual, 1):
        element["element_id"] = f"el_residual_{i:04d}"
    # ---- DocLayout layout binding (post-detection merge) ----
    if layout_boxes is not None:
        candidates, residual = _apply_layout_binding(
            candidates, residual, layout_boxes, ow, oh, settings
        )

    all_components = candidates + residual
    exact_foreground = _merge_row_runs(all_components, ow, oh)
    payload = {
        "version": "auto_elements_v3_exact_rle_cached",
        "layout_fingerprint": layout_fingerprint,
        "layout_detection": {
            "enabled": layout_boxes is not None,
            "available": layout_boxes is not None,
            "box_count": len(layout_boxes) if layout_boxes else 0,
        },
        "slide_id": slide_dir.name,
        "source_sha256": source_sha256,
        "detection_settings_fingerprint": settings_fingerprint,
        "detection_settings": detection_settings,
        "canvas": {"width": ow, "height": oh},
        "elements": candidates,
        "residual_elements": residual,
        "source_foreground_pixel_count": int(np.count_nonzero(source_foreground)),
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
    """生成 DocLayout 候选框的稳定指纹，用于缓存区分（无布局框返回空串）。"""
    if not layout_boxes:
        return ""
    try:
        rows = []
        for box in layout_boxes:
            b = box.get("box") if isinstance(box.get("box"), dict) else {}
            rows.append({
                "r": str(box.get("role") or ""),
                "c": round(float(box.get("confidence", 0) or 0), 4),
                "x": int(b.get("x", 0)), "y": int(b.get("y", 0)),
                "w": int(b.get("w", 0)), "h": int(b.get("h", 0)),
            })
        return hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    except Exception:
        return ""
