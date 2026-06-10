#!/usr/bin/env python3
"""Validate that narration files stay grounded in visual_contract.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


class GroundingError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GroundingError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise GroundingError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GroundingError(f"JSON file must contain an object: {path}")
    return value


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def contract_slides(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if contract.get("version") != "visual_contract_v1":
        raise GroundingError("Contract version must be visual_contract_v1")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        raise GroundingError("Contract must contain non-empty slides[]")
    result: dict[str, dict[str, Any]] = {}
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id", "")).strip()
        if slide_id:
            result[slide_id] = slide
    return result


def group_map(slide: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = slide.get("visual_groups")
    if not isinstance(groups, list):
        raise GroundingError(f"Slide missing visual_groups[]: {slide.get('slide_id')}")
    result: dict[str, dict[str, Any]] = {}
    for group in groups:
        if isinstance(group, dict) and str(group.get("id", "")).strip():
            result[str(group["id"])] = group
    return result


def validate_slide(run_dir: Path, slide: dict[str, Any], strict_literal: bool) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    groups = group_map(slide)
    beats_path = run_dir / "slides" / slide_id / "narration_beats.json"
    beats_data = read_json(beats_path)
    beats = beats_data.get("beats")
    if not isinstance(beats, list) or not beats:
        raise GroundingError(f"narration_beats.json must contain non-empty beats[]: {beats_path}")
    referenced_groups: set[str] = set()
    for beat in beats:
        if not isinstance(beat, dict):
            raise GroundingError(f"Invalid beat in {beats_path}")
        beat_id = str(beat.get("id", "")).strip()
        group_id = str(beat.get("group_id", "")).strip()
        if group_id not in groups:
            raise GroundingError(f"Beat {beat_id} references unknown group_id in {slide_id}: {group_id}")
        referenced_groups.add(group_id)
        group = groups[group_id]
        spoken = normalize(str(beat.get("spoken_text", "")))
        anchor = normalize(str(beat.get("visible_anchor", "")))
        visible = normalize(str(group.get("visible_text", "")))
        if not spoken:
            raise GroundingError(f"Beat {beat_id} has empty spoken_text in {slide_id}")
        if strict_literal and visible and visible not in spoken and anchor and anchor not in spoken:
            raise GroundingError(f"Beat {beat_id} does not mention visible text or anchor in {slide_id}: {group_id}")
        if not strict_literal and visible and visible not in spoken and anchor and anchor not in spoken:
            print(f"Warning: beat {beat_id} does not literally mention visible text/anchor: {slide_id}/{group_id}", file=sys.stderr)
    unreferenced = []
    for group_id, group in groups.items():
        role = str(group.get("role", ""))
        if role in {"title", "subtitle", "decoration"}:
            continue
        if group_id not in referenced_groups:
            unreferenced.append(group_id)
    if unreferenced:
        raise GroundingError(f"Content visual groups are not referenced by narration in {slide_id}: {', '.join(unreferenced)}")


def validate(contract_path: Path, run_dir: Path, strict_literal: bool) -> int:
    slides = contract_slides(read_json(contract_path))
    for slide in slides.values():
        validate_slide(run_dir, slide, strict_literal=strict_literal)
    return len(slides)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate narration grounding against visual contract.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--contract", type=Path, help="Defaults to <run-dir>/planning/visual_contract.json")
    parser.add_argument("--strict-literal", action="store_true", help="Require spoken_text to literally include visible text or anchor.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = args.contract or args.run_dir / "planning" / "visual_contract.json"
    try:
        count = validate(contract_path.resolve(), args.run_dir.resolve(), strict_literal=args.strict_literal)
    except GroundingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Validated narration grounding for {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
