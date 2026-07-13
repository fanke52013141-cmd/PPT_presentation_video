#!/usr/bin/env python3
"""Build deterministic reveal assets from exact or manually corrected Masks.

- A slide with no painted Mask is rendered as one static full-slide image.
- An exact AI Mask or painted Mask defines the processing boundary for a layer.
- Only white pixels connected to that Mask boundary are removed.
- Enclosed white details and all non-white content inside the Mask are retained.
- No semantic segmentation, coverage scoring, or automatic Mask expansion runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

try:
    from scripts.background_color import (
        MASK_CUTOUT_FEATHER_PX,
        MASK_CUTOUT_HARD_MAX_CHROMA,
        MASK_CUTOUT_HARD_MIN_CHANNEL,
        MASK_CUTOUT_SOFT_MAX_CHROMA,
        MASK_CUTOUT_SOFT_MIN_CHANNEL,
        masked_outer_white_cutout,
        normalize_connected_background,
    )
    from scripts.pipeline_profiles import allowed_reveal_actions, normalize_reveal_action, read_pipeline_profile
except ModuleNotFoundError:
    from background_color import (
        MASK_CUTOUT_FEATHER_PX,
        MASK_CUTOUT_HARD_MAX_CHROMA,
        MASK_CUTOUT_HARD_MIN_CHANNEL,
        MASK_CUTOUT_SOFT_MAX_CHROMA,
        MASK_CUTOUT_SOFT_MIN_CHANNEL,
        masked_outer_white_cutout,
        normalize_connected_background,
    )
    from pipeline_profiles import allowed_reveal_actions, normalize_reveal_action, read_pipeline_profile


PIPELINE_VERSION = "exact_rle_mask_with_manual_corrections_v5"
MASKED_COMPOSITION_METHOD = "solid_background_mask_boundary_white_cutout"
STATIC_COMPOSITION_METHOD = "full_slide_static"
DEFAULT_CANVAS = {
    "width": 1920,
    "height": 1080,
    "background": "#FEFDF9",
    "subtitle_safe_y": 930,
}
DEFAULT_REVEAL_DURATION_SEC = 0.75
MIN_REVEAL_DURATION_SEC = 0.05
RENDERER_ACTIONS = {
    "fade_in",
    "fade_up",
    "soft_zoom_in",
    "slide_in_left",
    "highlight",
    "cover_fade_out",
    "cover_wipe_left_to_right",
    "cover_wipe_right_to_left",
    "cover_wipe_top_to_bottom",
    "cover_wipe_bottom_to_top",
    "fog_diagonal_erase",
    "crop_fade_up",
    "crop_slide_in_left",
    "crop_soft_zoom_in",
    "wipe_left_to_right",
    "wipe_right_to_left",
    "wipe_top_to_bottom",
    "wipe_bottom_to_top",
    "scratch_reveal",
    "brush_wipe_left_to_right",
    "sticker_pop",
    "stamp_in",
    "paper_drop",
}


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
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def is_erase_stroke(stroke: dict[str, Any]) -> bool:
    mode = str(stroke.get("mode", "")).lower()
    return bool(stroke.get("eraser")) or mode == "erase"


def manual_mask_alpha(manual_mask: Any, width: int, height: int) -> Image.Image | None:
    """Rasterize an exact automatic base mask plus manual paint/erase deltas."""
    if not isinstance(manual_mask, dict):
        return None
    strokes = manual_mask.get("strokes")
    alpha = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha)
    found_paint = False

    rle = manual_mask.get("rle") if isinstance(manual_mask.get("rle"), dict) else {}
    if rle.get("encoding") == "row_runs_v1":
        if int(rle.get("width", width)) != width or int(rle.get("height", height)) != height:
            raise RevealBuildError("Exact Mask RLE canvas does not match slide canvas")
        for run in rle.get("runs", []) or []:
            if not isinstance(run, list) or len(run) < 3:
                continue
            y, x1, x2 = int(run[0]), int(run[1]), int(run[2])
            if 0 <= y < height and x2 > x1:
                draw.rectangle((max(0, x1), y, min(width, x2) - 1, y), fill=255)
                found_paint = True

    for stroke in strokes if isinstance(strokes, list) else []:
        if not isinstance(stroke, dict):
            continue
        raw_points = stroke.get("points")
        if not isinstance(raw_points, list) or not raw_points:
            continue
        points = [
            (int(round(float(point.get("x", 0)))), int(round(float(point.get("y", 0)))))
            for point in raw_points
            if isinstance(point, dict)
        ]
        if not points:
            continue

        erase = is_erase_stroke(stroke)
        if not erase:
            found_paint = True
        size = max(1, int(round(float(stroke.get("size", 42)))))
        radius = max(1, size // 2)
        fill = 0 if erase else 255
        if len(points) > 1:
            draw.line(points, fill=fill, width=size, joint="curve")
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    if not found_paint or not alpha.getbbox():
        return None
    return alpha


def alpha_box(alpha: Image.Image, width: int, height: int, padding: int = 2) -> dict[str, int]:
    bbox = alpha.getbbox()
    if not bbox:
        raise RevealBuildError("Manual mask contains no painted pixels")
    x1 = max(0, bbox[0] - padding)
    y1 = max(0, bbox[1] - padding)
    x2 = min(width, bbox[2] + padding)
    y2 = min(height, bbox[3] + padding)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def build_event(slide_id: str, group: dict[str, Any], layer_id: str, fallback_at: float) -> dict[str, Any]:
    reveal = group.get("reveal") if isinstance(group.get("reveal"), dict) else {}
    profile = read_pipeline_profile()
    action = normalize_reveal_action(str(reveal.get("type", "crop_fade_up")), profile, for_renderer=True)
    if action not in RENDERER_ACTIONS and action not in allowed_reveal_actions(profile):
        action = "crop_fade_up"
    duration = max(
        MIN_REVEAL_DURATION_SEC,
        float(reveal.get("duration", DEFAULT_REVEAL_DURATION_SEC)),
    )
    event: dict[str, Any] = {
        "id": f"{slide_id}_{group['id']}_{action}",
        "target": layer_id,
        "target_group_id": group["id"],
        "action": action,
        "at": round(max(0.0, float(reveal.get("at", fallback_at))), 3),
        "duration": round(duration, 3),
        "easing": "easeOutCubic",
        "params": {
            key: reveal[key]
            for key in ("angle", "feather", "fog_strength", "blur_px", "direction", "stagger", "rotation")
            if key in reveal
        },
    }
    event["link_to_narration"] = bool(group.get("link_to_narration", bool(group.get("narration_beat_id"))))
    for key in ("narration_beat_id", "linked_segment_id"):
        if event["link_to_narration"] and group.get(key):
            event[key] = group[key]
    beat_ids = group.get("narration_beat_ids")
    if isinstance(beat_ids, list) and beat_ids:
        event["narration_beat_ids"] = beat_ids
    return event


def reset_assets_dir(assets_dir: Path) -> None:
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)


def publish_slide_outputs(staging_dir: Path, slide_dir: Path) -> None:
    """Publish a complete build without exposing deleted or half-written assets."""
    staged_assets = staging_dir / "assets"
    production_assets = slide_dir / "assets"
    production_assets.mkdir(parents=True, exist_ok=True)

    published_assets: set[Path] = set()
    for staged_path in sorted(path for path in staged_assets.rglob("*") if path.is_file()):
        relative = staged_path.relative_to(staged_assets)
        published_assets.add(relative)
        destination = production_assets / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_path, destination)

    # Publish metadata last. Until these replacements happen, readers continue
    # to see the previous complete scene, whose assets were never deleted.
    for filename in ("animation_timeline.json", "reveal_report.json", "scene.json"):
        os.replace(staging_dir / filename, slide_dir / filename)

    # Metadata now points only to the newly published set, so old unreferenced
    # files can be removed without creating a missing-asset window.
    for old_path in sorted(
        (path for path in production_assets.rglob("*") if path.is_file()),
        reverse=True,
    ):
        if old_path.relative_to(production_assets) not in published_assets:
            old_path.unlink()
    for old_dir in sorted(
        (path for path in production_assets.rglob("*") if path.is_dir()),
        reverse=True,
    ):
        try:
            old_dir.rmdir()
        except OSError:
            pass
    shutil.rmtree(staging_dir, ignore_errors=True)


def static_slide_outputs(
    slide_id: str,
    slide_dir: Path,
    master_path: Path,
    master: Image.Image,
    width: int,
    height: int,
    background: str,
    default_duration_sec: float,
    input_group_count: int,
    source_sha256: str,
    normalized_background_pixel_count: int,
    warnings: list[dict[str, Any]] | None = None,
) -> None:
    assets_dir = slide_dir / "assets"
    master.save(assets_dir / "full_slide.png", format="PNG")
    full_box = {"x": 0, "y": 0, "w": width, "h": height}
    scene = {
        "slide_id": slide_id,
        "source_visual_draft": str(master_path),
        "visual_source": "master_reveal_layers",
        "canvas": {"width": width, "height": height, "background": background},
        "layers": [{
            "id": "full_slide",
            "type": "png",
            "asset": "assets/full_slide.png",
            "role": "full_slide",
            "box": full_box,
            "z_index": 0,
        }],
        "composition": {
            "method": STATIC_COMPOSITION_METHOD,
            "pipeline_version": PIPELINE_VERSION,
            "manual_mask_only": True,
        },
    }
    write_json(slide_dir / "scene.json", scene)
    write_json(slide_dir / "animation_timeline.json", {
        "slide_id": slide_id,
        "duration_sec": round(max(default_duration_sec, 0.1), 3),
        "events": [],
    })
    write_json(slide_dir / "reveal_report.json", {
        "slide_id": slide_id,
        "method": STATIC_COMPOSITION_METHOD,
        "pipeline_version": PIPELINE_VERSION,
        "manual_mask_only": True,
        "background": background,
        "background_normalization": {
            "method": "outer_connected_near_white_only",
            "normalized_pixel_count": normalized_background_pixel_count,
        },
        "source_sha256": source_sha256,
        "warnings": warnings or [],
        "input_group_count": input_group_count,
        "group_count": 0,
        "layer_count": 1,
        "fallback_full_slide": True,
    })


def compose_slide(
    slide: dict[str, Any],
    manifest_dir: Path,
    repo_root: Path,
    default_canvas: dict[str, Any],
) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise RevealBuildError("Slide missing slide_id")

    production_slide_dir = resolve_path(
        str(slide["slide_dir"]),
        manifest_dir,
        manifest_dir,
        repo_root,
    )
    production_slide_dir.mkdir(parents=True, exist_ok=True)
    for stale_build_dir in production_slide_dir.glob(".reveal-build-*"):
        if stale_build_dir.is_dir():
            shutil.rmtree(stale_build_dir, ignore_errors=True)
    master_path = resolve_path(
        str(slide["master"]),
        manifest_dir,
        production_slide_dir,
        repo_root,
    )
    if not master_path.exists():
        raise RevealBuildError(f"Missing master image: {master_path}")

    slide_dir = production_slide_dir / f".reveal-build-{uuid.uuid4().hex}"
    assets_dir = slide_dir / "assets"
    reset_assets_dir(assets_dir)
    master = Image.open(master_path).convert("RGB")

    canvas = {
        **default_canvas,
        **(slide.get("canvas") if isinstance(slide.get("canvas"), dict) else {}),
    }
    width = int(canvas.get("width", master.width))
    height = int(canvas.get("height", master.height))
    if master.size != (width, height):
        master = master.resize((width, height), Image.Resampling.LANCZOS)
    background = str(canvas.get("background", DEFAULT_CANVAS["background"]))
    background_rgb = hex_to_rgb(background)
    subtitle_safe_y = int(canvas.get("subtitle_safe_y", DEFAULT_CANVAS["subtitle_safe_y"]))
    source_sha256 = sha256_file(master_path)

    groups = slide.get("groups")
    if not isinstance(groups, list):
        raise RevealBuildError(f"Slide groups must be a list: {slide_id}")

    painted_groups: list[tuple[dict[str, Any], Image.Image]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise RevealBuildError(f"Invalid group in {slide_id}")
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            raise RevealBuildError(f"Group missing id in {slide_id}")
        alpha = manual_mask_alpha(group.get("manual_mask"), width, height)
        if alpha is not None:
            painted_groups.append((group, alpha))

    source_master = master
    default_duration_sec = float(slide.get("default_duration_sec", 12.0))
    if not painted_groups:
        normalized_master, normalized_background_pixel_count = normalize_connected_background(
            master,
            background_rgb,
        )
        static_slide_outputs(
            slide_id=slide_id,
            slide_dir=slide_dir,
            master_path=master_path,
            master=normalized_master,
            width=width,
            height=height,
            background=background,
            default_duration_sec=default_duration_sec,
            input_group_count=len(groups),
            source_sha256=source_sha256,
            normalized_background_pixel_count=normalized_background_pixel_count,
        )
        publish_slide_outputs(slide_dir, production_slide_dir)
        return

    static_painted_groups = [
        (group, alpha) for group, alpha in painted_groups
        if bool(group.get("is_static")) or bool(group.get("is_static_header"))
    ]
    dynamic_painted_groups = [
        (group, alpha) for group, alpha in painted_groups
        if not bool(group.get("is_static")) and not bool(group.get("is_static_header"))
    ]
    base_image = Image.new("RGBA", (width, height), (*background_rgb, 255))
    static_group_reports: list[dict[str, Any]] = []
    for static_group, static_alpha in static_painted_groups:
        static_layer, exact_alpha, cutout_stats = masked_outer_white_cutout(source_master, static_alpha)
        if not exact_alpha.getbbox():
            continue
        base_image = Image.alpha_composite(base_image, static_layer.convert("RGBA"))
        static_group_reports.append({
            "group_id": str(static_group.get("id") or "__static__"),
            "mask_bbox": alpha_box(exact_alpha, width, height),
            "output_alpha_sha256": sha256_bytes(exact_alpha.tobytes()),
            "manual_mask_sha256": json_fingerprint(static_group.get("manual_mask")),
            "cutout": {"method": "static_base_exact_mask", **cutout_stats},
        })
    base_image.convert("RGB").save(assets_dir / "base_slide.png", format="PNG")
    layers: list[dict[str, Any]] = [{
        "id": "base_slide",
        "type": "png",
        "asset": "assets/base_slide.png",
        "role": "background",
        "box": {"x": 0, "y": 0, "w": width, "h": height},
        "z_index": 0,
    }]
    events: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    group_reports: list[dict[str, Any]] = []

    for index, (group, manual_alpha) in enumerate(dynamic_painted_groups, start=1):
        group_id = str(group["id"])
        layer_image, alpha, cutout_stats = masked_outer_white_cutout(
            source_master,
            manual_alpha,
        )
        if not alpha.getbbox():
            warnings.append({
                "severity": "warning",
                "type": "manual_mask_contains_only_white_background",
                "group_id": group_id,
            })
            continue
        source_box = alpha_box(alpha, width, height)
        if source_box["y"] + source_box["h"] > subtitle_safe_y and str(group.get("role", "")) != "decoration":
            warnings.append({
                "severity": "warning",
                "type": "manual_mask_enters_subtitle_safe_zone",
                "group_id": group_id,
            })

        crops_dir = assets_dir / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        layer_rel = f"assets/crops/{group_id}.png"
        layer_image.save(slide_dir / layer_rel, format="PNG")

        layer_id = f"reveal_crop_{group_id}"
        layers.append({
            "id": layer_id,
            "type": "png",
            "asset": layer_rel,
            "role": "reveal_crop",
            "target_group_id": group_id,
            "visible_text": group.get("visible_text", ""),
            "box": {"x": 0, "y": 0, "w": width, "h": height},
            "source_box": source_box,
            "z_index": int(group.get("z_index", 40 + index)),
        })
        events.append(build_event(slide_id, group, layer_id, 0.2 + (index - 1) * 0.7))
        group_reports.append({
            "group_id": group_id,
            "mask_bbox": source_box,
            "output_alpha_sha256": sha256_bytes(alpha.tobytes()),
            "manual_mask_sha256": json_fingerprint(group.get("manual_mask")),
            "cutout": {
                "method": "mask_boundary_connected_white_soft_alpha",
                **cutout_stats,
            },
        })

    if not group_reports:
        normalized_master, normalized_background_pixel_count = normalize_connected_background(
            master,
            background_rgb,
        )
        warnings.append({
            "severity": "warning",
            "type": "all_manual_masks_resolved_to_empty_content",
            "message": "All painted masks contained only removable background; fallback to full static slide.",
        })
        static_slide_outputs(
            slide_id=slide_id,
            slide_dir=slide_dir,
            master_path=master_path,
            master=normalized_master,
            width=width,
            height=height,
            background=background,
            default_duration_sec=default_duration_sec,
            input_group_count=len(groups),
            source_sha256=source_sha256,
            normalized_background_pixel_count=normalized_background_pixel_count,
            warnings=warnings,
        )
        publish_slide_outputs(slide_dir, production_slide_dir)
        return

    scene = {
        "slide_id": slide_id,
        "source_visual_draft": str(master_path),
        "visual_source": "master_reveal_layers",
        "canvas": {"width": width, "height": height, "background": background},
        "layers": layers,
        "composition": {
            "method": MASKED_COMPOSITION_METHOD,
            "pipeline_version": PIPELINE_VERSION,
            "manual_mask_only": True,
            "background_source": "canvas.background",
            "source_image_used_for_background": False,
            "cutout_method": "mask_boundary_connected_white_soft_alpha",
            "static_header_in_base": bool(static_group_reports),
        },
    }
    duration = max(
        default_duration_sec,
        max((float(event["at"]) + float(event["duration"]) for event in events), default=0.0) + 0.5,
    )
    write_json(slide_dir / "scene.json", scene)
    write_json(slide_dir / "animation_timeline.json", {
        "slide_id": slide_id,
        "duration_sec": round(duration, 3),
        "events": events,
    })
    write_json(slide_dir / "reveal_report.json", {
        "slide_id": slide_id,
        "method": MASKED_COMPOSITION_METHOD,
        "pipeline_version": PIPELINE_VERSION,
        "manual_mask_only": True,
        "background": background,
        "background_source": "canvas.background",
        "source_image_used_for_background": False,
        "cutout": {
            "method": "mask_boundary_connected_white_soft_alpha",
            "hard_min_channel": MASK_CUTOUT_HARD_MIN_CHANNEL,
            "hard_max_chroma": MASK_CUTOUT_HARD_MAX_CHROMA,
            "soft_min_channel": MASK_CUTOUT_SOFT_MIN_CHANNEL,
            "soft_max_chroma": MASK_CUTOUT_SOFT_MAX_CHROMA,
            "feather_px": MASK_CUTOUT_FEATHER_PX,
            "enclosed_white_preserved": True,
            "white_decontamination": True,
        },
        "source_sha256": source_sha256,
        "static_groups": static_group_reports,
        "warnings": warnings,
        "input_group_count": len(groups),
        "group_count": len(group_reports),
        "layer_count": len(layers),
        "fallback_full_slide": False,
        "groups": group_reports,
    })
    publish_slide_outputs(slide_dir, production_slide_dir)


def build_manifest(
    manifest: dict[str, Any],
    manifest_path: Path,
    repo_root: Path,
    slide_id: str = "",
) -> int:
    if manifest.get("version") != "reveal_v1":
        raise RevealBuildError("Manifest version must be reveal_v1")
    canvas = {
        **DEFAULT_CANVAS,
        **(manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {}),
    }
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        raise RevealBuildError("Manifest must contain non-empty slides[]")
    selected_slides = [
        slide for slide in slides
        if not slide_id or (isinstance(slide, dict) and str(slide.get("slide_id") or "") == slide_id)
    ]
    if slide_id and not selected_slides:
        raise RevealBuildError(f"Slide not found in manifest: {slide_id}")
    for slide in selected_slides:
        if not isinstance(slide, dict):
            raise RevealBuildError("Each slide must be an object")
        compose_slide(slide, manifest_path.parent, repo_root, canvas)
    return len(selected_slides)


def compose_preview_image(slide_dir: Path, output_path: Path) -> None:
    """Composite the production scene layers into a static review PNG."""
    scene = read_json(slide_dir / "scene.json")
    canvas = scene.get("canvas") if isinstance(scene.get("canvas"), dict) else {}
    width = max(1, int(canvas.get("width", 1920)))
    height = max(1, int(canvas.get("height", 1080)))
    layers = scene.get("layers")
    if not isinstance(layers, list) or not layers:
        raise RevealBuildError(f"Scene has no previewable layers: {slide_dir}")
    preview = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for layer in sorted(
        (item for item in layers if isinstance(item, dict)),
        key=lambda item: int(item.get("z_index", 0)),
    ):
        asset = slide_dir / str(layer.get("asset") or "")
        if not asset.exists():
            raise RevealBuildError(f"Missing preview layer: {asset}")
        image = Image.open(asset).convert("RGBA")
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        preview = Image.alpha_composite(preview, image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.convert("RGB").save(output_path, format="PNG")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build exact manual-mask reveal assets.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--slide-id", default="")
    parser.add_argument("--preview-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest_path = args.manifest.resolve()
        manifest_payload = read_json(manifest_path)
        count = build_manifest(
            manifest_payload,
            manifest_path,
            args.repo_root.resolve(),
            slide_id=str(args.slide_id or "").strip(),
        )
        if args.preview_output:
            if not args.slide_id:
                raise RevealBuildError("--preview-output requires --slide-id")
            preview_slide = next(
                (
                    slide for slide in manifest_payload.get("slides", []) or []
                    if isinstance(slide, dict) and str(slide.get("slide_id") or "") == str(args.slide_id)
                ),
                None,
            )
            if preview_slide is None:
                raise RevealBuildError(f"Slide not found in manifest: {args.slide_id}")
            preview_slide_dir = resolve_path(
                str(preview_slide["slide_dir"]),
                manifest_path.parent,
                manifest_path.parent,
                args.repo_root.resolve(),
            )
            compose_preview_image(
                preview_slide_dir,
                args.preview_output.resolve(),
            )
    except RevealBuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Built {PIPELINE_VERSION} reveal assets for {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
