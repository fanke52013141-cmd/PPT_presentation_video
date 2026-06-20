#!/usr/bin/env python3
"""Bind reveal animation events to TTS audio_timeline segments.

This script rewrites each slide's animation_timeline.json so reveal events start
when their mapped narration beat or linked audio segment starts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class BindError(RuntimeError):
    pass


DEFAULT_SYNC_REVEAL_DURATION_SEC = 0.75
MIN_REVEAL_DURATION_SEC = 0.05


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BindError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise BindError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BindError(f"JSON file must contain an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_beat_map(slide_dir: Path) -> dict[str, dict[str, Any]]:
    path = slide_dir / "narration_beats.json"
    if not path.exists():
        return {}
    data = read_json(path)
    beats = data.get("beats")
    if not isinstance(beats, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for beat in beats:
        if isinstance(beat, dict) and str(beat.get("id", "")).strip():
            result[str(beat["id"])] = beat
    return result


def segment_starts(audio_timeline: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    segments = audio_timeline.get("segments")
    if not isinstance(segments, list) or not segments:
        raise BindError("audio_timeline.json must contain non-empty segments[]")
    by_id: dict[str, float] = {}
    clean_segments: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id", "")).strip()
        start = segment.get("start")
        if segment_id and isinstance(start, (int, float)):
            by_id[segment_id] = float(start)
            clean_segments.append(segment)
    return by_id, clean_segments


def infer_segment_for_beat(beat_index: int, segments: list[dict[str, Any]]) -> str | None:
    if not segments:
        return None
    index = min(max(beat_index, 0), len(segments) - 1)
    segment_id = str(segments[index].get("id", "")).strip()
    return segment_id or None


def event_beat_ids(event: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    raw_ids = event.get("narration_beat_ids")
    if isinstance(raw_ids, list):
        ids.extend(str(value).strip() for value in raw_ids if str(value).strip())
    single = str(event.get("narration_beat_id", "")).strip()
    if single:
        ids.append(single)
    result: list[str] = []
    for beat_id in ids:
        if beat_id not in result:
            result.append(beat_id)
    return result


def linked_segment_for_event(
    event: dict[str, Any],
    event_index: int,
    beat_map: dict[str, dict[str, Any]],
    beat_order: list[str],
    segments: list[dict[str, Any]],
) -> str:
    linked_segment_id = str(event.get("linked_segment_id", "")).strip()
    if linked_segment_id:
        return linked_segment_id
    for beat_id in event_beat_ids(event):
        beat = beat_map.get(beat_id, {})
        linked_segment_id = str(beat.get("linked_segment_id", "")).strip()
        if linked_segment_id:
            return linked_segment_id
        if any(str(segment.get("id", "")).strip() == beat_id for segment in segments):
            return beat_id
        if beat_id in beat_order:
            inferred = infer_segment_for_beat(beat_order.index(beat_id), segments)
            if inferred:
                return inferred
    return infer_segment_for_beat(event_index, segments) or ""


def bind_slide(slide_dir: Path, lead_sec: float, preserve_existing_at: bool) -> bool:
    animation_path = slide_dir / "animation_timeline.json"
    audio_path = slide_dir / "audio_timeline.json"
    timeline = read_json(animation_path)
    audio_timeline = read_json(audio_path)
    segment_by_id, segments = segment_starts(audio_timeline)
    beat_map = load_beat_map(slide_dir)
    events = timeline.get("events")
    if not isinstance(events, list):
        raise BindError(f"animation_timeline.json must contain events[]: {animation_path}")

    beat_order = list(beat_map.keys())
    initial_audio_delay = float(audio_timeline.get("audio_start_sec", 0.0) or 0.0)
    changed = False
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise BindError(f"Invalid event object: {animation_path}")
        if preserve_existing_at and isinstance(event.get("at"), (int, float)) and event.get("linked_segment_id"):
            continue
        linked_segment_id = linked_segment_for_event(event, index, beat_map, beat_order, segments)
        if linked_segment_id and linked_segment_id not in segment_by_id:
            event.pop("linked_segment_id", None)
            linked_segment_id = linked_segment_for_event(event, index, beat_map, beat_order, segments)
        if linked_segment_id in segment_by_id:
            event["linked_segment_id"] = linked_segment_id
            duration = float(event.get("duration", DEFAULT_SYNC_REVEAL_DURATION_SEC))
            duration = max(MIN_REVEAL_DURATION_SEC, duration)
            event["duration"] = round(duration, 3)
            audio_delay = float(audio_timeline.get("audio_start_sec", 0.0) or 0.0)
            desired_at = audio_delay + segment_by_id[linked_segment_id] + max(0.0, lead_sec)
            if desired_at < 0:
                audio_delay = max(audio_delay, 0.0 - segment_by_id[linked_segment_id])
                audio_timeline["audio_start_sec"] = round(audio_delay, 3)
                desired_at = 0.0
            event["at"] = round(max(0.0, desired_at), 3)
            event["narration_start_at"] = round(segment_by_id[linked_segment_id] + audio_delay, 3)
            changed = True
    final_audio_delay = float(audio_timeline.get("audio_start_sec", 0.0) or 0.0)
    for event in events:
        if not isinstance(event, dict):
            continue
        linked_segment_id = str(event.get("linked_segment_id", "")).strip()
        if linked_segment_id in segment_by_id:
            event["narration_start_at"] = round(segment_by_id[linked_segment_id] + final_audio_delay, 3)
    duration = audio_timeline.get("duration_sec")
    if isinstance(duration, (int, float)):
        base_duration = audio_timeline.get("audio_content_duration_sec")
        if isinstance(base_duration, (int, float)):
            audio_content_duration = float(base_duration)
        else:
            audio_content_duration = max(0.0, float(duration) - initial_audio_delay)
        audio_timeline["audio_content_duration_sec"] = round(audio_content_duration, 3)
        event_end = max((float(event.get("at", 0)) + float(event.get("duration", 0)) for event in events if isinstance(event, dict)), default=0.0)
        audio_timeline["duration_sec"] = round(audio_content_duration + final_audio_delay, 3)
        timeline["duration_sec"] = round(max(audio_content_duration + final_audio_delay, event_end + 0.25), 3)
    if changed:
        write_json(animation_path, timeline)
        write_json(audio_path, audio_timeline)
    return changed


def slide_dirs(run_dir: Path, slide_id: str | None) -> list[Path]:
    root = run_dir / "slides"
    if slide_id:
        return [root / slide_id]
    if not root.exists():
        raise BindError(f"Missing slides directory: {root}")
    contract_ids = contract_slide_ids(run_dir)
    if contract_ids:
        return [root / current_slide_id for current_slide_id in contract_ids]
    slides = sorted(path for path in root.iterdir() if path.is_dir())
    if not slides:
        raise BindError(f"No slide directories found: {root}")
    return slides


def contract_slide_ids(run_dir: Path) -> list[str]:
    contract_path = run_dir / "planning" / "visual_contract.json"
    if not contract_path.exists():
        return []
    try:
        contract = read_json(contract_path)
    except BindError:
        return []
    slides = contract.get("slides")
    if not isinstance(slides, list):
        return []
    slide_ids: list[str] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id", "")).strip()
        if slide_id:
            slide_ids.append(slide_id)
    return slide_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bind reveal animation timing to audio timeline segments.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--slide-id")
    parser.add_argument("--lead-sec", type=float, default=0.0, help="Optional delay after the audio segment starts before revealing.")
    parser.add_argument("--preserve-existing-at", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        changed_count = 0
        dirs = slide_dirs(args.run_dir.resolve(), args.slide_id)
        for slide_dir in dirs:
            if bind_slide(slide_dir, lead_sec=args.lead_sec, preserve_existing_at=args.preserve_existing_at):
                changed_count += 1
    except BindError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Bound reveal timelines for {changed_count} of {len(dirs)} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
