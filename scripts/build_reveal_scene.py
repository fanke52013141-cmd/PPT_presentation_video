#!/usr/bin/env python3
"""Build a full-slide reveal scene from reveal_manifest.json."""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DEFAULT_CANVAS = {"width": 1920, "height": 1080, "background": "#FFFDF7", "subtitle_safe_y": 930}
DEFAULTS = {"padding_px": 32, "duration": 0.12, "angle": 135, "feather": 16, "fog_strength": 0.68, "blur_px": 16}
MIN_REVEAL_DURATION_SEC = 0.05
COVER_ACTIONS = {"cover_fade_out", "cover_wipe_left_to_right", "cover_wipe_top_to_bottom"}
FOG_ACTIONS = {"fog_diagonal_erase"}
CROP_ACTIONS = {"crop_fade_up", "crop_slide_in_left", "crop_soft_zoom_in"}
ALLOWED_ACTIONS = COVER_ACTIONS | FOG_ACTIONS | CROP_ACTIONS | {"highlight"}
TAIL_TRIM_ROLES = {"content_body", "diagram", "annotation"}


class RevealBuildError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RevealBuildError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RevealBuildError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RevealBuildError(f"JSON file must contain an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(value: str, manifest_dir: Path, slide_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (slide_dir / path, manifest_dir / path, repo_root / path):
        if candidate.exists():
            return candidate
    return slide_dir / path


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise RevealBuildError(f"Invalid hex color: {value}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))


def padded_box(raw: dict[str, Any], width: int, height: int, padding: int) -> dict[str, int]:
    x = int(round(float(raw["x"])))
    y = int(round(float(raw["y"])))
    w = int(round(float(raw["w"])))
    h = int(round(float(raw["h"])))
    if w <= 0 or h <= 0:
        raise RevealBuildError(f"Invalid box size: {raw}")
    if x < 0 or y < 0 or x + w > width or y + h > height:
        raise RevealBuildError(f"Box outside canvas: {raw}")
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(width, x + w + padding)
    y2 = min(height, y + h + padding)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def crop_image(image: Image.Image, box: dict[str, int]) -> Image.Image:
    return image.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]))


def paste_mask_clipped(target: Image.Image, mask: Image.Image, target_box: dict[str, int], mask_box: dict[str, int]) -> None:
    dx = mask_box["x"] - target_box["x"]
    dy = mask_box["y"] - target_box["y"]
    src_x1 = max(0, -dx)
    src_y1 = max(0, -dy)
    dst_x1 = max(0, dx)
    dst_y1 = max(0, dy)
    paste_w = min(mask_box["w"] - src_x1, target.width - dst_x1)
    paste_h = min(mask_box["h"] - src_y1, target.height - dst_y1)
    if paste_w <= 0 or paste_h <= 0:
        return
    cropped = mask.crop((src_x1, src_y1, src_x1 + paste_w, src_y1 + paste_h))
    target.paste(cropped, (dst_x1, dst_y1))


def erase_box_from_crop(rgba: Image.Image, crop_box: dict[str, int], erase_box: dict[str, int], margin: int = 4) -> None:
    x1 = max(crop_box["x"], erase_box["x"] - margin)
    y1 = max(crop_box["y"], erase_box["y"] - margin)
    x2 = min(crop_box["x"] + crop_box["w"], erase_box["x"] + erase_box["w"] + margin)
    y2 = min(crop_box["y"] + crop_box["h"], erase_box["y"] + erase_box["h"] + margin)
    if x2 <= x1 or y2 <= y1:
        return
    alpha = rgba.getchannel("A")
    draw = ImageDraw.Draw(alpha)
    draw.rectangle((x1 - crop_box["x"], y1 - crop_box["y"], x2 - crop_box["x"], y2 - crop_box["y"]), fill=0)
    rgba.putalpha(alpha)


