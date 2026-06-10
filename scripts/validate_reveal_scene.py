#!/usr/bin/env python3
"""Validate reveal scene outputs before Remotion rendering."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image


class RevealValidationError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RevealValidationError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RevealValidationError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RevealValidationError(f"JSON file must contain an object: {path}")
    return value


def image_size(path: Path) -> tuple[int, int]:
    if not path.exists():
        raise RevealValidationError(f"Missing PNG asset: {path}")
    if path.suffix.lower() != ".png":
        raise RevealValidationError(f"Expected PNG asset: {path}")
    with Image.open(path) as image:
        return image.size


def resolve_asset(asset: str, slide_dir: Path, repo_root: Path) -> Path:
    path = Path(asset)
    if path.is_absolute():
        return path
    for candidate in (slide_dir / path, repo_root / path):
        if candidate.exists():
            return candidate
    return slide_dir / path


def validate_scene(slide_dir: Path, repo_root: Path, width: int, height: int, require_no_blocking: bool) -> None:
    scene = read_json(slide_dir / "scene.json")
    if scene.get("visual_source") != "master_reveal_layers":
        raise RevealValidationError(f"Scene is not a master reveal scene: {slide_dir / 'scene.json'}")
    report = read_json(slide_dir / "reveal_report.json")
    if require_no_blocking:
        warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
        blocking = [w for w in warnings if isinstance(w, dict) and str(w.get("severity")) == "blocking"]
        if blocking:
            types = ", ".join(str(w.get("type", "unknown")) for w in blocking)
            raise RevealValidationError(f"Blocking reveal warnings in {slide_dir}: {types}")
    layers = scene.get("layers")
    if not isinstance(layers, list) or not layers:
        raise RevealValidationError(f"scene.json must contain layers[]: {slide_dir}")
    layer_ids: set[str] = set()
    has_full_slide = False
    for layer in layers:
        if not isinstance(layer, dict):
            raise RevealValidationError(f"Invalid layer object in {slide_dir}")
        layer_id = str(layer.get("id", ""))
        if not layer_id:
            raise RevealValidationError(f"Layer missing id in {slide_dir}")
        if layer_id in layer_ids:
            raise RevealValidationError(f"Duplicate layer id in {slide_dir}: {layer_id}")
        layer_ids.add(layer_id)
        if layer.get("type") != "png":
            raise RevealValidationError(f"Layer type must be png in {slide_dir}: {layer_id}")
        box = layer.get("box")
        if not isinstance(box, dict):
            raise RevealValidationError(f"Layer missing box in {slide_dir}: {layer_id}")
        for key in ["x", "y", "w", "h"]:
            if not isinstance(box.get(key), (int, float)):
                raise RevealValidationError(f"Layer box missing numeric {key}: {slide_dir}: {layer_id}")
        if box["x"] < 0 or box["y"] < 0 or box["x"] + box["w"] > width or box["y"] + box["h"] > height:
            raise RevealValidationError(f"Layer box outside canvas in {slide_dir}: {layer_id}")
        asset_path = resolve_asset(str(layer.get("asset", "")), slide_dir, repo_root)
        actual = image_size(asset_path)
        expected = (int(round(float(box["w"]))), int(round(float(box["h"]))))
        if actual != expected:
            raise RevealValidationError(f"PNG dimension mismatch for {layer_id}: {actual} != {expected}")
        if layer.get("role") == "full_slide":
            has_full_slide = True
    if not has_full_slide:
        raise RevealValidationError(f"Reveal scene must include a full_slide layer: {slide_dir}")
    timeline = read_json(slide_dir / "animation_timeline.json")
    events = timeline.get("events")
    if not isinstance(events, list):
        raise RevealValidationError(f"animation_timeline.json must contain events[]: {slide_dir}")
    for event in events:
        if not isinstance(event, dict):
            raise RevealValidationError(f"Invalid animation event in {slide_dir}")
        target = str(event.get("target", ""))
        if target not in layer_ids:
            raise RevealValidationError(f"Animation event targets unknown layer in {slide_dir}: {target}")
        for key in ["action", "at", "duration"]:
            if key not in event:
                raise RevealValidationError(f"Animation event missing {key}: {slide_dir}: {event.get('id')}")


def slide_dirs_from_args(run_dir: Path | None, slide_dir: Path | None) -> list[Path]:
    if slide_dir:
        return [slide_dir.resolve()]
    if not run_dir:
        raise RevealValidationError("Provide --run-dir or --slide-dir")
    slides_root = run_dir.resolve() / "slides"
    if not slides_root.exists():
        raise RevealValidationError(f"Missing slides directory: {slides_root}")
    slide_dirs = sorted(path for path in slides_root.iterdir() if path.is_dir())
    if not slide_dirs:
        raise RevealValidationError(f"No slide directories found: {slides_root}")
    return slide_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate reveal scene assets.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", type=Path)
    group.add_argument("--slide-dir", type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--allow-blocking-warnings", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        slide_dirs = slide_dirs_from_args(args.run_dir, args.slide_dir)
        for slide_dir in slide_dirs:
            validate_scene(
                slide_dir=slide_dir,
                repo_root=args.repo_root.resolve(),
                width=args.width,
                height=args.height,
                require_no_blocking=not args.allow_blocking_warnings,
            )
    except RevealValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Validated reveal scene for {len(slide_dirs)} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
