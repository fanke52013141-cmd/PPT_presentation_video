#!/usr/bin/env python3
"""Validate visual_contract.json grounding between content units, visual groups, and narration beats."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.pipeline_profiles import display_only_roles, read_pipeline_profile, speak_policy_for_role
except ModuleNotFoundError:
    from pipeline_profiles import display_only_roles, read_pipeline_profile, speak_policy_for_role


class ContractError(RuntimeError):
    pass


ALLOWED_SPEAK_POLICIES = {"speak", "display_only"}


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


def speak_policy_for(group: dict[str, Any]) -> str:
    explicit = str(group.get("speak_policy", "")).strip()
    if explicit:
        return explicit
    role = str(group.get("role", ""))
    return speak_policy_for_role(role)


def require_non_empty(value: Any, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractError(message)
    return text


def validate_group_semantics(slide_id: str, group: dict[str, Any], group_id: str, role: str) -> tuple[str, str]:
    profile = read_pipeline_profile()
    configured_display_only_roles = display_only_roles(profile)
    content_unit_id = require_non_empty(
        group.get("content_unit_id"),
        f"Visual group {group_id} missing content_unit_id in {slide_id}",
    )
    policy = speak_policy_for(group)
    if policy not in ALLOWED_SPEAK_POLICIES:
        raise ContractError(f"Visual group {group_id} has invalid speak_policy in {slide_id}: {policy}")
    if role in configured_display_only_roles and policy != "display_only":
        raise ContractError(f"Display-only role must use speak_policy=display_only in {slide_id}: {group_id}/{role}")
    if role != "decoration":
        require_non_empty(group.get("mask_target"), f"Visual group {group_id} missing mask_target in {slide_id}")
    return content_unit_id, policy


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
    content_unit_ids: set[str] = set()
    visible_text_by_id: dict[str, str] = {}
    content_unit_by_group_id: dict[str, str] = {}
    speak_policy_by_group_id: dict[str, str] = {}
    role_by_group_id: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise ContractError(f"Invalid visual group in {slide_id}")
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            raise ContractError(f"Visual group missing id in {slide_id}")
        if group_id in group_ids:
            raise ContractError(f"Duplicate visual group id in {slide_id}: {group_id}")
        group_ids.add(group_id)
        role = str(group.get("role", "content_body")).strip()
        role_by_group_id[group_id] = role
        for key in ["visible_text", "visual_anchor", "narration_function"]:
            if not str(group.get(key, "")).strip():
                raise ContractError(f"Visual group {group_id} missing {key} in {slide_id}")
        content_unit_id, policy = validate_group_semantics(slide_id, group, group_id, role)
        if content_unit_id in content_unit_ids:
            raise ContractError(f"Duplicate content_unit_id in {slide_id}: {content_unit_id}")
        content_unit_ids.add(content_unit_id)
        content_unit_by_group_id[group_id] = content_unit_id
        speak_policy_by_group_id[group_id] = policy
        visible_text_by_id[group_id] = str(group.get("visible_text", "")).strip()
    beats = slide.get("narration_beats")
    if not isinstance(beats, list) or not beats:
        raise ContractError(f"Slide missing narration_beats[]: {slide_id}")
    referenced_groups: set[str] = set()
    referenced_content_units: set[str] = set()
    beat_ids: set[str] = set()
    for beat in beats:
        if not isinstance(beat, dict):
            raise ContractError(f"Invalid narration beat in {slide_id}")
        beat_id = str(beat.get("id", "")).strip()
        group_id = str(beat.get("group_id", "")).strip()
        content_unit_id = str(beat.get("content_unit_id", "")).strip()
        if not beat_id:
            raise ContractError(f"Narration beat missing id in {slide_id}")
        if beat_id in beat_ids:
            raise ContractError(f"Duplicate narration beat id in {slide_id}: {beat_id}")
        beat_ids.add(beat_id)
        if group_id not in group_ids:
            raise ContractError(f"Beat {beat_id} references unknown group_id in {slide_id}: {group_id}")
        expected_content_unit_id = content_unit_by_group_id[group_id]
        if not content_unit_id:
            raise ContractError(f"Beat {beat_id} missing content_unit_id in {slide_id}")
        if content_unit_id != expected_content_unit_id:
            raise ContractError(
                f"Beat {beat_id} content_unit_id does not match group in {slide_id}: "
                f"{content_unit_id} != {expected_content_unit_id}"
            )
        if speak_policy_by_group_id[group_id] == "display_only":
            raise ContractError(f"Beat {beat_id} references display_only group in {slide_id}: {group_id}")
        referenced_groups.add(group_id)
        referenced_content_units.add(content_unit_id)
        for key in ["visible_anchor", "spoken_intent"]:
            if not str(beat.get(key, "")).strip():
                raise ContractError(f"Beat {beat_id} missing {key} in {slide_id}")
        spoken_text = str(beat.get("spoken_text", "")).strip()
        visible_anchor = str(beat.get("visible_anchor", "")).strip()
        visible_text = visible_text_by_id.get(group_id, "")
        if spoken_text and visible_anchor not in spoken_text and visible_text not in spoken_text:
            print(
                f"Warning: beat {beat_id} in {slide_id} does not literally mention its visible anchor/text.",
                file=sys.stderr,
            )
    unreferenced = []
    for group_id, role in role_by_group_id.items():
        policy = speak_policy_by_group_id[group_id]
        if policy == "display_only" or role == "decoration":
            continue
        if group_id not in referenced_groups:
            unreferenced.append(group_id)
    if unreferenced:
        raise ContractError(f"Speakable visual groups are not referenced by narration in {slide_id}: {', '.join(unreferenced)}")
    missing_content_units = [
        content_unit_by_group_id[group_id]
        for group_id, policy in speak_policy_by_group_id.items()
        if policy == "speak" and content_unit_by_group_id[group_id] not in referenced_content_units
    ]
    if missing_content_units:
        raise ContractError(f"Speakable content units are not referenced by narration in {slide_id}: {', '.join(missing_content_units)}")


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
