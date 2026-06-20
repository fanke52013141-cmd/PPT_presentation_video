#!/usr/bin/env python3
"""Validate reveal_manifest.json before building reveal assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.pipeline_profiles import allowed_reveal_actions, read_pipeline_profile
except ModuleNotFoundError:
    from pipeline_profiles import allowed_reveal_actions, read_pipeline_profile


class ManifestError(RuntimeError):
    pass


ALLOWED_ACTIONS = allowed_reveal_actions(read_pipeline_profile())
APPROVED_REVIEW_STATUSES = {"reviewed", "approved", "manual_reviewed", "manual_adjusted", "locked"}
DEFAULT_PADDING_PX = 32


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


def visual_contract_maps(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if contract.get("version") != "visual_contract_v1":
        raise ManifestError("Contract version must be visual_contract_v1")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ManifestError("Contract must contain non-empty slides[]")
    maps: dict[str, dict[str, Any]] = {}
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id", "")).strip()
        groups = slide.get("visual_groups") if isinstance(slide.get("visual_groups"), list) else []
        beats = slide.get("narration_beats") if isinstance(slide.get("narration_beats"), list) else []
        group_ids: set[str] = set()
        beat_ids: set[str] = set()
        group_content_units: dict[str, str] = {}
        beat_content_units: dict[str, str] = {}
        group_speak_policies: dict[str, str] = {}
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id", "")).strip()
            if not group_id:
                continue
            group_ids.add(group_id)
            group_content_units[group_id] = str(group.get("content_unit_id", "")).strip()
            group_speak_policies[group_id] = str(group.get("speak_policy", "")).strip()
        for beat in beats:
            if not isinstance(beat, dict):
                continue
            beat_id = str(beat.get("id", "")).strip()
            if not beat_id:
                continue
            beat_ids.add(beat_id)
            beat_content_units[beat_id] = str(beat.get("content_unit_id", "")).strip()
        maps[slide_id] = {
            "groups": group_ids,
            "beats": beat_ids,
            "group_content_units": group_content_units,
            "beat_content_units": beat_content_units,
            "group_speak_policies": group_speak_policies,
        }
    return maps


def effective_box(raw_box: dict[str, Any], width: int, height: int, padding: int) -> dict[str, float]:
    x = float(raw_box["x"])
    y = float(raw_box["y"])
    w = float(raw_box["w"])
    h = float(raw_box["h"])
    x1 = max(0.0, x - padding)
    y1 = max(0.0, y - padding)
    x2 = min(float(width), x + w + padding)
    y2 = min(float(height), y + h + padding)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def validate_box(box: Any, width: int, height: int, subtitle_safe_y: int, role: str, group_id: str, padding: int) -> dict[str, float]:
    if not isinstance(box, dict):
        raise ManifestError(f"Group missing box: {group_id}")
    for key in ("x", "y", "w", "h"):
        if not isinstance(box.get(key), (int, float)):
            raise ManifestError(f"Group box missing numeric {key}: {group_id}")
    if box["w"] <= 0 or box["h"] <= 0:
        raise ManifestError(f"Group box has non-positive size: {group_id}")
    if box["x"] < 0 or box["y"] < 0 or box["x"] + box["w"] > width or box["y"] + box["h"] > height:
        raise ManifestError(f"Group raw box outside canvas: {group_id}")
    padded = effective_box(box, width=width, height=height, padding=padding)
    if role != "decoration" and padded["y"] + padded["h"] > subtitle_safe_y:
        raise ManifestError(
            f"Group effective box enters subtitle safe zone after padding: {group_id} "
            f"raw_y2={box['y'] + box['h']} effective_y2={padded['y'] + padded['h']} safe_y={subtitle_safe_y}"
        )
    return padded


def overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(ax2, bx2)
    y2 = min(ay2, by2)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    return float(overlap) / max(1.0, min(float(a["w"] * a["h"]), float(b["w"] * b["h"])))


def validate_semantic_fields(group: dict[str, Any], slide_maps: dict[str, Any], slide_id: str, group_id: str, role: str, beat_id: str) -> None:
    contract_content_units: dict[str, str] = slide_maps.get("group_content_units", {}) if slide_maps else {}
    beat_content_units: dict[str, str] = slide_maps.get("beat_content_units", {}) if slide_maps else {}
    speak_policies: dict[str, str] = slide_maps.get("group_speak_policies", {}) if slide_maps else {}
    manifest_content_unit = str(group.get("content_unit_id", "")).strip()
    contract_content_unit = str(contract_content_units.get(group_id, "")).strip()
    if contract_content_unit:
        if not manifest_content_unit:
            raise ManifestError(f"Reveal group missing content_unit_id copied from contract: {slide_id}/{group_id}")
        if manifest_content_unit != contract_content_unit:
            raise ManifestError(
                f"Reveal group content_unit_id does not match contract: {slide_id}/{group_id} "
                f"{manifest_content_unit} != {contract_content_unit}"
            )
    if role != "decoration" and not str(group.get("mask_target", "")).strip():
        raise ManifestError(f"Reveal group missing mask_target: {slide_id}/{group_id}")
    if speak_policies.get(group_id) == "display_only" and beat_id:
        raise ManifestError(f"Display-only reveal group must not reference narration beat: {slide_id}/{group_id}/{beat_id}")
    if beat_id and beat_content_units.get(beat_id) and manifest_content_unit and beat_content_units[beat_id] != manifest_content_unit:
        raise ManifestError(
            f"Reveal beat content_unit_id does not match group: {slide_id}/{group_id}/{beat_id} "
            f"{beat_content_units[beat_id]} != {manifest_content_unit}"
        )


def validate_slide(slide: dict[str, Any], contract_maps: dict[str, dict[str, Any]] | None, width: int, height: int, subtitle_safe_y: int, max_overlap: float, require_reviewed: bool) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise ManifestError("Slide missing slide_id")
    groups = slide.get("groups")
    if not isinstance(groups, list):
        raise ManifestError(f"Slide groups[] must be a list: {slide_id}")
    if not groups:
        return
    slide_maps = contract_maps.get(slide_id, {}) if contract_maps else {}
    known_groups = slide_maps.get("groups", set()) if contract_maps else set()
    known_beats = slide_maps.get("beats", set()) if contract_maps else set()
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
        raw_beat_id = group.get("narration_beat_id")
        beat_id = str(raw_beat_id or "").strip()
        if beat_id and known_beats and beat_id not in known_beats:
            raise ManifestError(f"Reveal group references unknown beat: {slide_id}/{group_id}/{beat_id}")
        if contract_maps:
            validate_semantic_fields(group, slide_maps, slide_id, group_id, role, beat_id)
        reveal = group.get("reveal")
        if not isinstance(reveal, dict):
            raise ManifestError(f"Group missing reveal object: {slide_id}/{group_id}")
        action = str(reveal.get("type", ""))
        if action not in ALLOWED_ACTIONS:
            raise ManifestError(f"Unsupported reveal action: {slide_id}/{group_id}/{action}")
        status = str(group.get("review_status", "")).strip()
        if require_reviewed and status not in APPROVED_REVIEW_STATUSES:
            raise ManifestError(f"Group is not explicitly reviewed: {slide_id}/{group_id} review_status={status or '<empty>'}")
        padding = int(group.get("padding_px", DEFAULT_PADDING_PX))
        padded_box = validate_box(group.get("box"), width, height, subtitle_safe_y, role, group_id, padding=padding)
        boxes.append((group_id, role, padded_box))
    for index, (left_id, left_role, left_box) in enumerate(boxes):
        for right_id, right_role, right_box in boxes[index + 1 :]:
            if left_role == "decoration" or right_role == "decoration":
                continue
            ratio = overlap_ratio(left_box, right_box)
            if ratio > max_overlap:
                raise ManifestError(f"Effective group boxes overlap too much in {slide_id}: {left_id}/{right_id} ratio={ratio:.3f}")


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
