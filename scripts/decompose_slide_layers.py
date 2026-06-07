#!/usr/bin/env python3
"""
Decompose Codex Image Gen full-slide PNGs into Remotion-ready PNG layers.

The production rule is: slide content is still created by Codex Image Gen, then
this script crops foreground regions out of the approved bitmap and writes PNG
layers plus a layer-based animation timeline. It does not redraw text, shapes,
arrows, icons, or charts with code.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_BG = (255, 253, 247)

TITLE_MARKER_REGION = (25, 25, 95, 170)
TITLE_REGION = (80, 25, 1780, 132)
SUBTITLE_REGION = (80, 132, 1780, 230)
CONTENT_REGION = (80, 235, 1840, 915)
SUBTITLE_SAFE_Y = 930


class DecomposeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Box:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def w(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def h(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.w * self.h

    def padded(self, pad: int, width: int, height: int) -> "Box":
        return Box(
            max(0, self.x1 - pad),
            max(0, self.y1 - pad),
            min(width, self.x2 + pad),
            min(height, self.y2 + pad),
        )

    def to_scene_box(self) -> dict[str, int]:
        return {"x": self.x1, "y": self.y1, "w": self.w, "h": self.h}


@dataclass
class Component:
    box: Box
    pixels: int


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DecomposeError(f"Missing required JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DecomposeError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DecomposeError(f"JSON file must contain an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slide_sort_key(path: Path) -> tuple[int, str]:
    suffix = path.name.rsplit("_", 1)[-1]
    return (int(suffix), path.name) if suffix.isdigit() else (999999, path.name)


def normalize_image(source: Path, destination: Path, width: int, height: int, optimize_png: bool) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = image.convert("RGB")
        if image.size != (width, height):
            source_ratio = image.width / image.height
            target_ratio = width / height
            if abs(source_ratio - target_ratio) > 0.015:
                raise DecomposeError(
                    f"Visual draft aspect ratio must be 16:9 before resize: {source} "
                    f"has {image.width}x{image.height}"
                )
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        image.save(destination, format="PNG", optimize=optimize_png)


def load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def estimate_background(rgb: np.ndarray) -> tuple[int, int, int]:
    height, width, _ = rgb.shape
    samples = np.concatenate(
        [
            rgb[:40, :, :].reshape(-1, 3),
            rgb[height - 40 :, :, :].reshape(-1, 3),
            rgb[:, :40, :].reshape(-1, 3),
            rgb[:, width - 40 :, :].reshape(-1, 3),
            rgb[940:height, 120:width - 120, :].reshape(-1, 3),
        ],
        axis=0,
    )
    max_channel = samples.max(axis=1)
    min_channel = samples.min(axis=1)
    luma = samples.mean(axis=1)
    quiet = samples[(luma > 225) & ((max_channel - min_channel) < 45)]
    if len(quiet) < 1000:
        quiet = samples[luma > 215]
    if len(quiet) < 1000:
        return DEFAULT_BG
    median = np.median(quiet, axis=0)
    return tuple(int(round(v)) for v in median)


def foreground_masks(image: Image.Image, bg: tuple[int, int, int]) -> tuple[Image.Image, Image.Image]:
    rgb = np.asarray(image).astype(np.int32)
    bg_arr = np.asarray(bg, dtype=np.int32)
    diff = np.sqrt(((rgb - bg_arr) ** 2).sum(axis=2))
    luma = rgb.mean(axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)

    coarse = ((diff > 20) | (luma < 238) | ((chroma > 24) & (diff > 12))).astype(np.uint8) * 255
    precise = ((diff > 10) | (luma < 248) | ((chroma > 18) & (diff > 8))).astype(np.uint8) * 255

    coarse_img = Image.fromarray(coarse, mode="L").filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(5))
    precise_img = Image.fromarray(precise, mode="L").filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(0.8))
    return coarse_img, precise_img


def foreground_pixels_in_box(mask: Image.Image, box: Box) -> int:
    crop = np.asarray(mask.crop((box.x1, box.y1, box.x2, box.y2))) > 0
    return int(crop.sum())


def bbox_from_mask(mask: Image.Image, region: tuple[int, int, int, int], padding: int, min_pixels: int) -> Component | None:
    x1, y1, x2, y2 = region
    crop = np.asarray(mask.crop(region)) > 0
    ys, xs = np.nonzero(crop)
    if len(xs) < min_pixels:
        return None
    box = Box(
        int(x1 + xs.min()),
        int(y1 + ys.min()),
        int(x1 + xs.max() + 1),
        int(y1 + ys.max() + 1),
    ).padded(padding, mask.width, mask.height)
    return Component(box=box, pixels=int(len(xs)))


def connected_components(mask: Image.Image, region: tuple[int, int, int, int], min_pixels: int) -> list[Component]:
    x1, y1, _x2, _y2 = region
    crop = np.asarray(mask.crop(region)) > 0
    height, width = crop.shape
    visited = np.zeros_like(crop, dtype=bool)
    components: list[Component] = []
    ys, xs = np.nonzero(crop)

    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue
        queue: deque[tuple[int, int]] = deque([(start_y, start_x)])
        visited[start_y, start_x] = True
        count = 0
        min_x = max_x = start_x
        min_y = max_y = start_y

        while queue:
            y, x = queue.popleft()
            count += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

            for ny in (y - 1, y, y + 1):
                if ny < 0 or ny >= height:
                    continue
                for nx in (x - 1, x, x + 1):
                    if nx < 0 or nx >= width or visited[ny, nx] or not crop[ny, nx]:
                        continue
                    visited[ny, nx] = True
                    queue.append((ny, nx))

        if count >= min_pixels:
            components.append(
                Component(
                    box=Box(x1 + min_x, y1 + min_y, x1 + max_x + 1, y1 + max_y + 1),
                    pixels=count,
                )
            )

    return components


def intersects(a: Box, b: Box) -> bool:
    return a.x1 < b.x2 and a.x2 > b.x1 and a.y1 < b.y2 and a.y2 > b.y1


def union_box(a: Box, b: Box) -> Box:
    return Box(min(a.x1, b.x1), min(a.y1, b.y1), max(a.x2, b.x2), max(a.y2, b.y2))


def merge_close_components(components: list[Component], width: int, height: int, padding: int) -> list[Component]:
    merged = [Component(box=item.box.padded(10, width, height), pixels=item.pixels) for item in components]
    changed = True
    while changed:
        changed = False
        next_items: list[Component] = []
        used = [False] * len(merged)

        for index, item in enumerate(merged):
            if used[index]:
                continue
            current = item
            used[index] = True
            expanded = current.box.padded(padding, width, height)
            for other_index in range(index + 1, len(merged)):
                if used[other_index]:
                    continue
                other = merged[other_index]
                if intersects(expanded, other.box):
                    current = Component(box=union_box(current.box, other.box), pixels=current.pixels + other.pixels)
                    expanded = current.box.padded(padding, width, height)
                    used[other_index] = True
                    changed = True
            next_items.append(current)
        merged = next_items

    return sorted(merged, key=lambda item: (item.box.y1, item.box.x1))


def low_runs(values: np.ndarray, threshold: int, min_run: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values.tolist()):
        if value <= threshold:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= min_run:
                runs.append((start, index))
            start = None
    if start is not None and len(values) - start >= min_run:
        runs.append((start, len(values)))
    return runs


def best_projection_cut(crop: np.ndarray, box: Box) -> tuple[str, int, int] | None:
    if crop.sum() < 1200:
        return None

    candidates: list[tuple[int, str, int]] = []
    min_piece_w = 170
    min_piece_h = 95
    min_run = 24

    column_counts = crop.sum(axis=0)
    column_threshold = max(18, int(crop.shape[0] * 0.34))
    for start, end in low_runs(column_counts, threshold=column_threshold, min_run=min_run):
        cut = (start + end) // 2
        if cut < min_piece_w or crop.shape[1] - cut < min_piece_w:
            continue
        left_pixels = int(crop[:, :cut].sum())
        right_pixels = int(crop[:, cut:].sum())
        if left_pixels < 900 or right_pixels < 900:
            continue
        candidates.append((end - start, "x", box.x1 + cut))

    row_counts = crop.sum(axis=1)
    row_threshold = max(18, int(crop.shape[1] * 0.18))
    for start, end in low_runs(row_counts, threshold=row_threshold, min_run=min_run):
        cut = (start + end) // 2
        if cut < min_piece_h or crop.shape[0] - cut < min_piece_h:
            continue
        top_pixels = int(crop[:cut, :].sum())
        bottom_pixels = int(crop[cut:, :].sum())
        if top_pixels < 900 or bottom_pixels < 900:
            continue
        candidates.append((end - start, "y", box.y1 + cut))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])


def projection_split_box(
    mask: Image.Image,
    box: Box,
    max_depth: int,
    max_pieces: int,
    width: int,
    height: int,
) -> list[Box]:
    pieces: list[Box] = []

    def recurse(current: Box, depth: int) -> None:
        if len(pieces) >= max_pieces:
            pieces.append(current)
            return
        if depth >= max_depth or current.w < 330 or current.h < 170:
            pieces.append(current)
            return

        crop = np.asarray(mask.crop((current.x1, current.y1, current.x2, current.y2))) > 0
        cut = best_projection_cut(crop, current)
        if cut is None:
            pieces.append(current)
            return

        _score, axis, value = cut
        if axis == "x":
            left = Box(current.x1, current.y1, value, current.y2).padded(6, width, height)
            right = Box(value, current.y1, current.x2, current.y2).padded(6, width, height)
            recurse(left, depth + 1)
            recurse(right, depth + 1)
        else:
            top = Box(current.x1, current.y1, current.x2, value).padded(6, width, height)
            bottom = Box(current.x1, value, current.x2, current.y2).padded(6, width, height)
            recurse(top, depth + 1)
            recurse(bottom, depth + 1)

    recurse(box, 0)
    deduped: list[Box] = []
    for piece in pieces:
        if foreground_pixels_in_box(mask, piece) < 900:
            continue
        if not any(overlap_ratio(piece, existing) > 0.96 for existing in deduped):
            deduped.append(piece)
    return sorted(deduped[:max_pieces], key=lambda item: (item.y1, item.x1))


def split_large_connected_components(
    components: list[Component],
    mask: Image.Image,
    width: int,
    height: int,
) -> tuple[list[Component], bool]:
    if len(components) != 1:
        return components, False

    component = components[0]
    if component.box.w < 900 and component.box.h < 380:
        return components, False

    boxes = projection_split_box(
        mask=mask,
        box=component.box.padded(8, width, height),
        max_depth=4,
        max_pieces=8,
        width=width,
        height=height,
    )
    if len(boxes) <= 1:
        return components, False

    return [
        Component(box=box, pixels=foreground_pixels_in_box(mask, box))
        for box in boxes
    ], True


def is_outer_frame(component: Component, content_region: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = content_region
    region_w = x2 - x1
    region_h = y2 - y1
    box = component.box
    fill_ratio = component.pixels / max(1, box.area)
    return box.w > region_w * 0.82 and box.h > region_h * 0.55 and fill_ratio < 0.09


def role_for_content(box: Box) -> str:
    if box.y1 >= 700 and box.w >= 650:
        return "summary"
    if box.w >= 620 or box.h >= 230:
        return "content_body"
    if box.h <= 150 and box.w <= 620:
        return "annotation"
    return "diagram"


def save_background(asset_path: Path, width: int, height: int, bg: tuple[int, int, int], optimize_png: bool) -> None:
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), bg).save(asset_path, format="PNG", optimize=optimize_png)


def save_cutout(
    image: Image.Image,
    alpha: Image.Image,
    box: Box,
    destination: Path,
    optimize_png: bool,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    crop = image.crop((box.x1, box.y1, box.x2, box.y2)).convert("RGBA")
    alpha_crop = alpha.crop((box.x1, box.y1, box.x2, box.y2))
    crop.putalpha(alpha_crop)
    crop.save(destination, format="PNG", optimize=optimize_png)


def audio_duration(slide_dir: Path, default_duration_sec: float) -> float:
    timeline_path = slide_dir / "audio_timeline.json"
    if not timeline_path.exists():
        return default_duration_sec
    timeline = read_json(timeline_path)
    duration = timeline.get("duration_sec")
    if isinstance(duration, (int, float)) and duration > 0:
        return round(float(duration), 3)
    segment_ends = [
        float(segment["end"])
        for segment in timeline.get("segments", [])
        if isinstance(segment, dict) and isinstance(segment.get("end"), (int, float))
    ]
    return round(max(segment_ends, default=default_duration_sec), 3)


def build_animation(slide_id: str, layers: list[dict[str, Any]], duration_sec: float) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    content_layers = [
        layer
        for layer in layers
        if layer["role"] not in {"background", "decoration"} and layer["id"] not in {"title_marker_layer"}
    ]
    title_layers = [layer for layer in content_layers if layer["role"] in {"title", "subtitle"}]
    body_layers = [layer for layer in content_layers if layer["role"] not in {"title", "subtitle"}]

    for index, layer in enumerate(title_layers):
        events.append(
            {
                "id": f"{slide_id}_{layer['id']}_appear",
                "target": layer["id"],
                "action": "fade_in",
                "at": round(index * 0.14, 3),
                "duration": 0.45,
                "easing": "easeOutCubic",
            }
        )

    start = 0.55
    usable = max(1.0, duration_sec - 2.4)
    interval = min(0.95, max(0.38, usable / max(1, len(body_layers) + 1)))
    for index, layer in enumerate(body_layers):
        role = layer["role"]
        action = "soft_zoom_in" if role == "diagram" else "fade_up"
        if role == "annotation":
            action = "slide_in_left"
        events.append(
            {
                "id": f"{slide_id}_{layer['id']}_appear",
                "target": layer["id"],
                "action": action,
                "at": round(start + index * interval, 3),
                "duration": 0.58,
                "easing": "easeOutCubic",
            }
        )
        if role == "summary":
            events.append(
                {
                    "id": f"{slide_id}_{layer['id']}_highlight",
                    "target": layer["id"],
                    "action": "highlight",
                    "at": round(max(start + index * interval + 0.75, duration_sec - 2.0), 3),
                    "duration": 1.1,
                    "easing": "easeOutCubic",
                }
            )

    return {"slide_id": slide_id, "duration_sec": duration_sec, "events": events}


def overlap_ratio(a: Box, b: Box) -> float:
    x1 = max(a.x1, b.x1)
    y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2)
    y2 = min(a.y2, b.y2)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    return overlap / max(1, min(a.area, b.area))


def build_overlap_warnings(layers: list[dict[str, Any]], max_ratio: float) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    boxes: list[tuple[str, Box]] = []
    for layer in layers:
        if layer.get("role") in {"background", "decoration"}:
            continue
        box = layer["box"]
        boxes.append((str(layer["id"]), Box(int(box["x"]), int(box["y"]), int(box["x"] + box["w"]), int(box["y"] + box["h"]))))
    for index, (left_id, left_box) in enumerate(boxes):
        for right_id, right_box in boxes[index + 1 :]:
            ratio = overlap_ratio(left_box, right_box)
            if ratio > max_ratio:
                warnings.append(
                    {
                        "type": "layer_bbox_overlap",
                        "left": left_id,
                        "right": right_id,
                        "ratio": round(ratio, 4),
                        "message": "Layer bounding boxes overlap; visual draft may need more spacing or this pair should remain one grouped layer.",
                    }
                )
    return warnings


def layer_entry(
    layer_id: str,
    asset: str,
    role: str,
    box: Box,
    z_index: int,
    animation_role: str,
    content_index: int | None = None,
    source_pixels: int | None = None,
) -> dict[str, Any]:
    layer: dict[str, Any] = {
        "id": layer_id,
        "type": "png",
        "asset": asset,
        "role": role,
        "box": box.to_scene_box(),
        "z_index": z_index,
        "animation_role": animation_role,
        "source_box": box.to_scene_box(),
        "extraction_method": "foreground_mask_crop",
    }
    if content_index is not None:
        layer["content_index"] = content_index
    if source_pixels is not None:
        layer["foreground_pixels"] = source_pixels
    return layer


def extract_fixed_layer(
    image: Image.Image,
    alpha: Image.Image,
    mask: Image.Image,
    region: tuple[int, int, int, int],
    layer_id: str,
    asset_name: str,
    role: str,
    z_index: int,
    animation_role: str,
    optimize_png: bool,
    slide_assets: Path,
    min_pixels: int,
) -> dict[str, Any] | None:
    component = bbox_from_mask(mask, region, padding=12, min_pixels=min_pixels)
    if component is None:
        return None
    asset_path = slide_assets / asset_name
    save_cutout(image, alpha, component.box, asset_path, optimize_png=optimize_png)
    return layer_entry(
        layer_id=layer_id,
        asset=f"assets/{asset_name}",
        role=role,
        box=component.box,
        z_index=z_index,
        animation_role=animation_role,
        source_pixels=component.pixels,
    )


def decompose_slide(
    slide_dir: Path,
    visual_filename: str,
    width: int,
    height: int,
    default_duration_sec: float,
    optimize_png: bool,
    overwrite: bool,
    max_overlap_ratio: float,
) -> None:
    visual_draft = slide_dir / visual_filename
    if not visual_draft.exists():
        raise DecomposeError(f"Missing visual draft: {visual_draft}")
    if visual_draft.suffix.lower() != ".png":
        raise DecomposeError(f"Visual draft must be PNG: {visual_draft}")

    assets_dir = slide_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    full_slide_path = assets_dir / "full_slide.png"
    if overwrite or not full_slide_path.exists():
        normalize_image(visual_draft, full_slide_path, width=width, height=height, optimize_png=optimize_png)

    image = load_rgb(full_slide_path)
    rgb = np.asarray(image)
    bg = estimate_background(rgb)
    coarse_mask, alpha_mask = foreground_masks(image, bg)

    layers: list[dict[str, Any]] = []
    background_asset = assets_dir / "background.png"
    if overwrite or not background_asset.exists():
        save_background(background_asset, width, height, bg, optimize_png=optimize_png)
    layers.append(
        {
            "id": "background_layer",
            "type": "png",
            "asset": "assets/background.png",
            "role": "background",
            "box": {"x": 0, "y": 0, "w": width, "h": height},
            "z_index": 0,
            "animation_role": "static_background",
        }
    )

    fixed_specs = [
        (TITLE_MARKER_REGION, "title_marker_layer", "title_marker.png", "decoration", 5, "title_marker", 90),
        (TITLE_REGION, "title_layer", "title.png", "title", 20, "title", 600),
        (SUBTITLE_REGION, "subtitle_layer", "subtitle.png", "subtitle", 21, "subtitle", 250),
    ]
    for region, layer_id, asset_name, role, z_index, animation_role, min_pixels in fixed_specs:
        layer = extract_fixed_layer(
            image=image,
            alpha=alpha_mask,
            mask=coarse_mask,
            region=region,
            layer_id=layer_id,
            asset_name=asset_name,
            role=role,
            z_index=z_index,
            animation_role=animation_role,
            optimize_png=optimize_png,
            slide_assets=assets_dir,
            min_pixels=min_pixels,
        )
        if layer:
            layers.append(layer)

    raw_components = connected_components(coarse_mask, CONTENT_REGION, min_pixels=260)
    frame_components = [item for item in raw_components if is_outer_frame(item, CONTENT_REGION)]
    content_components = [item for item in raw_components if item not in frame_components]
    merged_components = merge_close_components(content_components, width=width, height=height, padding=34)
    merged_components = [
        item
        for item in merged_components
        if item.box.y2 < SUBTITLE_SAFE_Y and item.box.area >= 900 and item.box.w >= 20 and item.box.h >= 20
    ]
    merged_components, projection_split_used = split_large_connected_components(
        merged_components,
        mask=coarse_mask,
        width=width,
        height=height,
    )

    if frame_components:
        frame = max(frame_components, key=lambda item: item.pixels)
        frame_box = frame.box.padded(8, width, height)
        save_cutout(image, alpha_mask, frame_box, assets_dir / "content_frame.png", optimize_png=optimize_png)
        layers.append(
            layer_entry(
                layer_id="content_frame_layer",
                asset="assets/content_frame.png",
                role="decoration",
                box=frame_box,
                z_index=8,
                animation_role="static_decoration",
                source_pixels=frame.pixels,
            )
        )

    for index, component in enumerate(merged_components, start=1):
        box = component.box.padded(8, width, height)
        role = role_for_content(box)
        asset_name = f"content_{index:02d}.png"
        save_cutout(image, alpha_mask, box, assets_dir / asset_name, optimize_png=optimize_png)
        layers.append(
            layer_entry(
                layer_id=f"content_{index:02d}_layer",
                asset=f"assets/{asset_name}",
                role=role,
                box=box,
                z_index=30 + index,
                animation_role=role,
                content_index=index,
                source_pixels=component.pixels,
            )
        )

    warnings: list[dict[str, Any]] = []
    if not merged_components:
        warnings.append(
            {
                "type": "no_content_components",
                "message": "No separable content components were detected. Regenerate the visual draft with more whitespace between elements.",
            }
        )
    if len(merged_components) == 1:
        warnings.append(
            {
                "type": "single_content_group",
                "message": "Only one content group was detected. Animation will be limited; regenerate with clearer separation if per-element motion is needed.",
            }
        )
    if projection_split_used:
        warnings.append(
            {
                "type": "projection_split_used",
                "message": "A large connected content group was split by whitespace projection. Regenerate with cleaner separation if line breaks look awkward.",
            }
        )
    warnings.extend(build_overlap_warnings(layers, max_ratio=max_overlap_ratio))

    scene = {
        "slide_id": slide_dir.name,
        "source_visual_draft": str(visual_draft).replace("\\", "/"),
        "visual_source": "codex_image_gen_png_layers",
        "canvas": {
            "width": width,
            "height": height,
            "background": f"#{bg[0]:02X}{bg[1]:02X}{bg[2]:02X}",
        },
        "layers": layers,
        "decomposition": {
            "method": "foreground_mask_connected_components",
            "background_color": {"r": bg[0], "g": bg[1], "b": bg[2]},
            "content_region": {"x": CONTENT_REGION[0], "y": CONTENT_REGION[1], "w": CONTENT_REGION[2] - CONTENT_REGION[0], "h": CONTENT_REGION[3] - CONTENT_REGION[1]},
            "subtitle_safe_y": SUBTITLE_SAFE_Y,
            "raw_component_count": len(raw_components),
            "content_component_count": len(merged_components),
            "frame_component_count": len(frame_components),
            "projection_split_used": projection_split_used,
            "warnings": warnings,
        },
    }
    write_json(slide_dir / "scene.json", scene)

    duration_sec = audio_duration(slide_dir, default_duration_sec=default_duration_sec)
    animation = build_animation(slide_id=slide_dir.name, layers=layers, duration_sec=duration_sec)
    write_json(slide_dir / "animation_timeline.json", animation)

    report = {
        "slide_id": slide_dir.name,
        "source": str(visual_draft).replace("\\", "/"),
        "full_slide_asset": "assets/full_slide.png",
        "layer_count": len(layers),
        "content_layer_count": len(merged_components),
        "warnings": warnings,
        "layers": [
            {
                "id": layer["id"],
                "role": layer["role"],
                "asset": layer["asset"],
                "box": layer["box"],
                "foreground_pixels": layer.get("foreground_pixels"),
            }
            for layer in layers
        ],
    }
    write_json(slide_dir / "decomposition_report.json", report)


def decompose_run(
    run_dir: Path,
    visual_filename: str,
    width: int,
    height: int,
    default_duration_sec: float,
    optimize_png: bool,
    overwrite: bool,
    max_overlap_ratio: float,
) -> int:
    slides_dir = run_dir / "slides"
    if not slides_dir.exists():
        raise DecomposeError(f"Missing slides directory: {slides_dir}")

    slide_dirs = sorted([path for path in slides_dir.iterdir() if path.is_dir()], key=slide_sort_key)
    if not slide_dirs:
        raise DecomposeError(f"No slide directories found in: {slides_dir}")

    for slide_dir in slide_dirs:
        decompose_slide(
            slide_dir=slide_dir,
            visual_filename=visual_filename,
            width=width,
            height=height,
            default_duration_sec=default_duration_sec,
            optimize_png=optimize_png,
            overwrite=overwrite,
            max_overlap_ratio=max_overlap_ratio,
        )

    return len(slide_dirs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decompose full-slide PNG visual drafts into Remotion PNG layers.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--visual-filename", default="visual_draft.png")
    parser.add_argument("--width", default=DEFAULT_WIDTH, type=int)
    parser.add_argument("--height", default=DEFAULT_HEIGHT, type=int)
    parser.add_argument("--default-duration-sec", default=12.0, type=float)
    parser.add_argument("--max-overlap-ratio", default=0.18, type=float)
    parser.add_argument("--optimize-png", action="store_true", help="Enable slower PNG compression optimization.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = decompose_run(
            run_dir=args.run_dir.resolve(),
            visual_filename=args.visual_filename,
            width=args.width,
            height=args.height,
            default_duration_sec=args.default_duration_sec,
            optimize_png=args.optimize_png,
            overwrite=args.overwrite,
            max_overlap_ratio=args.max_overlap_ratio,
        )
    except DecomposeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Decomposed {count} slide visual(s) into PNG layers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
