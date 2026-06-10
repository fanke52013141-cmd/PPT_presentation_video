#!/usr/bin/env python3
"""Validate visual_contract.json grounding between visual groups and narration beats."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ContractError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ContractError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON file must contain an object: {path}")
    return value


def validate_slide(slide: dict[str, Any], min_groups: int, max_groups: int) -> None:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise ContractError("Slide missing slide_id")
    groups = slide.get("visual_groups")
    if not isinstance(groups, list) or not groups:
        raise ContractError(f"Slide missing visual_groups[]: {slide_id}")
    if len(groups) < min_groups or len(groups) > max_groups:
        raise ContractError(f"Expected {min_groups}-{max_groups} visual groups in {slide_id}, got {len(groups)}")
    group_ids: set[str] = set()
    visible_text_by_id: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise ContractError(f"Invalid visual group in {slide_id}")
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            raise ContractError(f"Visual group missing id in {slide_id}")
        if group_id in group_ids:
            raise ContractError(f"Duplicate visual group id in {slide_id}: {group_id}")
        group_ids.add(group_id)
        for key in ["visible_text", "visual_anchor", "narration_function"]:
            if not str(group.get(key, "")).strip():
                raise ContractError(f"Visual group {group_id} missing {key} in {slide_id}")
        visible_text_by_id[group_id] = str(group.get("visible_text", "")).strip()
    beats = slide.get("narration_beats")
    if not isinstance(beats, list) or not beats:
        raise ContractError(f"Slide missing narration_beats[]: {slide_id}")
    referenced_groups: set[str] = set()
    for beat in beats:
        if not isinstance(beat, dict):
            raise ContractError(f"Invalid narration beat in {slide_id}")
        beat_id = str(beat.get("id", "")).strip()
        group_id = str(beat.get("group_id", "")).strip()
        if not beat_id:
            raise ContractError(f"Narration beat missing id in {slide_id}")
        if group_id not in group_ids:
            raise ContractError(f"Beat {beat_id} references unknown group_id in {slide_id}: {group_id}")
        referenced_groups.add(group_id)
        for key in ["visible_anchor", "spoken_intent"]:
            if not str(beat.get(key, "")).strip():
                raise ContractError(f"Beat {beat_id} missing {key} in {slide_id}")
        spoken_text = str(beat.get("spoken_text", "")).strip()
        visible_anchor = str(beat.get("visible_anchor", "")).strip()
        visible_text = visible_text_by_id.get(group_id, "")
        if spoken_text and visible_anchor not in spoken_text and visible_text not in spoken_text:
            # Grounding can be semantic rather than literal, so this is a warning-level gate.
            print(
                f"Warning: beat {beat_id} in {slide_id} does not literally mention its visible anchor/text.",
                file=sys.stderr,
            )
    unreferenced = sorted(group_ids - referenced_groups)
    content_unreferenced = [group_id for group_id in unreferenced if not group_id.startswith(("title", "subtitle"))]
    if content_unreferenced:
        raise ContractError(f"Visual groups are not referenced by any beat in {slide_id}: {', '.join(content_unreferenced)}")


def validate_contract(contract: dict[str, Any], min_groups: int, max_groups: int) -> int:
    if contract.get("version") != "visual_contract_v1":
        raise ContractError("Contract version must be visual_contract_v1")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ContractError("Contract must contain non-empty slides[]")
    for slide in slides:
        if not isinstance(slide, dict):
            raise ContractError("Each slide must be an object")
        validate_slide(slide, min_groups=min_groups, max_groups=max_groups)
    return len(slides)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate visual narration grounding contract.")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--min-groups", type=int, default=3)
    parser.add_argument("--max-groups", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = validate_contract(read_json(args.contract), min_groups=args.min_groups, max_groups=args.max_groups)
    except ContractError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Validated visual contract for {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