def erase_mask_from_crop(
    rgba: Image.Image,
    crop_box: dict[str, int],
    erase_box: dict[str, int],
    erase_alpha: Image.Image | None,
) -> bool:
    if erase_alpha is None:
        return False
    expanded = expand_alpha(erase_alpha, pixels=28)
    if expanded is None:
        return False
    mask = Image.new("L", rgba.size, 0)
    paste_mask_clipped(mask, expanded, crop_box, erase_box)
    clear_mask = mask.point(lambda value: 255 if value > 0 else 0)
    alpha = rgba.getchannel("A")
    alpha = Image.composite(Image.new("L", rgba.size, 0), alpha, clear_mask)
    rgba.putalpha(alpha)
    return bool(clear_mask.getbbox())


def erase_later_groups_from_crop(
    rgba: Image.Image,
    crop_box: dict[str, int],
    group_index: int,
    groups: list[Any],
    group_boxes: dict[str, dict[str, int]],
) -> None:
    for later_group in groups[group_index:]:
        if not isinstance(later_group, dict):
            continue
        later_id = str(later_group.get("id", "")).strip()
        later_box = group_boxes.get(later_id)
        if not later_box:
            continue
        later_alpha = manual_mask_alpha(later_group.get("manual_mask"), later_box)
        if not erase_mask_from_crop(rgba, crop_box, later_box, later_alpha):
            erase_box_from_crop(rgba, crop_box, later_box)


def is_erase_stroke(stroke: dict[str, Any]) -> bool:
    mode = str(stroke.get("mode", "")).lower()
    return bool(stroke.get("eraser")) or mode == "erase"


