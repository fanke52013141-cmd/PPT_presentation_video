#!/usr/bin/env python3
"""Auto-fit reveal_manifest.json group boxes against visual_draft.png.

This uses the fixed flat background color to find non-background pixels near each
manifest box. It is an assistant, not a replacement for review: always inspect
the preview image after running this script.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


class FitError(RuntimeError):
    pass


DEFAULT_BACKGROUND = "#FFFDF7"
LOCKED_REVIEW_STATUSES = {"reviewed", "approved", "manual_reviewed", "manual_adjusted", "locked"}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FitError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise FitError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FitError(f"JSON file must contain an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hex_to_rgb(value: str) -> np.ndarray:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise FitError(f"Invalid background color: {value}")
    return np.array([int(text[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def resolve_path(value: str, manifest_dir: Path, slide_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (slide_dir / path, manifest_dir / path, repo_root / path):
        if candidate.exists():
            return candidate
    return slide_dir / path


def clamp_box(box: dict[str, Any], width: int, height: int) -> dict[str, int]:
    x = max(0, min(width - 1, int(round(float(box["x"])))))
    y = max(0, min(height - 1, int(round(float(box["y"])))))
    w = max(1, int(round(float(box["w"]))))
    h = max(1, int(round(float(box["h"]))))
    if x + w > width:
        w = width - x
    if y + h > height:
        h = height - y
    return {"x": x, "y": y, "w": w, "h": h}


def expand_box(box: dict[str, int], width: int, height: int, margin: int) -> dict[str, int]:
    x1 = max(0, box["x"] - margin)
    y1 = max(0, box["y"] - margin)
    x2 = min(width, box["x"] + box["w"] + margin)
    y2 = min(height, box["y"] + box["h"] + margin)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def fit_box(image: Image.Image, box: dict[str, int], background: str, threshold: float, search_margin: int, padding: int, subtitle_safe_y: int, role: str, max_area_ratio: float) -> tuple[dict[str, int], dict[str, Any]]:
    width, height = image.size
    if role in {"title", "subtitle"}:
        return box, {"fit_status": "skipped_static_header", "search_box": box}
    search = expand_box(box, width, height, search_margin)
    region = np.asarray(image.crop((search["x"], search["y"], search["x"] + search["w"], search["y"] + search["h"])).convert("RGB"), dtype=np.float32)
    bg = hex_to_rgb(background)
    dist = np.linalg.norm(region - bg, axis=2)
    mask = dist > threshold
    marked = int(mask.sum())
    min_pixels = max(24, int(search["w"] * search["h"] * 0.001))
    if marked < min_pixels:
        return box, {"fit_status": "unchanged_no_content_detected", "marked_pixels": marked, "search_box": search}
    ys, xs = np.where(mask)
    x1 = max(0, int(xs.min()) + search["x"] - padding)
    y1 = max(0, int(ys.min()) + search["y"] - padding)
    x2 = min(width, int(xs.max()) + search["x"] + padding + 1)
    y2 = min(height, int(ys.max()) + search["y"] + padding + 1)
    if role != "decoration":
        safe_bottom = max(1, subtitle_safe_y - padding)
        y2 = min(y2, safe_bottom)
        if y2 <= y1:
            y1 = max(0, safe_bottom - 1)
            y2 = safe_bottom
    fitted = {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}
    area_before = box["w"] * box["h"]
    area_after = fitted["w"] * fitted["h"]
    if area_after > area_before * max_area_ratio:
        return box, {
            "fit_status": "unchanged_expansion_too_large",
            "marked_pixels": marked,
            "search_box": search,
            "area_before": area_before,
            "area_after": area_after,
            "area_ratio": round(area_after / max(1, area_before), 3),
            "max_area_ratio": max_area_ratio,
        }
    return fitted, {
        "fit_status": "auto_fitted",
        "marked_pixels": marked,
        "search_box": search,
        "area_before": area_before,
        "area_after": area_after,
        "area_ratio": round(area_after / max(1, area_before), 3),
    }


def fit_manifest(manifest: dict[str, Any], manifest_path: Path, repo_root: Path, threshold: float, search_margin: int, padding: int, max_area_ratio: float, overwrite_reviewed: bool) -> dict[str, Any]:
    if manifest.get("version") != "reveal_v1":
        raise FitError("Manifest version must be reveal_v1")
    canvas = manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {}
    background = str(canvas.get("background", DEFAULT_BACKGROUND))
    width = int(canvas.get("width", 1920))
    height = int(canvas.get("height", 1080))
    subtitle_safe_y = int(canvas.get("subtitle_safe_y", 930))
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        raise FitError("Manifest must contain non-empty slides[]")
    report: dict[str, Any] = {"version": "auto_fit_report_v1", "locked_statuses": sorted(LOCKED_REVIEW_STATUSES), "slides": []}
    manifest_dir = manifest_path.parent
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id", ""))
        slide_dir = resolve_path(str(slide.get("slide_dir", "")), manifest_dir, manifest_dir, repo_root)
        master_path = resolve_path(str(slide.get("master", "visual_draft.png")), manifest_dir, slide_dir, repo_root)
        if not master_path.exists():
            raise FitError(f"Missing visual_draft image for {slide_id}: {master_path}")
        image = Image.open(master_path).convert("RGB")
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        groups = slide.get("groups")
        if not isinstance(groups, list):
            continue
        slide_report = {"slide_id": slide_id, "groups": []}
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("box"), dict):
                continue
            group_id = str(group.get("id", ""))
            status = str(group.get("review_status", "")).strip()
            if status in LOCKED_REVIEW_STATUSES and not overwrite_reviewed:
                slide_report["groups"].append({"id": group_id, "fit_status": "skipped_locked_review_status", "review_status": status})
                continue
            role = str(group.get("role", "content_body"))
            base_box = clamp_box(group["box"], width, height)
            group_padding = int(group.get("padding_px", padding))
            fitted, meta = fit_box(
                image=image,
                box=base_box,
                background=background,
                threshold=threshold,
                search_margin=search_margin,
                # The build step applies group padding again, so auto-fit only
                # keeps a small content margin here to avoid double expansion.
                padding=padding,
                subtitle_safe_y=subtitle_safe_y,
                role=role,
                max_area_ratio=max_area_ratio,
            )
            group["box"] = fitted
            group["review_status"] = "auto_fitted_needs_review"
            group["auto_fit"] = meta
            slide_report["groups"].append({"id": group_id, **meta, "box": fitted})
        report["slides"].append(slide_report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-fit reveal boxes using background-color detection.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--threshold", type=float, default=18.0)
    parser.add_argument("--search-margin", type=int, default=80)
    parser.add_argument("--padding", type=int, default=32)
    parser.add_argument("--max-area-ratio", type=float, default=1.8)
    parser.add_argument("--overwrite-reviewed", action="store_true")
    parser.add_argument("--out", type=Path, help="Defaults to overwriting --manifest")
    parser.add_argument("--report", type=Path, help="Defaults to <manifest>.auto_fit_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest_path = args.manifest.resolve()
        manifest = read_json(manifest_path)
        report = fit_manifest(
            manifest,
            manifest_path=manifest_path,
            repo_root=args.repo_root.resolve(),
            threshold=args.threshold,
            search_margin=args.search_margin,
            padding=args.padding,
            max_area_ratio=args.max_area_ratio,
            overwrite_reviewed=args.overwrite_reviewed,
        )
        out_path = args.out.resolve() if args.out else manifest_path
        report_path = args.report.resolve() if args.report else manifest_path.with_suffix(".auto_fit_report.json")
        write_json(out_path, manifest)
        write_json(report_path, report)
    except FitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote fitted manifest: {out_path}")
    print(f"Wrote fit report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
