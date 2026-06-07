#!/usr/bin/env python3
"""
Prepare Remotion scene inputs from full-slide bitmap visual drafts.

This project keeps slide content inside generated PNGs. Remotion should compose
those PNGs with audio and subtitles, not redraw slide body content.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080


class PrepareError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PrepareError(f"Missing required JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise PrepareError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PrepareError(f"JSON file must contain an object: {path}")
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
                raise PrepareError(
                    f"Visual draft aspect ratio must be 16:9 before resize: {source} "
                    f"has {image.width}x{image.height}"
                )
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        image.save(destination, format="PNG", optimize=optimize_png)


def audio_duration(slide_dir: Path, default_duration_sec: float) -> float:
    audio_timeline_path = slide_dir / "audio_timeline.json"
    if not audio_timeline_path.exists():
        return default_duration_sec
    timeline = read_json(audio_timeline_path)
    duration = timeline.get("duration_sec")
    if isinstance(duration, (int, float)) and duration > 0:
        return round(float(duration), 3)
    segment_ends = [
        float(segment["end"])
        for segment in timeline.get("segments", [])
        if isinstance(segment, dict) and isinstance(segment.get("end"), (int, float))
    ]
    return round(max(segment_ends, default=default_duration_sec), 3)


def prepare_slide(
    slide_dir: Path,
    visual_filename: str,
    width: int,
    height: int,
    default_duration_sec: float,
    optimize_png: bool,
    overwrite: bool,
) -> None:
    visual_draft = slide_dir / visual_filename
    if not visual_draft.exists():
        raise PrepareError(f"Missing visual draft: {visual_draft}")
    if visual_draft.suffix.lower() != ".png":
        raise PrepareError(f"Visual draft must be PNG: {visual_draft}")

    asset_path = slide_dir / "assets" / "full_slide.png"
    if overwrite or not asset_path.exists():
        normalize_image(visual_draft, asset_path, width=width, height=height, optimize_png=optimize_png)

    scene_path = slide_dir / "scene.json"
    if overwrite or not scene_path.exists():
        scene = {
            "slide_id": slide_dir.name,
            "source_visual_draft": str(visual_draft).replace("\\", "/"),
            "visual_source": "codex_image_gen_full_slide_bitmap",
            "canvas": {
                "width": width,
                "height": height,
                "background": "#FFFDF7",
            },
            "layers": [
                {
                    "id": "full_slide_layer",
                    "type": "png",
                    "asset": "assets/full_slide.png",
                    "role": "full_slide",
                    "box": {"x": 0, "y": 0, "w": width, "h": height},
                    "z_index": 10,
                    "animation_role": "full_slide_bitmap",
                }
            ],
        }
        write_json(scene_path, scene)

    animation_path = slide_dir / "animation_timeline.json"
    if overwrite or not animation_path.exists():
        duration_sec = audio_duration(slide_dir, default_duration_sec=default_duration_sec)
        animation = {
            "slide_id": slide_dir.name,
            "duration_sec": duration_sec,
            "events": [
                {
                    "id": f"{slide_dir.name}_full_slide_fade",
                    "target": "full_slide_layer",
                    "action": "fade_in",
                    "at": 0,
                    "duration": 0.5,
                    "easing": "easeOutCubic",
                }
            ],
        }
        write_json(animation_path, animation)


def prepare_run(
    run_dir: Path,
    visual_filename: str,
    width: int,
    height: int,
    default_duration_sec: float,
    optimize_png: bool,
    overwrite: bool,
) -> int:
    slides_dir = run_dir / "slides"
    if not slides_dir.exists():
        raise PrepareError(f"Missing slides directory: {slides_dir}")

    slide_dirs = sorted([path for path in slides_dir.iterdir() if path.is_dir()], key=slide_sort_key)
    if not slide_dirs:
        raise PrepareError(f"No slide directories found in: {slides_dir}")

    for slide_dir in slide_dirs:
        prepare_slide(
            slide_dir=slide_dir,
            visual_filename=visual_filename,
            width=width,
            height=height,
            default_duration_sec=default_duration_sec,
            optimize_png=optimize_png,
            overwrite=overwrite,
        )

    return len(slide_dirs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare full-slide PNG scene files for Remotion.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--visual-filename", default="visual_draft.png")
    parser.add_argument("--width", default=DEFAULT_WIDTH, type=int)
    parser.add_argument("--height", default=DEFAULT_HEIGHT, type=int)
    parser.add_argument("--default-duration-sec", default=12.0, type=float)
    parser.add_argument("--optimize-png", action="store_true", help="Enable slower PNG compression optimization.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = prepare_run(
            run_dir=args.run_dir.resolve(),
            visual_filename=args.visual_filename,
            width=args.width,
            height=args.height,
            default_duration_sec=args.default_duration_sec,
            optimize_png=args.optimize_png,
            overwrite=args.overwrite,
        )
    except PrepareError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Prepared {count} slide scene(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