def manual_mask_alpha(
    manual_mask: Any,
    box: dict[str, int],
    paint_expand: int = 24,
    erase_expand: int = 8,
) -> Image.Image | None:
    if not isinstance(manual_mask, dict):
        return None
    strokes = manual_mask.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        return None
    alpha = Image.new("L", (box["w"], box["h"]), 0)
    draw = ImageDraw.Draw(alpha)
    for stroke in strokes:
        if not isinstance(stroke, dict):
            continue
        points = stroke.get("points")
        if not isinstance(points, list) or not points:
            continue
        is_erase = is_erase_stroke(stroke)
        expand = erase_expand if is_erase else paint_expand
        size = max(1, int(round(float(stroke.get("size", 42)) + expand * 2)))
        fill = 0 if is_erase else 255
        local_points: list[tuple[int, int]] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            local_points.append((
                int(round(float(point.get("x", 0)) - box["x"])),
                int(round(float(point.get("y", 0)) - box["y"])),
            ))
        if not local_points:
            continue
        radius = max(1, size // 2)
        if len(local_points) == 1:
            x, y = local_points[0]
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
            continue
        draw.line(local_points, fill=fill, width=size, joint="curve")
        for x, y in local_points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    return alpha


def manual_erase_alpha(manual_mask: Any, width: int, height: int, expand: int = 8) -> Image.Image | None:
    if not isinstance(manual_mask, dict):
        return None
    strokes = manual_mask.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        return None
    alpha = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha)
    found = False
    for stroke in strokes:
        if not isinstance(stroke, dict) or not is_erase_stroke(stroke):
            continue
        points = stroke.get("points")
        if not isinstance(points, list) or not points:
            continue
        found = True
        size = max(1, int(round(float(stroke.get("size", 42)) + expand * 2)))
        radius = max(1, size // 2)
        coords = [
            (int(round(float(point.get("x", 0)))), int(round(float(point.get("y", 0)))))
            for point in points
            if isinstance(point, dict)
        ]
        if not coords:
            continue
        if len(coords) > 1:
            draw.line(coords, fill=255, width=size, joint="curve")
        for x, y in coords:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return alpha if found else None


def manual_mask_box(manual_mask: Any, width: int, height: int, padding: int = 32) -> dict[str, int] | None:
    if not isinstance(manual_mask, dict):
        return None
    strokes = manual_mask.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for stroke in strokes:
        if not isinstance(stroke, dict):
            continue
        if is_erase_stroke(stroke):
            continue
        points = stroke.get("points")
        if not isinstance(points, list) or not points:
            continue
        radius = max(1.0, float(stroke.get("size", 42)) / 2.0)
        for point in points:
            if not isinstance(point, dict):
                continue
            x = float(point.get("x", 0))
            y = float(point.get("y", 0))
            xs.extend([x - radius, x + radius])
            ys.extend([y - radius, y + radius])
    if not xs or not ys:
        return None
    x1 = max(0, int(round(min(xs) - padding)))
    y1 = max(0, int(round(min(ys) - padding)))
    x2 = min(width, int(round(max(xs) + padding)))
    y2 = min(height, int(round(max(ys) + padding)))
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def sample_background(image: Image.Image, fallback: str, sample_size: int = 24) -> tuple[int, int, int]:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    h, w, _ = rgb.shape
    samples = np.concatenate([
        rgb[:sample_size, :sample_size].reshape(-1, 3),
        rgb[:sample_size, max(0, w - sample_size):].reshape(-1, 3),
        rgb[max(0, h - sample_size):, :sample_size].reshape(-1, 3),
        rgb[max(0, h - sample_size):, max(0, w - sample_size):].reshape(-1, 3),
    ])
    if samples.size == 0:
        return hex_to_rgb(fallback)
    return tuple(int(value) for value in np.median(samples, axis=0))


def foreground_alpha(image: Image.Image, background: str, low: int = 8, high: int = 32) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    bg = np.asarray(sample_background(image, background), dtype=np.int16)
    distance = np.max(np.abs(rgb - bg), axis=2)
    scaled = np.clip((distance - low) * (255.0 / max(1, high - low)), 0, 255).astype(np.uint8)
    return Image.fromarray(scaled, mode="L")


def seed_mask_for_group(group: dict[str, Any], width: int, height: int) -> Image.Image:
    full_box = {"x": 0, "y": 0, "w": width, "h": height}
    seed = manual_mask_alpha(group.get("manual_mask"), full_box, paint_expand=0, erase_expand=0)
    if seed is not None and seed.getbbox():
        return seed
    raw_box = group.get("box")
    if not isinstance(raw_box, dict):
        return Image.new("L", (width, height), 0)
    box = padded_box(raw_box, width, height, int(group.get("padding_px", DEFAULTS["padding_px"])))
    seed = Image.new("L", (width, height), 0)
    ImageDraw.Draw(seed).rectangle(
        (box["x"], box["y"], box["x"] + box["w"] - 1, box["y"] + box["h"] - 1),
        fill=255,
    )
    return seed


def nearest_seed_labels(seed_masks: list[Image.Image], width: int, height: int, scale: int = 4) -> np.ndarray:
    small_width = max(1, (width + scale - 1) // scale)
    small_height = max(1, (height + scale - 1) // scale)
    labels = np.full((small_height, small_width), -1, dtype=np.int16)
    queue: deque[tuple[int, int]] = deque()
    for index, seed in enumerate(seed_masks):
        small = np.asarray(seed.resize((small_width, small_height), Image.Resampling.NEAREST), dtype=np.uint8)
        ys, xs = np.where((small > 0) & (labels < 0))
        labels[ys, xs] = index
        queue.extend(zip(ys.tolist(), xs.tolist()))
    if not queue:
        return np.zeros((height, width), dtype=np.int16)
    while queue:
        y, x = queue.popleft()
        label = labels[y, x]
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < small_height and 0 <= nx < small_width and labels[ny, nx] < 0:
                labels[ny, nx] = label
                queue.append((ny, nx))
    full = Image.fromarray(labels.astype(np.int32), mode="I").resize((width, height), Image.Resampling.NEAREST)
    return np.asarray(full, dtype=np.int16)


def build_group_alphas(
    master: Image.Image,
    groups: list[Any],
    background: str,
    width: int,
    height: int,
) -> dict[str, Image.Image]:
    valid_groups = [group for group in groups if isinstance(group, dict)]
    seeds = [seed_mask_for_group(group, width, height) for group in valid_groups]
    owners = nearest_seed_labels(seeds, width, height)
    content_alpha = np.asarray(foreground_alpha(master, background), dtype=np.uint8)
    result: dict[str, Image.Image] = {}

    for index, group in enumerate(valid_groups):
        group_id = str(group.get("id", "")).strip()
        alpha = np.where(owners == index, content_alpha, 0).astype(np.uint8)
        erase = manual_erase_alpha(group.get("manual_mask"), width, height)
        if erase is not None:
            alpha[np.asarray(erase, dtype=np.uint8) > 0] = 0
        result[group_id] = Image.fromarray(alpha, mode="L")
    return result


def alpha_box(alpha: Image.Image, fallback: dict[str, int], width: int, height: int, padding: int = 4) -> dict[str, int]:
    bbox = alpha.getbbox()
    if not bbox:
        return fallback
    x1 = max(0, bbox[0] - padding)
    y1 = max(0, bbox[1] - padding)
    x2 = min(width, bbox[2] + padding)
    y2 = min(height, bbox[3] + padding)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def box_right(box: dict[str, int]) -> int:
    return box["x"] + box["w"]


def box_bottom(box: dict[str, int]) -> int:
    return box["y"] + box["h"]


def box_mostly_inside(inner: dict[str, int], outer: dict[str, int], tolerance: int = 24) -> bool:
    return (
        inner["x"] >= outer["x"] - tolerance
        and inner["y"] >= outer["y"] - tolerance
        and box_right(inner) <= box_right(outer) + tolerance
        and box_bottom(inner) <= box_bottom(outer) + tolerance
    )


def expand_box_horizontally(box: dict[str, int], fallback: dict[str, int], width: int) -> dict[str, int]:
    x1 = max(0, fallback["x"])
    x2 = min(width, box_right(fallback))
    return {**box, "x": x1, "w": max(1, x2 - x1)}


def reveal_box_for_group(
    alpha: Image.Image,
    fallback: dict[str, int],
    content_alpha: np.ndarray,
    width: int,
    height: int,
    role: str,
) -> tuple[dict[str, int], Image.Image]:
    tight = alpha_box(alpha, fallback, width, height)
    if box_mostly_inside(tight, fallback):
        return expand_box_horizontally(tight, fallback, width), alpha
    if role in TAIL_TRIM_ROLES:
        trimmed = trim_isolated_tails(alpha, content_alpha)
        return alpha_box(trimmed, fallback, width, height), trimmed
    return tight, alpha


def true_runs(values: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values.tolist()):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(values)))
    return runs


def merge_close_runs(runs: list[tuple[int, int]], max_gap: int = 12) -> list[tuple[int, int]]:
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def trim_isolated_projection_tails(
    alpha: Image.Image,
    content_alpha: np.ndarray,
    axis: str,
    min_area_ratio: float = 0.18,
) -> Image.Image:
    alpha_array = np.asarray(alpha, dtype=np.uint8).copy()
    support = (alpha_array > 0) & (content_alpha > 8)
    if axis == "x":
        projection = support.any(axis=0)
    elif axis == "y":
        projection = support.any(axis=1)
    else:
        return alpha

    runs = merge_close_runs(true_runs(projection))
    if len(runs) <= 1:
        return alpha

    if axis == "x":
        areas = [int(support[:, start:end].sum()) for start, end in runs]
    else:
        areas = [int(support[start:end, :].sum()) for start, end in runs]
    largest = max(areas, default=0)
    if largest <= 0:
        return alpha
    keep = [area >= largest * min_area_ratio for area in areas]
    if all(keep):
        return alpha

    keep_mask_size = alpha_array.shape[1] if axis == "x" else alpha_array.shape[0]
    keep_mask = np.zeros(keep_mask_size, dtype=bool)
    for should_keep, (start, end) in zip(keep, runs):
        if should_keep:
            keep_mask[start:end] = True
    if axis == "x":
        alpha_array[:, ~keep_mask] = 0
    else:
        alpha_array[~keep_mask, :] = 0
    return Image.fromarray(alpha_array, mode="L")


def trim_isolated_tails(alpha: Image.Image, content_alpha: np.ndarray) -> Image.Image:
    trimmed = trim_isolated_projection_tails(alpha, content_alpha, "x")
    return trim_isolated_projection_tails(trimmed, content_alpha, "y")


def expand_alpha(alpha: Image.Image | None, pixels: int = 18) -> Image.Image | None:
    if alpha is None or pixels <= 0:
        return alpha
    kernel = max(3, pixels if pixels % 2 == 1 else pixels + 1)
    return alpha.filter(ImageFilter.MaxFilter(kernel)).filter(ImageFilter.GaussianBlur(0.6))


def apply_alpha(image: Image.Image, alpha: Image.Image | None) -> Image.Image:
    if alpha is None:
        return image
    rgba = image.convert("RGBA")
    if alpha.size != rgba.size:
        alpha = alpha.resize(rgba.size, Image.Resampling.LANCZOS)
    rgba.putalpha(expand_alpha(alpha))
    return rgba


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def background_candidates(image: Image.Image, fallback: str, sample_size: int = 18) -> list[tuple[int, int, int]]:
    rgb = image.convert("RGB")
    w, h = rgb.size
    fallback_rgb = hex_to_rgb(fallback)
    candidates: list[tuple[int, int, int]] = [fallback_rgb]
    samples: list[tuple[int, int, int]] = []
    origins = [
        (0, 0),
        (max(0, w - sample_size), 0),
        (0, max(0, h - sample_size)),
        (max(0, w - sample_size), max(0, h - sample_size)),
    ]
    pixels = rgb.load()
    for ox, oy in origins:
        for y in range(oy, min(h, oy + sample_size)):
            for x in range(ox, min(w, ox + sample_size)):
                r, g, b = pixels[x, y]
                brightness = (r + g + b) / 3
                saturation = max(r, g, b) - min(r, g, b)
                if brightness >= 232 and saturation <= 28:
                    samples.append((r, g, b))
    if samples:
        samples.sort()
        candidates.append(samples[len(samples) // 2])
    unique: list[tuple[int, int, int]] = []
    for color in candidates:
        if all(color_distance(color, existing) > 4 for existing in unique):
            unique.append(color)
    return unique


def remove_background_from_masked_crop(
    image: Image.Image,
    alpha: Image.Image | None,
    background: str,
    reference: Image.Image | None = None,
    tolerance: int = 34,
    feather: int = 26,
) -> Image.Image:
    rgba = apply_alpha(image, alpha).convert("RGBA")
    if alpha is None:
        return rgba
    candidates = background_candidates(reference or image, background)
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            rgb = (r, g, b)
            distance = min(color_distance(rgb, bg) for bg in candidates)
            if distance <= tolerance:
                pixels[x, y] = (r, g, b, 0)
            elif distance <= tolerance + feather:
                fade = (distance - tolerance) / max(1, feather)
                pixels[x, y] = (r, g, b, int(a * fade))
    return rgba


def write_cover(path: Path, box: dict[str, int], color: str, alpha: Image.Image | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "RGBA" if alpha is not None else "RGB"
    cover = Image.new(mode, (box["w"], box["h"]), hex_to_rgb(color) + ((255,) if alpha is not None else ()))
    if alpha is not None:
        cover.putalpha(alpha)
    cover.save(path, format="PNG")


def write_fog(path: Path, master: Image.Image, box: dict[str, int], color: str, strength: float, blur_px: float, alpha: Image.Image | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = crop_image(master, box).convert("RGB").filter(ImageFilter.GaussianBlur(float(blur_px)))
    overlay = Image.new("RGB", base.size, hex_to_rgb(color))
    fog = Image.blend(base, overlay, max(0.0, min(1.0, float(strength))))
    fog = apply_alpha(fog, alpha)
    fog.save(path, format="PNG")


def rect_distance(a: dict[str, int], b: dict[str, int]) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    dx = max(b["x"] - ax2, a["x"] - bx2, 0)
    dy = max(b["y"] - ay2, a["y"] - by2, 0)
    return float((dx * dx + dy * dy) ** 0.5)


def build_event(slide_id: str, group: dict[str, Any], layer_id: str, fallback_at: float) -> dict[str, Any]:
    reveal = group.get("reveal") if isinstance(group.get("reveal"), dict) else {}
    action = str(reveal.get("type", "cover_fade_out"))
    if action not in ALLOWED_ACTIONS:
        raise RevealBuildError(f"Unsupported reveal action: {action}")
    at = float(reveal.get("at", fallback_at))
    duration = float(reveal.get("duration", DEFAULTS["duration"]))
    duration = min(duration, DEFAULTS["duration"])
    event: dict[str, Any] = {
        "id": f"{slide_id}_{group['id']}_{action}",
        "target": layer_id,
        "target_group_id": group["id"],
        "action": action,
        "at": round(max(0.0, at), 3),
        "duration": round(max(MIN_REVEAL_DURATION_SEC, duration), 3),
        "easing": "easeOutCubic",
        "params": {
            "angle": float(reveal.get("angle", DEFAULTS["angle"])),
            "feather": float(reveal.get("feather", DEFAULTS["feather"])),
        },
    }
    for key in ("narration_beat_id", "linked_segment_id"):
        if group.get(key):
            event[key] = group[key]
    if isinstance(group.get("narration_beat_ids"), list) and group["narration_beat_ids"]:
        event["narration_beat_ids"] = group["narration_beat_ids"]
    return event


def compose_slide(slide: dict[str, Any], manifest_dir: Path, repo_root: Path, default_canvas: dict[str, Any]) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise RevealBuildError("Slide missing slide_id")
    slide_dir = resolve_path(str(slide["slide_dir"]), manifest_dir, manifest_dir, repo_root)
    assets_dir = slide_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    master_path = resolve_path(str(slide["master"]), manifest_dir, slide_dir, repo_root)
    if not master_path.exists():
        raise RevealBuildError(f"Missing master image: {master_path}")
    master = Image.open(master_path).convert("RGB")
    canvas = {**default_canvas, **(slide.get("canvas") if isinstance(slide.get("canvas"), dict) else {})}
    width = int(canvas.get("width", master.width))
    height = int(canvas.get("height", master.height))
    if master.size != (width, height):
        master = master.resize((width, height), Image.Resampling.LANCZOS)
    background = str(canvas.get("background", DEFAULT_CANVAS["background"]))
    subtitle_safe_y = int(canvas.get("subtitle_safe_y", DEFAULT_CANVAS["subtitle_safe_y"]))
    master.save(assets_dir / "full_slide.png", format="PNG")
    layers: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    groups = slide.get("groups")
    if not isinstance(groups, list):
        raise RevealBuildError(f"Slide groups must be a list: {slide_id}")
    group_alphas = build_group_alphas(master, groups, background, width, height)
    content_alpha = np.asarray(foreground_alpha(master, background), dtype=np.uint8)
    group_boxes: dict[str, dict[str, int]] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise RevealBuildError(f"Invalid group in {slide_id}")
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            raise RevealBuildError(f"Group missing id in {slide_id}")
        raw_box = group.get("box")
        if not isinstance(raw_box, dict):
            raise RevealBuildError(f"Group missing box in {slide_id}: {group_id}")
        padding = int(group.get("padding_px", DEFAULTS["padding_px"]))
        fallback_box = manual_mask_box(group.get("manual_mask"), width, height) or padded_box(raw_box, width, height, padding)
        role = str(group.get("role", "content_body"))
        group_boxes[group_id], group_alphas[group_id] = reveal_box_for_group(
            group_alphas[group_id],
            fallback_box,
            content_alpha,
            width,
            height,
            role,
        )
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            raise RevealBuildError(f"Invalid group in {slide_id}")
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            raise RevealBuildError(f"Group missing id in {slide_id}")
        role = str(group.get("role", "content_body"))
        raw_box = group.get("box")
        if not isinstance(raw_box, dict):
            raise RevealBuildError(f"Group missing box in {slide_id}: {group_id}")
        box = group_boxes[group_id]
        if role != "decoration" and box["y"] + box["h"] > subtitle_safe_y:
            warnings.append({"severity": "blocking", "type": "subtitle_safe_zone_violation", "group_id": group_id})
        for existing in placed:
            gap = rect_distance(box, existing["box"])
            if gap < 48 and role != "decoration" and existing["role"] != "decoration":
                warnings.append({"severity": "warning", "type": "group_gap_small", "group_id": group_id, "other_group_id": existing["id"], "gap_px": round(gap, 2)})
        reveal = group.get("reveal") if isinstance(group.get("reveal"), dict) else {}
        action = str(reveal.get("type", "crop_fade_up"))
        layer_asset = ""
        layer_role = "reveal_crop"
        if action not in CROP_ACTIONS:
            action = "crop_fade_up"
        rel = f"assets/crops/{group_id}.png"
        (slide_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        crop = crop_image(master, box).convert("RGBA")
        crop.putalpha(Image.new("L", crop.size, 255))
        crop.save(slide_dir / rel, format="PNG")
        layer_asset = rel
        layer_id = f"{layer_role}_{group_id}"
        layer = {"id": layer_id, "type": "png", "asset": layer_asset, "role": layer_role, "target_group_id": group_id, "visible_text": group.get("visible_text", ""), "box": box, "z_index": int(group.get("z_index", 40 + index))}
        layers.append(layer)
        group = {**group, "reveal": {**reveal, "type": action}}
        events.append(build_event(slide_id, group, layer_id, 0.2 + (index - 1) * 0.7))
        placed.append({"id": group_id, "role": role, "box": box})
    scene = {"slide_id": slide_id, "source_visual_draft": str(master_path), "visual_source": "master_reveal_layers", "canvas": {"width": width, "height": height, "background": background}, "layers": layers, "composition": {"method": "timed_manual_mask_reveal", "algorithmic_full_slide_decomposition": False}}
    duration = max(float(slide.get("default_duration_sec", 12.0)), max((float(e["at"]) + float(e["duration"]) for e in events), default=0.0) + 0.5)
    write_json(slide_dir / "scene.json", scene)
    write_json(slide_dir / "animation_timeline.json", {"slide_id": slide_id, "duration_sec": round(duration, 3), "events": events})
    write_json(slide_dir / "reveal_report.json", {"slide_id": slide_id, "method": "timed_manual_mask_reveal", "warnings": warnings, "group_count": len(groups), "layer_count": len(layers), "fallback_full_slide": False})


def build_manifest(manifest: dict[str, Any], manifest_path: Path, repo_root: Path) -> int:
    if manifest.get("version") != "reveal_v1":
        raise RevealBuildError("Manifest version must be reveal_v1")
    canvas = {**DEFAULT_CANVAS, **(manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {})}
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        raise RevealBuildError("Manifest must contain non-empty slides[]")
    for slide in slides:
        if not isinstance(slide, dict):
            raise RevealBuildError("Each slide must be an object")
        compose_slide(slide, manifest_path.parent, repo_root, canvas)
    return len(slides)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build full-slide reveal scene assets.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = build_manifest(read_json(args.manifest), args.manifest.resolve(), args.repo_root.resolve())
    except RevealBuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Built reveal scene for {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
