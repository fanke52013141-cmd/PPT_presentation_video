#!/usr/bin/env python3
"""Check Step 3 visual_draft.png files for Mask-friendly quality.

The reveal/mask pipeline assumes Step 3 generated images are 1920x1080 with a
mostly pure white background. This local diagnostic checks rendered draft images
inside one project run directory and reports common problems before Step 5.

Usage:
    python scripts/check_visual_draft_quality.py path/to/project/run_dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_SIZE = (1920, 1080)
WHITE_CHANNEL_THRESHOLD = 245
MAX_NON_WHITE_RATIO = 0.28
MAX_BORDER_NON_WHITE_RATIO = 0.04
MAX_SUBTITLE_SAFE_NON_WHITE_RATIO = 0.10
SUBTITLE_SAFE_Y = 930


class QualityFailure(AssertionError):
    """Raised when a visual draft quality check fails."""


def _load_image(path: Path) -> Any:
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise QualityFailure("Pillow is required: pip install pillow") from exc
    try:
        return Image.open(path).convert("RGB")
    except Exception as exc:
        raise QualityFailure(f"Failed to read image {path}: {type(exc).__name__}: {exc}") from exc


def _is_white(pixel: tuple[int, int, int]) -> bool:
    return all(channel >= WHITE_CHANNEL_THRESHOLD for channel in pixel)


def _sample_ratio(image: Any, box: tuple[int, int, int, int], stride: int = 8) -> float:
    x0, y0, x1, y1 = box
    total = 0
    non_white = 0
    pixels = image.load()
    for y in range(max(0, y0), min(image.height, y1), stride):
        for x in range(max(0, x0), min(image.width, x1), stride):
            total += 1
            if not _is_white(pixels[x, y]):
                non_white += 1
    return non_white / total if total else 0.0


def _border_non_white_ratio(image: Any, margin: int = 24) -> float:
    boxes = [
        (0, 0, image.width, margin),
        (0, image.height - margin, image.width, image.height),
        (0, 0, margin, image.height),
        (image.width - margin, 0, image.width, image.height),
    ]
    weighted_total = 0
    weighted_non_white = 0.0
    for box in boxes:
        x0, y0, x1, y1 = box
        area = max(0, x1 - x0) * max(0, y1 - y0)
        ratio = _sample_ratio(image, box, stride=4)
        weighted_total += area
        weighted_non_white += ratio * area
    return weighted_non_white / weighted_total if weighted_total else 0.0


def _check_one_image(path: Path) -> dict[str, Any]:
    image = _load_image(path)
    result = {
        "path": str(path),
        "size": [image.width, image.height],
        "non_white_ratio": round(_sample_ratio(image, (0, 0, image.width, image.height)), 4),
        "border_non_white_ratio": round(_border_non_white_ratio(image), 4),
        "subtitle_safe_non_white_ratio": round(_sample_ratio(image, (0, SUBTITLE_SAFE_Y, image.width, image.height)), 4),
        "issues": [],
    }
    if (image.width, image.height) != EXPECTED_SIZE:
        result["issues"].append(f"expected {EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]}, got {image.width}x{image.height}")
    if result["non_white_ratio"] > MAX_NON_WHITE_RATIO:
        result["issues"].append(f"too much non-white area: {result['non_white_ratio']:.2%}")
    if result["border_non_white_ratio"] > MAX_BORDER_NON_WHITE_RATIO:
        result["issues"].append(f"border is not clean white: {result['border_non_white_ratio']:.2%}")
    if result["subtitle_safe_non_white_ratio"] > MAX_SUBTITLE_SAFE_NON_WHITE_RATIO:
        result["issues"].append(f"subtitle safe area has too much content: {result['subtitle_safe_non_white_ratio']:.2%}")
    return result


def _visual_drafts(run_dir: Path) -> list[Path]:
    return sorted((run_dir / "slides").glob("*/visual_draft.png"))


def check_run_dir(run_dir: Path) -> dict[str, Any]:
    if not run_dir.exists():
        raise QualityFailure(f"run_dir does not exist: {run_dir}")
    drafts = _visual_drafts(run_dir)
    if not drafts:
        raise QualityFailure(f"No visual_draft.png files found under {run_dir / 'slides'}")
    results = [_check_one_image(path) for path in drafts]
    failed = [item for item in results if item["issues"]]
    return {
        "success": not failed,
        "run_dir": str(run_dir),
        "checked_count": len(results),
        "failed_count": len(failed),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Step 3 visual_draft.png quality for Mask-friendly white-background generation.")
    parser.add_argument("run_dir", help="Project run directory containing slides/*/visual_draft.png")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args(argv)

    try:
        report = check_run_dir(Path(args.run_dir).resolve())
    except QualityFailure as exc:
        print(f"FAIL {exc}")
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Checked {report['checked_count']} visual draft image(s).")
        for item in report["results"]:
            slide = Path(item["path"]).parent.name
            if item["issues"]:
                print(f"FAIL {slide}: " + "; ".join(item["issues"]))
            else:
                print(f"PASS {slide}: white-background quality looks acceptable")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
