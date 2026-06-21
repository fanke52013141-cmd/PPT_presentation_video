#!/usr/bin/env python3
"""Generate a first-pass reveal_manifest.json from visual_contract.json.

The output is a coordinate template. Review and adjust each group box after
looking at the actual Image Gen `visual_draft.png`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.pipeline_profiles import default_reveal_for_role
except ModuleNotFoundError:
    from pipeline_profiles import default_reveal_for_role


class TemplateError(RuntimeError):
    pass


CANVAS = {"width": 1920, "height": 1080, "background": "#FEFDF9", "subtitle_safe_y": 930}
SEMANTIC_FIELDS = [
    "content_unit_id",
    "source_text",
    "speak_policy",
    "mask_target",
    "must_include",
    "must_not_include",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise TemplateError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise TemplateError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TemplateError(f"JSON file must contain an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def content_slots(count: int) -> list[dict[str, int]]:
    # Slots stay inside x=80..1840, y=235..900, leaving room for header and subtitles.
    if count <= 0:
        return []
    if count == 1:
        return [{"x": 360, "y": 330, "w": 1200, "h": 360}]
    if count == 2:
        return [
            {"x": 140, "y": 330, "w": 760, "h": 360},
            {"x": 1020, "y": 330, "w": 760, "h": 360},
        ]
    if count == 3:
        return [
            {"x": 110, "y": 300, "w": 520, "h": 280},
            {"x": 700, "y": 300, "w": 520, "h": 280},
            {"x": 1290, "y": 300, "w": 520, "h": 280},
        ]
    if count == 4:
        return [
            {"x": 150, "y": 270, "w": 720, "h": 250},
            {"x": 1050, "y": 270, "w": 720, "h": 250},
            {"x": 150, "y": 610, "w": 720, "h": 230},
            {"x": 1050, "y": 610, "w": 720, "h": 230},
        ]
    return [
        {"x": 110, "y": 260, "w": 520, "h": 220},
        {"x": 700, "y": 260, "w": 520, "h": 220},
        {"x": 1290, "y": 260, "w": 520, "h": 220},
        {"x": 260, "y": 585, "w": 620, "h": 220},
        {"x": 1040, "y": 585, "w": 620, "h": 220},
    ][:count]


def default_reveal(role: str) -> dict[str, Any]:
    return default_reveal_for_role(role)


def box_for_group(group: dict[str, Any], slot: dict[str, int] | None) -> dict[str, int]:
    role = str(group.get("role", "content_body"))
    group_id = str(group.get("id", ""))
    if role == "title" or group_id == "title_group":
        return {"x": 80, "y": 45, "w": 1640, "h": 70}
    if role == "subtitle" or group_id == "subtitle_group":
        return {"x": 90, "y": 175, "w": 1600, "h": 50}
    if role == "summary" or group_id == "summary_group":
        return {"x": 420, "y": 760, "w": 1080, "h": 110}
    if slot:
        return slot
    return {"x": 160, "y": 300, "w": 720, "h": 260}


def group_beat(group_id: str, beats: list[dict[str, Any]]) -> dict[str, Any] | None:
    for beat in beats:
        if isinstance(beat, dict) and str(beat.get("group_id", "")) == group_id:
            return beat
    return None


def copy_semantic_fields(group: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for field in SEMANTIC_FIELDS:
        if field in group:
            copied[field] = group[field]
    return copied


def build_slide(slide: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise TemplateError("Slide missing slide_id")
    groups = slide.get("visual_groups")
    beats = slide.get("narration_beats")
    if not isinstance(groups, list) or not groups:
        raise TemplateError(f"Slide missing visual_groups[]: {slide_id}")
    if not isinstance(beats, list):
        beats = []
    content_groups = [
        group for group in groups
        if isinstance(group, dict) and str(group.get("role", "")) not in {"title", "subtitle", "decoration"}
        and str(group.get("id", "")) not in {"title_group", "subtitle_group", "summary_group"}
    ]
    slots = content_slots(len(content_groups))
    slot_by_id = {str(group.get("id")): slots[index] for index, group in enumerate(content_groups) if index < len(slots)}
    manifest_groups: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id", "")).strip()
        role = str(group.get("role", "content_body"))
        if not group_id:
            continue
        beat = group_beat(group_id, beats)
        manifest_group = {
            "id": group_id,
            "role": role,
            "box": box_for_group(group, slot_by_id.get(group_id)),
            "visible_text": str(group.get("visible_text", "")),
            "visual_anchor": str(group.get("visual_anchor", "")),
            "narration_beat_id": str(beat.get("id", "")) if beat else None,
            "padding_px": 32 if role not in {"diagram", "summary"} else 48,
            "z_index": 20 + index,
            "reveal": default_reveal(role),
            "review_status": "needs_manual_adjustment_after_image_gen",
        }
        manifest_group.update(copy_semantic_fields(group))
        if beat and beat.get("content_unit_id"):
            manifest_group["narration_content_unit_id"] = str(beat.get("content_unit_id", ""))
        manifest_groups.append(manifest_group)
    return {
        "slide_id": slide_id,
        "slide_dir": str((run_dir / "slides" / slide_id).as_posix()),
        "master": "visual_draft.png",
        "default_duration_sec": 12,
        "groups": manifest_groups,
    }


def build_manifest(contract: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    if contract.get("version") != "visual_contract_v1":
        raise TemplateError("Contract version must be visual_contract_v1")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        raise TemplateError("Contract must contain non-empty slides[]")
    return {
        "version": "reveal_v1",
        "canvas": CANVAS,
        "slides": [build_slide(slide, run_dir) for slide in slides if isinstance(slide, dict)],
        "template_note": "Auto-generated coordinate draft. Semantic fields are copied from visual_contract.json; adjust boxes after reviewing visual_draft.png.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate reveal_manifest.json template from visual_contract.json.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--contract", type=Path, help="Defaults to <run-dir>/planning/visual_contract.json")
    parser.add_argument("--out", type=Path, help="Defaults to <run-dir>/reveal_manifest.json")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = args.contract or args.run_dir / "planning" / "visual_contract.json"
    out_path = args.out or args.run_dir / "reveal_manifest.json"
    if out_path.exists() and not args.overwrite:
        print(f"Error: output exists, use --overwrite: {out_path}", file=sys.stderr)
        return 2
    try:
        manifest = build_manifest(read_json(contract_path.resolve()), args.run_dir.resolve())
        write_json(out_path.resolve(), manifest)
    except TemplateError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
