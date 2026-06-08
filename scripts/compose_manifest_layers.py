#!/usr/bin/env python3
"""
Compose Image Gen-produced macro layer images into a Remotion scene.

This script is intentionally not an algorithmic slide decomposer. It does not
infer semantic layers from a full-slide bitmap. Each content layer must already
exist as a separate Image Gen/Web-generated PNG and be declared in a manifest.
The script only trims empty white margins, keys out white layer backgrounds,
places the generated layers into fixed boxes, and writes scene/timeline files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter


class ComposeError(RuntimeError):
    pass


DEFAULT_CANVAS = {"width": 1920, "height": 1080, "background": "#FFFDF7"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ComposeError(f"Missing manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ComposeError(f"Invalid manifest JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ComposeError(f"Manifest must contain an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(value: str, manifest_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (manifest_dir / path, repo_root / path):
        if candidate.exists():
            return candidate
    return repo_root / path


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ComposeError(f"Invalid hex color: {value}")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def nonwhite_bbox(image: Image.Image, threshold: int = 246, pad: int = 24) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    arr = np.asarray(rgb).astype(np.int16)
    chroma = arr.max(axis=2) - arr.min(axis=2)
    mask = (
        (arr[:, :, 0] < threshold)
        | (arr[:, :, 1] < threshold)
        | (arr[:, :, 2] < threshold)
        | (chroma > 14)
    )
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return (0, 0, image.width, image.height)
    return (
        max(0, int(xs.min()) - pad),
        max(0, int(ys.min()) - pad),
        min(image.width, int(xs.max() + 1) + pad),
        min(image.height, int(ys.max() + 1) + pad),
    )


def alpha_from_white(image: Image.Image, diff_threshold: float, alpha_scale: float, edge_blur: float) -> Image.Image:
    rgb = image.convert("RGB")
    arr = np.asarray(rgb).astype(np.int16)
    corner = 20
    samples = np.vstack(
        [
            arr[:corner, :corner].reshape(-1, 3),
            arr[:corner, -corner:].reshape(-1, 3),
            arr[-corner:, :corner].reshape(-1, 3),
            arr[-corner:, -corner:].reshape(-1, 3),
        ]
    )
    bg = np.median(samples, axis=0)
    diff = np.sqrt(((arr - bg) ** 2).sum(axis=2))
    chroma = arr.max(axis=2) - arr.min(axis=2)
    alpha = np.clip((diff - diff_threshold) * alpha_scale, 0, 255)
    alpha = np.maximum(alpha, np.clip((chroma - diff_threshold) * alpha_scale, 0, 255))
    alpha_img = Image.fromarray(alpha.astype("uint8"), "L")
    if edge_blur > 0:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(edge_blur))
    return alpha_img


def prepare_layer_image(
    source: Path,
    width: int,
    height: int,
    key_white: bool,
    alpha_policy: dict[str, Any],
) -> Image.Image:
    if not source.exists():
        raise ComposeError(f"Missing layer source image: {source}")
    with Image.open(source) as image:
        image = image.convert("RGB")
        if bool(alpha_policy.get("trim_white_margin", True)):
            image = image.crop(nonwhite_bbox(image, pad=int(alpha_policy.get("trim_padding_px", 24))))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        rgba = image.convert("RGBA")
        if key_white:
            rgba.putalpha(
                alpha_from_white(
                    image,
                    diff_threshold=float(alpha_policy.get("diff_threshold", 8)),
                    alpha_scale=float(alpha_policy.get("alpha_scale", 8)),
                    edge_blur=float(alpha_policy.get("edge_blur", 0.45)),
                )
            )
        return rgba


def write_background(asset_path: Path, canvas: dict[str, Any], background_source: Path | None = None) -> None:
    width = int(canvas["width"])
    height = int(canvas["height"])
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    if background_source:
        with Image.open(background_source) as image:
            image = image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
            image.save(asset_path, format="PNG")
        return
    color = hex_to_rgb(str(canvas.get("background", "#FFFDF7")))
    Image.new("RGB", (width, height), color).save(asset_path, format="PNG")


def read_duration(slide_dir: Path, default_duration: float) -> float:
    timeline_path = slide_dir / "audio_timeline.json"
    if not timeline_path.exists():
        return default_duration
    timeline = read_json(timeline_path)
    duration = timeline.get("duration_sec")
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)
    return default_duration


def intersection_size(a: dict[str, int], b: dict[str, int]) -> tuple[int, int]:
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    y2 = min(a["y"] + a["h"], b["y"] + b["h"])
    return max(0, x2 - x1), max(0, y2 - y1)


def layout_constraints(slide: dict[str, Any], height: int) -> dict[str, Any]:
    raw = slide.get("layout_constraints")
    constraints = raw if isinstance(raw, dict) else {}
    enforce_safe = bool(constraints.get("enforce_subtitle_safe_zone", True))
    safe_y = constraints.get("subtitle_safe_y")
    if not isinstance(safe_y, (int, float)):
        safe_y = round(height * float(constraints.get("subtitle_safe_y_ratio", 930 / 1080)))
    overlap_tolerance = int(constraints.get("overlap_tolerance_px", 4))
    return {
        "enforce_subtitle_safe_zone": enforce_safe,
        "subtitle_safe_y": int(safe_y),
        "overlap_tolerance_px": max(0, overlap_tolerance),
    }


def build_animation(slide_id: str, layers: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    entry_index = 0
    for layer in layers:
        if layer["role"] in {"background", "decoration"}:
            continue
        action = str(layer.get("animation", "fade_up"))
        entry_action = str(layer.get("entry_animation") or ("fade_up" if action == "highlight" else action))
        if entry_action == "static":
            entry_action = ""
        reveal_at = layer.get("reveal_at")
        reveal_duration = layer.get("reveal_duration")
        if isinstance(reveal_at, (int, float)):
            at = max(0.0, float(reveal_at))
        elif action == "highlight":
            at = max(0.4, duration - 4.0)
        else:
            at = 0.12 + entry_index * 0.45
        event_duration = float(reveal_duration) if isinstance(reveal_duration, (int, float)) and reveal_duration > 0 else 0.55
        if entry_action:
            events.append(
                {
                    "id": f"{slide_id}_{layer['id']}_{entry_action}",
                    "target": layer["id"],
                    "action": entry_action if entry_action in {"fade_in", "fade_up", "soft_zoom_in", "slide_in_left"} else "fade_up",
                    "at": round(at, 3),
                    "duration": event_duration,
                    "easing": "easeOutCubic",
                }
            )
            if not isinstance(reveal_at, (int, float)) and action != "highlight":
                entry_index += 1
        if action == "highlight":
            highlight_at = layer.get("highlight_at")
            if isinstance(highlight_at, (int, float)):
                highlight_start = max(at + event_duration, float(highlight_at))
            else:
                highlight_start = max(at + event_duration + 0.2, duration - 2.0)
            events.append(
                {
                    "id": f"{slide_id}_{layer['id']}_highlight",
                    "target": layer["id"],
                    "action": "highlight",
                    "at": round(highlight_start, 3),
                    "duration": 1.1,
                    "easing": "easeOutCubic",
                }
            )
    return {"slide_id": slide_id, "duration_sec": round(duration, 3), "events": events}


def compose_slide(slide: dict[str, Any], manifest_dir: Path, repo_root: Path, default_canvas: dict[str, Any]) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise ComposeError("Slide missing slide_id")
    slide_dir = resolve_path(str(slide["slide_dir"]), manifest_dir, repo_root)
    assets_dir = slide_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    canvas = {**default_canvas, **slide.get("canvas", {})}
    width = int(canvas["width"])
    height = int(canvas["height"])
    constraints = layout_constraints(slide, height)
    background_asset = assets_dir / "background.png"
    background_source = slide.get("background_source")
    write_background(
        background_asset,
        canvas,
        resolve_path(str(background_source), manifest_dir, repo_root) if background_source else None,
    )

    alpha_policy = slide.get("white_key_alpha", {})
    if not isinstance(alpha_policy, dict):
        alpha_policy = {}

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

    preview = Image.open(background_asset).convert("RGBA")
    placed_boxes: list[dict[str, Any]] = []
    for raw in slide.get("layers", []):
        if not isinstance(raw, dict):
            raise ComposeError(f"Invalid layer entry in {slide_id}")
        layer_id = str(raw["id"])
        box = raw["box"]
        x = int(round(float(box["x"])))
        y = int(round(float(box["y"])))
        w = int(round(float(box["w"])))
        h = int(round(float(box["h"])))
        if w <= 0 or h <= 0:
            raise ComposeError(f"Invalid layer box for {slide_id}/{layer_id}")
        if x < 0 or y < 0 or x + w > width or y + h > height:
            raise ComposeError(f"Layer box outside canvas for {slide_id}/{layer_id}: {box}")
        role = str(raw.get("role", "content_body"))
        current_box = {"x": x, "y": y, "w": w, "h": h}
        if constraints["enforce_subtitle_safe_zone"] and role not in {"background", "decoration"}:
            safe_y = int(constraints["subtitle_safe_y"])
            if y + h > safe_y:
                raise ComposeError(
                    f"Layer enters subtitle safe zone for {slide_id}/{layer_id}: "
                    f"bottom={y + h}, safe_y={safe_y}"
                )
        for placed in placed_boxes:
            if role == "decoration" or placed["role"] == "decoration":
                continue
            overlap_w, overlap_h = intersection_size(current_box, placed["box"])
            tolerance = int(constraints["overlap_tolerance_px"])
            if overlap_w > tolerance and overlap_h > tolerance:
                raise ComposeError(
                    f"Layer boxes overlap for {slide_id}/{layer_id} and {placed['id']}: "
                    f"{overlap_w}x{overlap_h}px"
                )
        source = resolve_path(str(raw["source"]), manifest_dir, repo_root)
        asset_name = str(raw.get("asset", f"{layer_id}.png"))
        asset_path = assets_dir / asset_name
        layer_image = prepare_layer_image(
            source=source,
            width=w,
            height=h,
            key_white=bool(raw.get("key_white", True)),
            alpha_policy={**alpha_policy, **raw.get("white_key_alpha", {})},
        )
        layer_image.save(asset_path, format="PNG")
        preview.alpha_composite(layer_image, (x, y))
        scene_layer = {
            "id": layer_id,
            "type": "png",
            "asset": f"assets/{asset_name}",
            "role": role,
            "box": {"x": x, "y": y, "w": w, "h": h},
            "z_index": int(raw.get("z_index", 30)),
            "animation_role": str(raw.get("animation", raw.get("role", "content_body"))),
            "animation": str(raw.get("animation", "fade_up")),
        }
        for key in (
            "entry_animation",
            "reveal_at",
            "reveal_duration",
            "highlight_at",
            "text_summary",
            "narration_cue",
        ):
            if key in raw:
                scene_layer[key] = raw[key]
        scene_layers.append(scene_layer)
        placed_boxes.append({"id": layer_id, "role": role, "box": current_box})

    scene = {
        "slide_id": slide_id,
        "visual_source": "image_gen_macro_layers_manifest",
        "canvas": {"width": width, "height": height, "background": str(canvas.get("background", "#FFFDF7"))},
        "layers": scene_layers,
        "composition": {
            "method": "manifest_declared_image_gen_layers",
            "semantic_decomposition": "external_image_gen_or_web_generated_layers",
            "algorithmic_full_slide_decomposition": False,
        },
    }
    write_json(slide_dir / "scene.json", scene)
    duration = read_duration(slide_dir, float(slide.get("default_duration_sec", 12.0)))
    write_json(slide_dir / "animation_timeline.json", build_animation(slide_id, scene_layers, duration))
    preview_rgb = preview.convert("RGB")
    preview_rgb.save(slide_dir / "render_preview.png", format="PNG")
    # Compatibility outputs for existing validators/review gates. These are
    # audit previews, not the production animation layer.
    preview_rgb.save(slide_dir / "visual_draft.png", format="PNG")
    preview_rgb.save(assets_dir / "full_slide.png", format="PNG")


def compose_manifest(manifest: dict[str, Any], manifest_path: Path, repo_root: Path) -> int:
    canvas = {**DEFAULT_CANVAS, **manifest.get("canvas", {})}
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ComposeError("Manifest must contain non-empty slides[]")
    for slide in slides:
        if not isinstance(slide, dict):
            raise ComposeError("Each slide must be an object")
        compose_slide(slide, manifest_path.parent, repo_root, canvas)
    return len(slides)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose Image Gen macro layers into Remotion scenes.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = compose_manifest(read_json(args.manifest), args.manifest.resolve(), args.repo_root.resolve())
    except ComposeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Composed {count} slide(s) from manifest-declared Image Gen layers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
