#!/usr/bin/env python3
"""Build a full-slide reveal scene from reveal_manifest.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

DEFAULT_CANVAS = {"width": 1920, "height": 1080, "background": "#FFFDF7", "subtitle_safe_y": 930}
DEFAULTS = {"padding_px": 32, "duration": 0.65, "angle": 135, "feather": 16, "fog_strength": 0.68, "blur_px": 16}
COVER_ACTIONS = {"cover_fade_out", "cover_wipe_left_to_right", "cover_wipe_top_to_bottom"}
FOG_ACTIONS = {"fog_diagonal_erase"}
CROP_ACTIONS = {"crop_fade_up", "crop_slide_in_left", "crop_soft_zoom_in"}
ALLOWED_ACTIONS = COVER_ACTIONS | FOG_ACTIONS | CROP_ACTIONS | {"highlight"}


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


def manual_mask_alpha(manual_mask: Any, box: dict[str, int]) -> Image.Image | None:
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
        size = max(1, int(round(float(stroke.get("size", 42)))))
        mode = str(stroke.get("mode", "")).lower()
        is_erase = bool(stroke.get("eraser")) or mode == "erase"
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


def apply_alpha(image: Image.Image, alpha: Image.Image | None) -> Image.Image:
    if alpha is None:
        return image
    rgba = image.convert("RGBA")
    if alpha.size != rgba.size:
        alpha = alpha.resize(rgba.size, Image.Resampling.LANCZOS)
    rgba.putalpha(alpha)
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
    event: dict[str, Any] = {
        "id": f"{slide_id}_{group['id']}_{action}",
        "target": layer_id,
        "target_group_id": group["id"],
        "action": action,
        "at": round(max(0.0, at), 3),
        "duration": round(max(0.05, duration), 3),
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
    layers: list[dict[str, Any]] = [
        {"id": "full_slide_layer", "type": "png", "asset": "assets/full_slide.png", "role": "full_slide", "box": {"x": 0, "y": 0, "w": width, "h": height}, "z_index": 0}
    ]
    events: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    groups = slide.get("groups")
    if not isinstance(groups, list):
        raise RevealBuildError(f"Slide groups must be a list: {slide_id}")
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
        padding = int(group.get("padding_px", DEFAULTS["padding_px"]))
        box = padded_box(raw_box, width, height, padding)
        alpha = manual_mask_alpha(group.get("manual_mask"), box)
        if role != "decoration" and box["y"] + box["h"] > subtitle_safe_y:
            warnings.append({"severity": "blocking", "type": "subtitle_safe_zone_violation", "group_id": group_id})
        for existing in placed:
            gap = rect_distance(box, existing["box"])
            if gap < 48 and role != "decoration" and existing["role"] != "decoration":
                warnings.append({"severity": "warning", "type": "group_gap_small", "group_id": group_id, "other_group_id": existing["id"], "gap_px": round(gap, 2)})
        reveal = group.get("reveal") if isinstance(group.get("reveal"), dict) else {}
        action = str(reveal.get("type", "cover_fade_out"))
        layer_asset = ""
        layer_role = "cover_layer"
        if action in FOG_ACTIONS:
            rel = f"assets/fog/{group_id}_fog.png"
            write_fog(slide_dir / rel, master, box, background, float(reveal.get("fog_strength", DEFAULTS["fog_strength"])), float(reveal.get("blur_px", DEFAULTS["blur_px"])), alpha)
            layer_asset = rel
            layer_role = "fog_layer"
        elif action in CROP_ACTIONS:
            rel_cover = f"assets/covers/{group_id}_cover.png"
            write_cover(slide_dir / rel_cover, box, background, alpha)
            layers.append({"id": f"cover_{group_id}", "type": "png", "asset": rel_cover, "role": "cover_layer", "target_group_id": group_id, "box": box, "z_index": int(group.get("z_index", 30 + index))})
            rel = f"assets/crops/{group_id}.png"
            (slide_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            apply_alpha(crop_image(master, box), alpha).save(slide_dir / rel, format="PNG")
            layer_asset = rel
            layer_role = "reveal_crop"
        else:
            rel = f"assets/covers/{group_id}_cover.png"
            write_cover(slide_dir / rel, box, background, alpha)
            layer_asset = rel
            layer_role = "cover_layer"
        layer_id = f"{layer_role}_{group_id}"
        layers.append({"id": layer_id, "type": "png", "asset": layer_asset, "role": layer_role, "target_group_id": group_id, "visible_text": group.get("visible_text", ""), "box": box, "z_index": int(group.get("z_index", 40 + index))})
        events.append(build_event(slide_id, group, layer_id, 0.2 + (index - 1) * 0.7))
        placed.append({"id": group_id, "role": role, "box": box})
    scene = {"slide_id": slide_id, "source_visual_draft": str(master_path), "visual_source": "master_reveal_layers", "canvas": {"width": width, "height": height, "background": background}, "layers": layers, "composition": {"method": "full_slide_reveal_layers", "algorithmic_full_slide_decomposition": False}}
    duration = max(float(slide.get("default_duration_sec", 12.0)), max((float(e["at"]) + float(e["duration"]) for e in events), default=0.0) + 0.5)
    write_json(slide_dir / "scene.json", scene)
    write_json(slide_dir / "animation_timeline.json", {"slide_id": slide_id, "duration_sec": round(duration, 3), "events": events})
    write_json(slide_dir / "reveal_report.json", {"slide_id": slide_id, "method": "full_slide_reveal_layers", "warnings": warnings, "group_count": len(groups), "layer_count": len(layers), "fallback_full_slide": len(groups) == 0})


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
