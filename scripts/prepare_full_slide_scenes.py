#!/usr/bin/env python3
"""
Compatibility wrapper for the former full-slide scene preparation command.

Production now requires decomposed PNG layers. This wrapper preserves the old
CLI entrypoint but delegates to scripts/decompose_slide_layers.py so accidental
use of the old command cannot recreate a single full_slide-only scene.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from decompose_slide_layers import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DecomposeError,
    decompose_run,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deprecated wrapper: decompose full-slide PNG drafts into Remotion PNG layers."
    )
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

    print(
        "prepare_full_slide_scenes.py is deprecated; "
        f"decomposed {count} slide visual(s) into PNG layers instead."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
