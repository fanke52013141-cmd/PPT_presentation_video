#!/usr/bin/env python3
"""
Validate article-to-video run assets before Remotion rendering.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080


class ValidationError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValidationError(f"Missing required JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON file must contain an object: {path}")
    return value


def resolve_asset(value: str, slide_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in [slide_dir / path, repo_root / path]:
        if candidate.exists():
            return candidate
    return slide_dir / path


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def validate_png(path: Path, width: int | None = None, height: int | None = None) -> None:
    if not path.exists():
        raise ValidationError(f"Missing PNG asset: {path}")
    if path.suffix.lower() != ".png":
        raise ValidationError(f"Expected PNG asset, got: {path}")
    actual_width, actual_height = image_size(path)
    if width is not None and height is not None and (actual_width, actual_height) != (width, height):
        raise ValidationError(
            f"PNG has wrong dimensions: {path} is {actual_width}x{actual_height}, "
            f"expected {width}x{height}"
        )


def validate_audio_timeline(path: Path) -> float:
    timeline = read_json(path)
    segments = timeline.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValidationError(f"audio_timeline.json must contain non-empty segments[]: {path}")
    duration = timeline.get("duration_sec")
    max_end = 0.0
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValidationError(f"Invalid audio segment object: {path}")
        for key in ["id", "start", "end", "text"]:
            if key not in segment:
                raise ValidationError(f"Audio segment missing {key}: {path}")
        start = segment["start"]
        end = segment["end"]
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            raise ValidationError(f"Audio segment has invalid timing: {path}: {segment.get('id')}")
        max_end = max(max_end, float(end))
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValidationError(f"audio_timeline.json missing positive duration_sec: {path}")
    if abs(float(duration) - max_end) > 0.2:
        raise ValidationError(f"audio_timeline duration_sec does not match segment ends: {path}")
    return float(duration)


def validate_scene(
    scene_path: Path,
    slide_dir: Path,
    repo_root: Path,
    width: int,
    height: int,
    require_full_slide: bool,
) -> set[str]:
    scene = read_json(scene_path)
    if "elements" in scene:
        raise ValidationError(f"scene.json contains deprecated elements[]: {scene_path}")
    layers = scene.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ValidationError(f"scene.json must contain non-empty layers[]: {scene_path}")
    if require_full_slide and len(layers) != 1:
        raise ValidationError(f"Full-slide mode requires exactly one PNG layer: {scene_path}")

    layer_ids: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValidationError(f"Invalid scene layer object: {scene_path}")
        layer_id = str(layer.get("id", ""))
        if not layer_id:
            raise ValidationError(f"Layer missing id: {scene_path}")
        if layer_id in layer_ids:
            raise ValidationError(f"Duplicate layer id {layer_id}: {scene_path}")
        layer_ids.add(layer_id)
        if layer.get("type") != "png":
            raise ValidationError(f"Layer type must be png, not {layer.get('type')}: {scene_path}")
        asset = str(layer.get("asset", ""))
        if asset.lower().endswith(".svg"):
            raise ValidationError(f"SVG assets are not allowed in production scene: {scene_path}")
        asset_path = resolve_asset(asset, slide_dir, repo_root)
        expected_size = (width, height) if require_full_slide else (None, None)
        validate_png(asset_path, width=expected_size[0], height=expected_size[1])

        if require_full_slide:
            box = layer.get("box")
            if not isinstance(box, dict):
                raise ValidationError(f"Full-slide layer missing box: {scene_path}")
            expected_box = {"x": 0, "y": 0, "w": width, "h": height}
            if any(box.get(key) != value for key, value in expected_box.items()):
                raise ValidationError(f"Full-slide layer box must be {expected_box}: {scene_path}")
            if layer.get("role") != "full_slide":
                raise ValidationError(f"Full-slide layer role must be full_slide: {scene_path}")

    return layer_ids


def validate_animation_timeline(path: Path, layer_ids: set[str], audio_duration_sec: float) -> None:
    timeline = read_json(path)
    events = timeline.get("events")
    if not isinstance(events, list):
        raise ValidationError(f"animation_timeline.json must contain events[]: {path}")
    duration = timeline.get("duration_sec")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValidationError(f"animation_timeline.json missing positive duration_sec: {path}")
    if abs(float(duration) - audio_duration_sec) > 0.2:
        raise ValidationError(f"animation duration does not match audio duration: {path}")
    for event in events:
        if not isinstance(event, dict):
            raise ValidationError(f"Invalid animation event object: {path}")
        target = str(event.get("target", ""))
        if target not in layer_ids:
            raise ValidationError(f"Animation target does not exist in scene layers: {path}: {target}")
        if not isinstance(event.get("at"), (int, float)) or not isinstance(event.get("duration"), (int, float)):
            raise ValidationError(f"Animation event has invalid timing: {path}: {event.get('id')}")


def validate_slide(
    slide_dir: Path,
    repo_root: Path,
    width: int,
    height: int,
    require_full_slide: bool,
) -> None:
    validate_png(slide_dir / "visual_draft.png")
    validate_png(slide_dir / "assets" / "full_slide.png", width=width, height=height)
    voice_path = slide_dir / "voice.mp3"
    if not voice_path.exists() or voice_path.stat().st_size < 1024:
        raise ValidationError(f"Missing or empty voice.mp3: {voice_path}")
    if not (slide_dir / "subtitles.srt").exists():
        raise ValidationError(f"Missing subtitles.srt: {slide_dir}")
    audio_duration_sec = validate_audio_timeline(slide_dir / "audio_timeline.json")
    layer_ids = validate_scene(
        slide_dir / "scene.json",
        slide_dir=slide_dir,
        repo_root=repo_root,
        width=width,
        height=height,
        require_full_slide=require_full_slide,
    )
    validate_animation_timeline(slide_dir / "animation_timeline.json", layer_ids, audio_duration_sec)


def validate_run(
    run_dir: Path,
    repo_root: Path,
    width: int,
    height: int,
    require_full_slide: bool,
) -> int:
    slide_plan = read_json(run_dir / "planning" / "slide_plan.json")
    slides = slide_plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError(f"slide_plan.json must contain non-empty slides[]: {run_dir}")

    slide_ids = [str(slide.get("slide_id", "")) for slide in slides if isinstance(slide, dict)]
    if not slide_ids or len(slide_ids) != len(set(slide_ids)):
        raise ValidationError(f"slide_plan.json has missing or duplicate slide_id values: {run_dir}")

    for slide_id in slide_ids:
        slide_dir = run_dir / "slides" / slide_id
        if not slide_dir.exists():
            raise ValidationError(f"Missing slide directory: {slide_dir}")
        validate_slide(
            slide_dir=slide_dir,
            repo_root=repo_root,
            width=width,
            height=height,
            require_full_slide=require_full_slide,
        )

    return len(slide_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a complete article-to-video run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--width", default=DEFAULT_WIDTH, type=int)
    parser.add_argument("--height", default=DEFAULT_HEIGHT, type=int)
    parser.add_argument("--require-full-slide", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = validate_run(
            run_dir=args.run_dir.resolve(),
            repo_root=args.repo_root.resolve(),
            width=args.width,
            height=args.height,
            require_full_slide=args.require_full_slide,
        )
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Validated {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
