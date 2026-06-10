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
    changed = False
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise BindError(f"Invalid event object: {animation_path}")
        if preserve_existing_at and isinstance(event.get("at"), (int, float)) and event.get("linked_segment_id"):
            continue
        linked_segment_id = str(event.get("linked_segment_id", "")).strip()
        beat_id = str(event.get("narration_beat_id", "")).strip()
        if not linked_segment_id and beat_id:
            beat = beat_map.get(beat_id, {})
            linked_segment_id = str(beat.get("linked_segment_id", "")).strip()
        if not linked_segment_id and beat_id in beat_order:
            linked_segment_id = infer_segment_for_beat(beat_order.index(beat_id), segments) or ""
        if not linked_segment_id:
            linked_segment_id = infer_segment_for_beat(index, segments) or ""
        if linked_segment_id in segment_by_id:
            event["linked_segment_id"] = linked_segment_id
            event["at"] = round(max(0.0, segment_by_id[linked_segment_id] - lead_sec), 3)
            changed = True
    duration = audio_timeline.get("duration_sec")
    if isinstance(duration, (int, float)):
        event_end = max((float(event.get("at", 0)) + float(event.get("duration", 0)) for event in events if isinstance(event, dict)), default=0.0)
        timeline["duration_sec"] = round(max(float(duration), event_end + 0.25), 3)
    if changed:
        write_json(animation_path, timeline)
    return changed


def slide_dirs(run_dir: Path, slide_id: str | None) -> list[Path]:
    root = run_dir / "slides"
    if slide_id:
        return [root / slide_id]
    if not root.exists():
        raise BindError(f"Missing slides directory: {root}")
    slides = sorted(path for path in root.iterdir() if path.is_dir())
    if not slides:
        raise BindError(f"No slide directories found: {root}")
    return slides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bind reveal animation timing to audio timeline segments.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--slide-id")
    parser.add_argument("--lead-sec", type=float, default=0.05, help="Start reveal slightly before the audio segment.")
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
