#!/usr/bin/env python3
"""
Split an approved Image Gen master slide into same-source macro PNG layers.

This is the default production path for visuals:

1. Generate a complete master slide with Image Gen.
2. Declare 5-8 semantic macro boxes in master_split_manifest.json.
3. Cut those boxes from the master image, create alpha mattes, and recompose a
   preview for QA.

The script does not infer slide semantics. The manifest decides which large
groups exist and where they live. This keeps visual style, scale, handwriting,
and lighting consistent because every production layer comes from the same
master bitmap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageFilter


DEFAULT_CANVAS = {"width": 1920, "height": 1080, "background": "#FFFDF7"}
DEFAULT_ALPHA_POLICY = {
    "transparent_threshold": 18.0,
    "opaque_threshold": 72.0,
    "chroma_threshold": 18.0,
    "darkness_threshold": 20.0,
    "edge_expand_px": 1,
    "edge_blur": 0.35,
    "remove_small_components_px": 36,
}
ENTRY_ACTIONS = {"fade_in", "fade_up", "soft_zoom_in", "slide_in_left"}


class SplitError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SplitError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SplitError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SplitError(f"JSON file must contain an object: {path}")
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
        raise SplitError(f"Invalid hex color: {value}")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def rgb_to_hex(rgb: np.ndarray | tuple[int, int, int]) -> str:
    values = [int(max(0, min(255, round(float(channel))))) for channel in rgb]
    return "#" + "".join(f"{channel:02X}" for channel in values)


def estimate_background_rgb(image: Image.Image) -> np.ndarray:
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    h, w, _ = arr.shape
    patch = max(24, min(w, h) // 18)
    samples = np.vstack(
        [
            arr[:patch, :patch].reshape(-1, 3),
            arr[:patch, -patch:].reshape(-1, 3),
            arr[-patch:, :patch].reshape(-1, 3),
            arr[-patch:, -patch:].reshape(-1, 3),
        ]
    )
    return np.median(samples, axis=0)


def synthetic_paper_background(width: int, height: int, bg_rgb: np.ndarray, seed_text: str) -> Image.Image:
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = np.random.default_rng(seed)
    small_w = max(160, width // 8)
    small_h = max(90, height // 8)
    noise = rng.normal(0, 3.0, size=(small_h, small_w, 1))
    warm = rng.normal(0, 1.2, size=(small_h, small_w, 1))
    base = np.array(bg_rgb, dtype=np.float32).reshape(1, 1, 3)
    arr = base + noise + np.concatenate([warm, np.zeros_like(warm), -warm], axis=2)
    arr = np.clip(arr, 0, 255).astype("uint8")
    return (
        Image.fromarray(arr, "RGB")
        .resize((width, height), Image.Resampling.BICUBIC)
        .filter(ImageFilter.GaussianBlur(0.35))
    )


def remove_small_components(mask: np.ndarray, min_pixels: int) -> np.ndarray:
    if min_pixels <= 0:
        return mask
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    cleaned = mask.copy()
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            coords: list[tuple[int, int]] = []
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            while queue:
                cx, cy = queue.popleft()
                coords.append((cx, cy))
                for nx in (cx - 1, cx, cx + 1):
                    for ny in (cy - 1, cy, cy + 1):
                        if nx == cx and ny == cy:
                            continue
                        if nx < 0 or ny < 0 or nx >= width or ny >= height:
                            continue
                        if visited[ny, nx] or not mask[ny, nx]:
                            continue
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            if len(coords) < min_pixels:
                for cx, cy in coords:
                    cleaned[cy, cx] = False
    return cleaned


def alpha_from_background(crop: Image.Image, bg_rgb: np.ndarray, policy: dict[str, Any]) -> Image.Image:
    arr = np.asarray(crop.convert("RGB")).astype(np.float32)
    diff = np.sqrt(((arr - bg_rgb.reshape(1, 1, 3)) ** 2).sum(axis=2))
    chroma = arr.max(axis=2) - arr.min(axis=2)
    darkness = float(np.mean(bg_rgb)) - arr.mean(axis=2)

    transparent_threshold = float(policy.get("transparent_threshold", DEFAULT_ALPHA_POLICY["transparent_threshold"]))
    opaque_threshold = max(
        transparent_threshold + 1,
        float(policy.get("opaque_threshold", DEFAULT_ALPHA_POLICY["opaque_threshold"])),
    )
    chroma_threshold = float(policy.get("chroma_threshold", DEFAULT_ALPHA_POLICY["chroma_threshold"]))
    darkness_threshold = float(policy.get("darkness_threshold", DEFAULT_ALPHA_POLICY["darkness_threshold"]))

    score = np.maximum.reduce(
        [
            (diff - transparent_threshold) / (opaque_threshold - transparent_threshold),
            (chroma - chroma_threshold) / max(1.0, opaque_threshold - chroma_threshold),
            (darkness - darkness_threshold) / max(1.0, opaque_threshold - darkness_threshold),
        ]
    )
    alpha = np.clip(score * 255.0, 0, 255)

    coarse_mask = alpha > 8
    coarse_mask = remove_small_components(
        coarse_mask,
        int(policy.get("remove_small_components_px", DEFAULT_ALPHA_POLICY["remove_small_components_px"])),
    )
    alpha = np.where(coarse_mask, alpha, 0)

    alpha_img = Image.fromarray(alpha.astype("uint8"), "L")
    edge_expand = int(policy.get("edge_expand_px", DEFAULT_ALPHA_POLICY["edge_expand_px"]))
    for _ in range(max(0, edge_expand)):
        alpha_img = alpha_img.filter(ImageFilter.MaxFilter(3))
    edge_blur = float(policy.get("edge_blur", DEFAULT_ALPHA_POLICY["edge_blur"]))
    if edge_blur > 0:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(edge_blur))
    return alpha_img


def rect_distance(a: dict[str, int], b: dict[str, int]) -> float:
    ax2 = a["x"] + a["w"]
    ay2 = a["y"] + a["h"]
    bx2 = b["x"] + b["w"]
    by2 = b["y"] + b["h"]
    dx = max(b["x"] - ax2, a["x"] - bx2, 0)
    dy = max(b["y"] - ay2, a["y"] - by2, 0)
    return math.hypot(dx, dy)


def intersection_size(a: dict[str, int], b: dict[str, int]) -> tuple[int, int]:
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    y2 = min(a["y"] + a["h"], b["y"] + b["h"])
    return max(0, x2 - x1), max(0, y2 - y1)


def layer_box(raw: dict[str, Any], width: int, height: int, slide_id: str) -> dict[str, int]:
    box = raw.get("box")
    if not isinstance(box, dict):
        raise SplitError(f"Layer missing box in {slide_id}: {raw.get('id')}")
    values = {key: int(round(float(box[key]))) for key in ("x", "y", "w", "h")}
    if values["w"] <= 0 or values["h"] <= 0:
        raise SplitError(f"Layer has non-positive box in {slide_id}: {raw.get('id')}")
    if values["x"] < 0 or values["y"] < 0 or values["x"] + values["w"] > width or values["y"] + values["h"] > height:
        raise SplitError(f"Layer box outside canvas in {slide_id}: {raw.get('id')}: {values}")
    return values


def layout_constraints(slide: dict[str, Any], height: int) -> dict[str, Any]:
    raw = slide.get("layout_constraints")
    constraints = raw if isinstance(raw, dict) else {}
    return {
        "min_macro_layer_gap_px": int(constraints.get("min_macro_layer_gap_px", 48)),
        "overlap_tolerance_px": int(constraints.get("overlap_tolerance_px", 4)),
        "max_visible_overlap_px": int(constraints.get("max_visible_overlap_px", 96)),
        "visible_overlap_alpha_threshold": int(constraints.get("visible_overlap_alpha_threshold", 160)),
        "subtitle_safe_y": int(constraints.get("subtitle_safe_y", round(height * 930 / 1080))),
        "min_content_layers": int(constraints.get("min_content_layers", 4)),
        "max_content_layers": int(constraints.get("max_content_layers", 8)),
    }


def beat_map(slide: dict[str, Any]) -> dict[str, dict[str, Any]]:
    beats = slide.get("narration_beats")
    if not isinstance(beats, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for beat in beats:
        if isinstance(beat, dict) and str(beat.get("id", "")).strip():
            result[str(beat["id"])] = beat
    return result


def build_animation(slide_id: str, layers: list[dict[str, Any]], beats: dict[str, dict[str, Any]], duration: float) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    stagger_index = 0
    for layer in layers:
        if layer["role"] in {"background", "decoration"}:
            continue
        action = str(layer.get("animation", "fade_up"))
        entry_action = str(layer.get("entry_animation") or ("fade_up" if action == "highlight" else action))
        if entry_action == "static":
            entry_action = ""
        if entry_action and entry_action not in ENTRY_ACTIONS:
            entry_action = "fade_up"

        linked_segment_id = layer.get("linked_segment_id")
        narration_beat_id = str(layer.get("narration_beat_id", "")).strip()
        beat = beats.get(narration_beat_id)
        reveal_at = layer.get("reveal_at")
        if isinstance(reveal_at, (int, float)):
            at = max(0.0, float(reveal_at))
        elif beat and isinstance(beat.get("start"), (int, float)):
            at = max(0.0, float(beat["start"]))
        else:
            at = 0.12 + stagger_index * 0.62

        reveal_duration = layer.get("reveal_duration")
        event_duration = float(reveal_duration) if isinstance(reveal_duration, (int, float)) and reveal_duration > 0 else 0.65
        if entry_action:
            event = {
                "id": f"{slide_id}_{layer['id']}_{entry_action}",
                "target": layer["id"],
                "action": entry_action,
                "at": round(at, 3),
                "duration": round(event_duration, 3),
                "easing": "easeOutCubic",
            }
            if linked_segment_id:
                event["linked_segment_id"] = linked_segment_id
            if narration_beat_id:
                event["narration_beat_id"] = narration_beat_id
            events.append(event)
            if not beat and not isinstance(reveal_at, (int, float)):
                stagger_index += 1

        if action == "highlight":
            highlight_at = layer.get("highlight_at")
            if isinstance(highlight_at, (int, float)):
                highlight_start = max(at + event_duration, float(highlight_at))
            elif beat and isinstance(beat.get("end"), (int, float)):
                highlight_start = max(at + event_duration, float(beat["end"]) - 0.4)
            else:
                highlight_start = max(at + event_duration + 0.25, duration - 1.6)
            event = {
                "id": f"{slide_id}_{layer['id']}_highlight",
                "target": layer["id"],
                "action": "highlight",
                "at": round(highlight_start, 3),
                "duration": 1.0,
                "easing": "easeOutCubic",
            }
            if linked_segment_id:
                event["linked_segment_id"] = linked_segment_id
            if narration_beat_id:
                event["narration_beat_id"] = narration_beat_id
            events.append(event)

    return {"slide_id": slide_id, "duration_sec": round(duration, 3), "events": events}


def recomposition_metrics(master: Image.Image, preview: Image.Image, alpha_union: Image.Image) -> dict[str, float]:
    master_arr = np.asarray(master.convert("RGB")).astype(np.float32)
    preview_arr = np.asarray(preview.convert("RGB")).astype(np.float32)
    diff = np.abs(master_arr - preview_arr).mean(axis=2)
    alpha = np.asarray(alpha_union.convert("L"))
    content_mask = alpha > 16
    whole = float(diff.mean())
    content = float(diff[content_mask].mean()) if np.any(content_mask) else whole
    coverage = float(np.count_nonzero(content_mask) / content_mask.size)
    return {
        "whole_mean_abs_diff": round(whole, 4),
        "content_mean_abs_diff": round(content, 4),
        "content_coverage_ratio": round(coverage, 6),
    }


def compose_slide(slide: dict[str, Any], manifest_dir: Path, repo_root: Path, default_canvas: dict[str, Any]) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise SplitError("Slide missing slide_id")

    slide_dir = resolve_path(str(slide["slide_dir"]), manifest_dir, manifest_dir, repo_root)
    assets_dir = slide_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    master_path = resolve_path(str(slide["master"]), manifest_dir, slide_dir, repo_root)
    if not master_path.exists():
        raise SplitError(f"Missing master slide image for {slide_id}: {master_path}")

    master = Image.open(master_path).convert("RGB")
    canvas = {**default_canvas, **slide.get("canvas", {})}
    width = int(canvas.get("width", master.width))
    height = int(canvas.get("height", master.height))
    if (master.width, master.height) != (width, height):
        master = master.resize((width, height), Image.Resampling.LANCZOS)

    master.save(assets_dir / "full_slide.png", format="PNG")
    bg_rgb = estimate_background_rgb(master)
    background_mode = str(slide.get("background_mode", "paper_texture"))
    if background_mode == "solid":
        background = Image.new("RGB", (width, height), hex_to_rgb(str(canvas.get("background", rgb_to_hex(bg_rgb)))))
    else:
        background = synthetic_paper_background(width, height, bg_rgb, f"{slide_id}:{master_path.name}")
    background.save(assets_dir / "background.png", format="PNG")

    constraints = layout_constraints(slide, height)
    beats = beat_map(slide)
    report_warnings: list[dict[str, Any]] = []
    layers_raw = slide.get("layers")
    if not isinstance(layers_raw, list) or not layers_raw:
        raise SplitError(f"Slide has no layers: {slide_id}")

    if not beats:
        report_warnings.append(
            {
                "severity": "warning",
                "type": "missing_narration_beats",
                "message": "No narration_beats were provided; animation will fall back to mechanical staggering.",
            }
        )

    content_count = len([raw for raw in layers_raw if isinstance(raw, dict) and raw.get("role") != "decoration"])
    if content_count < constraints["min_content_layers"] or content_count > constraints["max_content_layers"]:
        report_warnings.append(
            {
                "severity": "warning",
                "type": "macro_layer_count_out_of_range",
                "message": (
                    f"Expected {constraints['min_content_layers']}-{constraints['max_content_layers']} "
                    f"content macro layers, got {content_count}."
                ),
            }
        )

    preview = background.convert("RGBA")
    alpha_union = Image.new("L", (width, height), 0)
    scene_layers: list[dict[str, Any]] = [
        {
            "id": "background_layer",
            "type": "png",
            "asset": "assets/background.png",
            "role": "background",
            "box": {"x": 0, "y": 0, "w": width, "h": height},
            "z_index": 0,
            "animation_role": "static_background",
        }
    ]
    placed: list[dict[str, Any]] = []
    base_alpha_policy = {**DEFAULT_ALPHA_POLICY, **(slide.get("alpha_policy") if isinstance(slide.get("alpha_policy"), dict) else {})}

    for index, raw in enumerate(layers_raw, start=1):
        if not isinstance(raw, dict):
            raise SplitError(f"Invalid layer entry in {slide_id}")
        layer_id = str(raw.get("id", "")).strip()
        if not layer_id:
            raise SplitError(f"Layer missing id in {slide_id}")
        role = str(raw.get("role", "content_body"))
        box = layer_box(raw, width, height, slide_id)
        if role != "decoration" and box["y"] + box["h"] > constraints["subtitle_safe_y"]:
            report_warnings.append(
                {
                    "severity": "blocking",
                    "type": "subtitle_safe_zone_violation",
                    "layer_id": layer_id,
                    "message": f"Layer bottom {box['y'] + box['h']} exceeds subtitle_safe_y {constraints['subtitle_safe_y']}.",
                }
            )
        for existing in placed:
            if role == "decoration" or existing["role"] == "decoration":
                continue
            overlap_w, overlap_h = intersection_size(box, existing["box"])
            if overlap_w > constraints["overlap_tolerance_px"] and overlap_h > constraints["overlap_tolerance_px"]:
                report_warnings.append(
                    {
                        "severity": "warning",
                        "type": "macro_layer_box_overlap",
                        "layer_id": layer_id,
                        "other_layer_id": existing["id"],
                        "message": (
                            f"Boxes overlap by {overlap_w}x{overlap_h}px. "
                            "This is acceptable only if visible alpha pixels do not overlap."
                        ),
                    }
                )
            elif rect_distance(box, existing["box"]) < constraints["min_macro_layer_gap_px"]:
                report_warnings.append(
                    {
                        "severity": "warning",
                        "type": "macro_layer_gap_too_small",
                        "layer_id": layer_id,
                        "other_layer_id": existing["id"],
                        "message": (
                            f"Independent macro layers are closer than "
                            f"{constraints['min_macro_layer_gap_px']}px."
                        ),
                    }
                )

        crop = master.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]))
        policy = {**base_alpha_policy, **(raw.get("alpha_policy") if isinstance(raw.get("alpha_policy"), dict) else {})}
        rgba = crop.convert("RGBA")
        rgba.putalpha(alpha_from_background(crop, bg_rgb, policy))
        asset_name = str(raw.get("asset", f"{layer_id}.png"))
        asset_path = assets_dir / asset_name
        rgba.save(asset_path, format="PNG")
        preview.alpha_composite(rgba, (box["x"], box["y"]))
        layer_alpha_full = Image.new("L", (width, height), 0)
        layer_alpha_full.paste(rgba.getchannel("A"), (box["x"], box["y"]))
        if role != "decoration":
            alpha_threshold = int(constraints["visible_overlap_alpha_threshold"])
            current_alpha = np.asarray(layer_alpha_full) > alpha_threshold
            for existing in placed:
                if existing["role"] == "decoration":
                    continue
                visible_overlap = int(np.count_nonzero(current_alpha & existing["alpha_mask"]))
                if visible_overlap > constraints["max_visible_overlap_px"]:
                    report_warnings.append(
                        {
                            "severity": "blocking",
                            "type": "visible_layer_overlap",
                            "layer_id": layer_id,
                            "other_layer_id": existing["id"],
                            "message": (
                                f"Visible alpha overlap is {visible_overlap}px, above "
                                f"max_visible_overlap_px={constraints['max_visible_overlap_px']}."
                            ),
                        }
                    )
        alpha_union = ImageChops.lighter(alpha_union, layer_alpha_full)

        if role != "decoration":
            beat_id = str(raw.get("narration_beat_id", "")).strip()
            if not beat_id:
                report_warnings.append(
                    {
                        "severity": "warning",
                        "type": "layer_missing_narration_beat",
                        "layer_id": layer_id,
                        "message": "Layer has no narration_beat_id; animation timing may not match the voiceover.",
                    }
                )
            elif beat_id not in beats:
                report_warnings.append(
                    {
                        "severity": "blocking",
                        "type": "unknown_narration_beat",
                        "layer_id": layer_id,
                        "message": f"Layer references missing narration beat: {beat_id}.",
                    }
                )

        scene_layer = {
            "id": layer_id,
            "type": "png",
            "asset": f"assets/{asset_name}",
            "role": role,
            "box": box,
            "z_index": int(raw.get("z_index", 20 + index)),
            "animation_role": str(raw.get("animation", role)),
            "animation": str(raw.get("animation", "fade_up")),
        }
        for key in (
            "entry_animation",
            "reveal_at",
            "reveal_duration",
            "highlight_at",
            "linked_segment_id",
            "narration_beat_id",
            "text_summary",
            "narration_cue",
        ):
            if key in raw:
                scene_layer[key] = raw[key]
        scene_layers.append(scene_layer)
        placed.append(
            {
                "id": layer_id,
                "role": role,
                "box": box,
                "alpha_mask": np.asarray(layer_alpha_full) > int(constraints["visible_overlap_alpha_threshold"]),
            }
        )

    preview_rgb = preview.convert("RGB")
    preview_rgb.save(slide_dir / "render_preview.png", format="PNG")
    metrics = recomposition_metrics(master, preview_rgb, alpha_union)

    scene = {
        "slide_id": slide_id,
        "source_visual_draft": str(master_path),
        "visual_source": "master_split_image_layers",
        "canvas": {"width": width, "height": height, "background": str(canvas.get("background", rgb_to_hex(bg_rgb)))},
        "layers": scene_layers,
        "composition": {
            "method": "master_image_same_source_macro_split",
            "semantic_decomposition": "manifest_declared_macro_boxes",
            "algorithmic_full_slide_decomposition": False,
            "requires_recomposition_review": True,
        },
    }
    write_json(slide_dir / "scene.json", scene)
    duration = float(slide.get("default_duration_sec", 12.0))
    write_json(slide_dir / "animation_timeline.json", build_animation(slide_id, scene_layers, beats, duration))
    write_json(
        slide_dir / "split_report.json",
        {
            "slide_id": slide_id,
            "method": "master_image_same_source_macro_split",
            "master": str(master_path),
            "background_rgb": [round(float(value), 2) for value in bg_rgb],
            "constraints": constraints,
            "metrics": metrics,
            "warnings": report_warnings,
            "content_layer_count": content_count,
        },
    )


def split_manifest(manifest: dict[str, Any], manifest_path: Path, repo_root: Path) -> int:
    if manifest.get("version") != "master_split_v1":
        raise SplitError("Manifest version must be master_split_v1")
    default_canvas = {**DEFAULT_CANVAS, **(manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {})}
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        raise SplitError("Manifest must contain non-empty slides[]")
    for slide in slides:
        if not isinstance(slide, dict):
            raise SplitError("Each slide must be an object")
        compose_slide(slide, manifest_path.parent, repo_root, default_canvas)
    return len(slides)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split Image Gen master slides into same-source PNG macro layers.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = split_manifest(read_json(args.manifest), args.manifest.resolve(), args.repo_root.resolve())
    except SplitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Split {count} slide(s) from Image Gen master images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
