#!/usr/bin/env python3
"""
Validate that split macro layers recompose into an acceptable slide preview.

This is a visual QA gate for the master-split production path. It checks that
the split report exists, blocking warnings are absent, layer count is sane, and
the recomposed preview remains close enough to the Image Gen master image in
the actual content area.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class RecompositionError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RecompositionError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RecompositionError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecompositionError(f"JSON file must contain an object: {path}")
    return value


def validate_slide(
    slide_dir: Path,
    max_content_diff: float,
    min_content_layers: int,
    max_content_layers: int,
    fail_on_warnings: bool,
    require_narration_beats: bool,
) -> None:
    scene = read_json(slide_dir / "scene.json")
    if scene.get("visual_source") != "master_split_image_layers":
        raise RecompositionError(f"Scene is not a master-split scene: {slide_dir / 'scene.json'}")

    render_preview = slide_dir / "render_preview.png"
    if not render_preview.exists():
        raise RecompositionError(f"Missing render_preview.png: {slide_dir}")

    split_report = read_json(slide_dir / "split_report.json")
    warnings = split_report.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    blocking = [
        warning
        for warning in warnings
        if isinstance(warning, dict) and str(warning.get("severity", "warning")) == "blocking"
    ]
    if blocking:
        names = ", ".join(str(warning.get("type", "unknown")) for warning in blocking)
        raise RecompositionError(f"Blocking split warnings in {slide_dir}: {names}")
    if fail_on_warnings and warnings:
        names = ", ".join(str(warning.get("type", "unknown")) for warning in warnings if isinstance(warning, dict))
        raise RecompositionError(f"Split warnings must be resolved in {slide_dir}: {names}")

    layers = scene.get("layers")
    if not isinstance(layers, list):
        raise RecompositionError(f"scene.json missing layers[]: {slide_dir}")
    content_layers = [
        layer
        for layer in layers
        if isinstance(layer, dict) and layer.get("role") not in {"background", "decoration"}
    ]
    if len(content_layers) < min_content_layers or len(content_layers) > max_content_layers:
        raise RecompositionError(
            f"Expected {min_content_layers}-{max_content_layers} content macro layers in {slide_dir}, "
            f"got {len(content_layers)}"
        )
    if require_narration_beats:
        missing = [
            str(layer.get("id", "unknown"))
            for layer in content_layers
            if not str(layer.get("narration_beat_id", "")).strip()
        ]
        if missing:
            raise RecompositionError(f"Layers missing narration_beat_id in {slide_dir}: {', '.join(missing)}")

    metrics = split_report.get("metrics")
    if not isinstance(metrics, dict):
        raise RecompositionError(f"split_report.json missing metrics: {slide_dir}")
    content_diff = metrics.get("content_mean_abs_diff")
    if not isinstance(content_diff, (int, float)):
        raise RecompositionError(f"split_report metrics missing content_mean_abs_diff: {slide_dir}")
    if float(content_diff) > max_content_diff:
        raise RecompositionError(
            f"Content recomposition diff is too high in {slide_dir}: "
            f"{float(content_diff):.3f} > {max_content_diff:.3f}"
        )


def slide_dirs_from_args(run_dir: Path | None, slide_dir: Path | None) -> list[Path]:
    if slide_dir:
        return [slide_dir.resolve()]
    if not run_dir:
        raise RecompositionError("Provide --run-dir or --slide-dir")
    slides_root = run_dir.resolve() / "slides"
    if not slides_root.exists():
        raise RecompositionError(f"Missing slides directory: {slides_root}")
    slide_dirs = sorted(path for path in slides_root.iterdir() if path.is_dir())
    if not slide_dirs:
        raise RecompositionError(f"No slide directories found: {slides_root}")
    return slide_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate master-split layer recomposition quality.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", type=Path)
    group.add_argument("--slide-dir", type=Path)
    parser.add_argument("--max-content-diff", type=float, default=18.0)
    parser.add_argument("--min-content-layers", type=int, default=4)
    parser.add_argument("--max-content-layers", type=int, default=8)
    parser.add_argument("--fail-on-warnings", action="store_true")
    parser.add_argument("--require-narration-beats", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        slide_dirs = slide_dirs_from_args(args.run_dir, args.slide_dir)
        for slide_dir in slide_dirs:
            validate_slide(
                slide_dir=slide_dir,
                max_content_diff=args.max_content_diff,
                min_content_layers=args.min_content_layers,
                max_content_layers=args.max_content_layers,
                fail_on_warnings=args.fail_on_warnings,
                require_narration_beats=args.require_narration_beats,
            )
    except RecompositionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Validated recomposition for {len(slide_dirs)} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
