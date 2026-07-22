#!/usr/bin/env python3
"""Write narration files from visual_contract.json.

The narration is deliberately grounded in visual groups: every spoken beat maps to
one group_id and content_unit_id, then expands that unit's visible text, source
text, visual anchor, and narration function. The narration_beats list is the sole
source of truth for deciding which visual groups are spoken.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


class NarrationBuildError(RuntimeError):
    pass


PAUSE_RE = re.compile(r"\s+")
DEDUPE_RE = re.compile(r"[\W_]+", re.UNICODE)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise NarrationBuildError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise NarrationBuildError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NarrationBuildError(f"JSON file must contain an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(text: str) -> str:
    return PAUSE_RE.sub(" ", text).strip()


def narration_key(text: str) -> str:
    value = re.sub(r"<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\)", "", normalize(text).casefold())
    return DEDUPE_RE.sub("", value)


def group_lookup(slide: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = slide.get("visual_groups")
    if not isinstance(groups, list):
        # Allow missing/null visual_groups (manual mode). An empty dict here
        # means beats are free-standing and must not require a group_id.
        return {}
    result: dict[str, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id", "")).strip()
        if group_id:
            result[group_id] = group
    return result


def spoken_text_for_beat(beat: dict[str, Any], group: dict[str, Any] | None, max_chars: int) -> str:
    existing = normalize(str(beat.get("spoken_text", "")))
    if existing:
        # Existing narration is user or upstream-authored source text. Never
        # truncate it here; max_chars only constrains generated fallback copy.
        return existing
    if group is None:
        # Manual mode: no visual group to expand. Fall back to the beat's own
        # spoken_intent, then to a minimal placeholder.
        intent = normalize(str(beat.get("spoken_intent", "")))
        if intent:
            return intent
        return ""
    visible = normalize(str(group.get("visible_text", beat.get("visible_anchor", "这个点"))))
    anchor = normalize(str(group.get("visual_anchor", beat.get("visible_anchor", visible))))
    source = normalize(str(group.get("source_text", "")))
    function = normalize(str(group.get("narration_function", beat.get("spoken_intent", ""))))
    intent = normalize(str(beat.get("spoken_intent", function)))
    parts = [f"看画面里的“{visible}”。", f"它对应的是{anchor}。"]
    if intent:
        parts.append(f"这一句要讲的是：{intent}。")
    if source and source != intent:
        parts.append(f"具体来说，{source}。")
    elif function and function != intent:
        parts.append(f"也就是说，{function}。")
    text = "".join(parts)
    return text[:max_chars]


def build_slide_narration(slide: dict[str, Any], max_beat_chars: int) -> dict[str, Any]:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise NarrationBuildError("Slide missing slide_id")
    groups = group_lookup(slide)
    manual_mode_slide = not groups  # no visual groups: free-standing beats
    raw_beats = slide.get("narration_beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise NarrationBuildError(f"Slide missing narration_beats[]: {slide_id}")
    beats: list[dict[str, Any]] = []
    seen_spoken_text: set[str] = set()
    for index, beat in enumerate(raw_beats, start=1):
        if not isinstance(beat, dict):
            raise NarrationBuildError(f"Invalid beat in {slide_id}")
        beat_id = str(beat.get("id", f"beat_{index:02d}")).strip()
        group_id = str(beat.get("group_id", "")).strip()
        group = groups.get(group_id)
        if group is None:
            if not manual_mode_slide:
                raise NarrationBuildError(f"Beat {beat_id} references unknown group_id in {slide_id}: {group_id}")
            # Manual mode: no group binding. content_unit_id stays on the beat.
            beat_content_unit_id = str(beat.get("content_unit_id", "")).strip()
            if not beat_content_unit_id:
                beat_content_unit_id = f"{slide_id}_unit_{index:03d}"
        else:
            group_content_unit_id = str(group.get("content_unit_id", group_id)).strip()
            beat_content_unit_id = str(beat.get("content_unit_id", group_content_unit_id)).strip()
            if group_content_unit_id and beat_content_unit_id and beat_content_unit_id != group_content_unit_id:
                raise NarrationBuildError(
                    f"Beat {beat_id} content_unit_id does not match group in {slide_id}: "
                    f"{beat_content_unit_id} != {group_content_unit_id}"
                )
            beat_content_unit_id = group_content_unit_id or beat_content_unit_id
        spoken_text = spoken_text_for_beat(beat, group, max_chars=max_beat_chars)
        key = narration_key(spoken_text)
        if key and key in seen_spoken_text:
            continue
        if key:
            seen_spoken_text.add(key)
        beats.append(
            {
                "id": beat_id,
                "content_unit_id": beat_content_unit_id,
                "group_id": group_id,
                "visible_anchor": normalize(
                    str(beat.get("visible_anchor", (group or {}).get("visible_text", "")))
                ),
                "spoken_intent": normalize(
                    str(beat.get("spoken_intent", (group or {}).get("narration_function", "")))
                ),
                "spoken_text": spoken_text,
            }
        )
    narration = "\n".join(beat["spoken_text"] for beat in beats)
    return {"slide_id": slide_id, "beats": beats, "narration": narration, "tts_text": narration}


def write_slide_files(run_dir: Path, slide_payload: dict[str, Any], overwrite: bool) -> None:
    slide_id = slide_payload["slide_id"]
    slide_dir = run_dir / "slides" / slide_id
    slide_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        "narration.txt": slide_payload["narration"] + "\n",
        "tts_text.txt": slide_payload["tts_text"] + "\n",
    }
    for name, content in targets.items():
        path = slide_dir / name
        if path.exists() and not overwrite:
            continue
        path.write_text(content, encoding="utf-8")
    json_path = slide_dir / "narration_beats.json"
    if not json_path.exists() or overwrite:
        write_json(json_path, {"slide_id": slide_id, "beats": slide_payload["beats"]})


def build_narration(contract: dict[str, Any], run_dir: Path, max_beat_chars: int, overwrite: bool) -> int:
    if contract.get("version") != "visual_contract_v1":
        raise NarrationBuildError("Contract version must be visual_contract_v1")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        raise NarrationBuildError("Contract must contain non-empty slides[]")
    for slide in slides:
        if not isinstance(slide, dict):
            raise NarrationBuildError("Each slide must be an object")
        payload = build_slide_narration(slide, max_beat_chars=max_beat_chars)
        write_slide_files(run_dir, payload, overwrite=overwrite)
    return len(slides)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write narration files from visual_contract.json.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--contract", type=Path, help="Defaults to <run-dir>/planning/visual_contract.json")
    parser.add_argument("--max-beat-chars", type=int, default=220)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = args.contract or args.run_dir / "planning" / "visual_contract.json"
    try:
        count = build_narration(read_json(contract_path.resolve()), args.run_dir.resolve(), max_beat_chars=args.max_beat_chars, overwrite=args.overwrite)
    except NarrationBuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote narration files for {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
