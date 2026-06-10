#!/usr/bin/env python3
"""Validate reveal_manifest.json before building reveal assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ManifestError(RuntimeError):
    pass


ALLOWED_ACTIONS = {
    "cover_fade_out",
    "cover_wipe_left_to_right",
    "cover_wipe_top_to_bottom",
    "fog_diagonal_erase",
    "crop_fade_up",
    "crop_slide_in_left",
    "crop_soft_zoom_in",
    "highlight",
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ManifestError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"JSON file must contain an object: {path}")
    return value


def visual_contract_maps(contract: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    if contract.get("version") != "visual_contract_v1":
        raise ManifestError("Contract version must be visual_contract_v1")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ManifestError("Contract must contain non-empty slides[]")
    maps: dict[str, dict[str, set[str]]] = {}
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id", "")).strip()
        groups = slide.get("visual_groups") if isinstance(slide.get("visual_groups"), list) else []
        beats = slide.get("narration_beats") if isinstance(slide.get("narration_beats"), list) else []
        maps[slide_id] = {
            "groups": {str(group.get("id", "")) for group in groups if isinstance(group, dict) and str(group.get("id", ""))},
            "beats": {str(beat.get("id", "")) for beat in beats if isinstance(beat, dict) and str(beat.get("id", ""))},
        }
    return maps


def validate_box(box: Any, width: int, height: int, subtitle_safe_y: int, role: str, group_id: str) -> None:
    if not isinstance(box, dict):
        raise ManifestError(f"Group missing box: {group_id}")
    for key in ("x", "y", "w", "h"):
        if not isinstance(box.get(key), (int, float)):
            raise ManifestError(f"Group box missing numeric {key}: {group_id}")
    if box["w"] <= 0 or box["h"] <= 0:
        raise ManifestError(f"Group box has non-positive size: {group_id}")
    if box["x"] < 0 or box["y"] < 0 or box["x"] + box["w"] > width or box["y"] + box["h"] > height:
        raise ManifestError(f"Group box outside canvas: {group_id}")
    if role != "decoration" and box["y"] + box["h"] > subtitle_safe_y:
        raise ManifestError(f"Group enters subtitle safe zone: {group_id}")


def overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(ax2, bx2)
    y2 = min(ay2, by2)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    return float(overlap) / max(1.0, min(float(a["w"] * a["h"]), float(b["w"] * b["h"])))


def validate_slide(slide: dict[str, Any], contract_maps: dict[str, dict[str, set[str]]] | None, width: int, height: int, subtitle_safe_y: int, max_overlap: float, require_reviewed: bool) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise ManifestError("Slide missing slide_id")
    groups = slide.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ManifestError(f"Slide missing groups[]: {slide_id}")
    known_groups = contract_maps.get(slide_id, {}).get("groups", set()) if contract_maps else set()
    known_beats = contract_maps.get(slide_id, {}).get("beats", set()) if contract_maps else set()
    seen: set[str] = set()
    boxes: list[tuple[str, str, dict[str, Any]]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise ManifestError(f"Invalid group object in {slide_id}")
        group_id = str(group.get("id", "")).strip()
        role = str(group.get("role", "content_body"))
        if not group_id:
            raise ManifestError(f"Group missing id in {slide_id}")
        if group_id in seen:
            raise ManifestError(f"Duplicate group id in {slide_id}: {group_id}")
        seen.add(group_id)
        if known_groups and group_id not in known_groups:
            raise ManifestError(f"Reveal group not found in visual contract: {slide_id}/{group_id}")
        beat_id = str(group.get("narration_beat_id", "")).strip()
        if beat_id and known_beats and beat_id not in known_beats:
            raise ManifestError(f"Reveal group references unknown beat: {slide_id}/{group_id}/{beat_id}")
        reveal = group.get("reveal")
        if not isinstance(reveal, dict):
            raise ManifestError(f"Group missing reveal object: {slide_id}/{group_id}")
        action = str(reveal.get("type", ""))
        if action not in ALLOWED_ACTIONS:
            raise ManifestError(f"Unsupported reveal action: {slide_id}/{group_id}/{action}")
        validate_box(group.get("box"), width, height, subtitle_safe_y, role, group_id)
        if require_reviewed and str(group.get("review_status", "")).startswith("needs_"):
            raise ManifestError(f"Group still needs manual review: {slide_id}/{group_id}")
        boxes.append((group_id, role, group["box"]))
    for index, (left_id, left_role, left_box) in enumerate(boxes):
        for right_id, right_role, right_box in boxes[index + 1 :]:
            if left_role == "decoration" or right_role == "decoration":
                continue
            ratio = overlap_ratio(left_box, right_box)
            if ratio > max_overlap:
                raise ManifestError(f"Group boxes overlap too much in {slide_id}: {left_id}/{right_id} ratio={ratio:.3f}")


def validate_manifest(manifest: dict[str, Any], contract: dict[str, Any] | None, require_reviewed: bool, max_overlap: float) -> int:
    if manifest.get("version") != "reveal_v1":
        raise ManifestError("Manifest version must be reveal_v1")
    canvas = manifest.get("canvas") if isinstance(manifest.get("canvas"), dict) else {}
    width = int(canvas.get("width", 1920))
    height = int(canvas.get("height", 1080))
    subtitle_safe_y = int(canvas.get("subtitle_safe_y", 930))
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ManifestError("Manifest must contain non-empty slides[]")
    maps = visual_contract_maps(contract) if contract else None
    for slide in slides:
        if not isinstance(slide, dict):
            raise ManifestError("Each slide must be an object")
        validate_slide(slide, maps, width, height, subtitle_safe_y, max_overlap=max_overlap, require_reviewed=require_reviewed)
    return len(slides)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate reveal_manifest.json before building assets.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--require-reviewed", action="store_true")
    parser.add_argument("--max-overlap", type=float, default=0.18)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        contract = read_json(args.contract.resolve()) if args.contract else None
        count = validate_manifest(read_json(args.manifest.resolve()), contract, require_reviewed=args.require_reviewed, max_overlap=args.max_overlap)
    except ManifestError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Validated reveal manifest for {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
