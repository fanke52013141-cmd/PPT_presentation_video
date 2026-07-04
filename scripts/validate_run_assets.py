#!/usr/bin/env python3
"""Validate article-to-video run assets before Remotion rendering."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
REVEAL_VISUAL_SOURCE = "master_reveal_layers"


class ValidationError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValidationError(f"Missing required JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON file must contain an object: {path}")
    return value


def resolve_asset(value: str, slide_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (slide_dir / path, repo_root / path):
        if candidate.exists():
            return candidate
    return slide_dir / path


def validate_png(path: Path, width: int | None = None, height: int | None = None) -> None:
    if not path.exists():
        raise ValidationError(f"Missing PNG asset: {path}")
    if path.suffix.lower() != ".png":
        raise ValidationError(f"Expected PNG asset, got: {path}")
    with Image.open(path) as image:
        actual = image.size
    if width is not None and height is not None and actual != (width, height):
        raise ValidationError(f"PNG has wrong dimensions: {path} is {actual[0]}x{actual[1]}, expected {width}x{height}")


def probe_audio_duration_sec(audio_path: Path) -> float | None:
    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        return None
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(audio_path),
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def validate_audio_timeline(path: Path) -> float:
    timeline = read_json(path)
    segments = timeline.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValidationError(f"audio_timeline.json must contain non-empty segments[]: {path}")
    max_end = 0.0
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValidationError(f"Invalid audio segment object: {path}")
        for key in ("id", "start", "end", "text"):
            if key not in segment:
                raise ValidationError(f"Audio segment missing {key}: {path}")
        if not isinstance(segment["start"], (int, float)) or not isinstance(segment["end"], (int, float)) or segment["end"] <= segment["start"]:
            raise ValidationError(f"Audio segment has invalid timing: {path}: {segment.get('id')}")
        max_end = max(max_end, float(segment["end"]))
    total_duration = timeline.get("duration_sec")
    if not isinstance(total_duration, (int, float)) or total_duration <= 0:
        raise ValidationError(f"audio_timeline.json missing positive duration_sec: {path}")
    audio_start = float(timeline.get("audio_start_sec", 0.0) or 0.0)
    content_duration = timeline.get("audio_content_duration_sec")
    if not isinstance(content_duration, (int, float)):
        content_duration = max(0.0, float(total_duration) - audio_start)
    if abs(float(content_duration) - max_end) > 0.2:
        raise ValidationError(
            f"audio_timeline audio_content_duration_sec does not match segment ends: {path}"
        )
    if abs(float(total_duration) - (float(content_duration) + audio_start)) > 0.2:
        raise ValidationError(
            f"audio_timeline duration_sec does not include audio_start_sec correctly: {path}"
        )
    return float(total_duration)


def validate_voice_duration_matches_timeline(voice_path: Path, timeline_duration_sec: float) -> None:
    actual_duration = probe_audio_duration_sec(voice_path)
    if actual_duration is None:
        return
    if actual_duration > timeline_duration_sec + 0.35:
        raise ValidationError(
            "voice.mp3 is longer than audio_timeline.json and would be cut off: "
            f"{voice_path} actual={actual_duration:.3f}s timeline={timeline_duration_sec:.3f}s"
        )


def validate_scene(scene_path: Path, slide_dir: Path, repo_root: Path, width: int, height: int, require_layered: bool) -> set[str]:
    scene = read_json(scene_path)
    if "elements" in scene:
        raise ValidationError(f"scene.json contains deprecated elements[]: {scene_path}")
    source = scene.get("visual_source")
    layers = scene.get("layers")
    reveal_report = read_json(slide_dir / "reveal_report.json") if source == REVEAL_VISUAL_SOURCE else {}
    fallback_full_slide = bool(reveal_report.get("fallback_full_slide"))
    if not isinstance(layers, list) or not layers:
        raise ValidationError(f"scene.json must contain non-empty layers[]: {scene_path}")
    if require_layered:
        if source != REVEAL_VISUAL_SOURCE:
            raise ValidationError(f"Layered mode requires visual_source={REVEAL_VISUAL_SOURCE}: {scene_path}")
        if len(layers) < 2 and not fallback_full_slide:
            raise ValidationError(f"Layered mode requires multiple PNG layers: {scene_path}")
    if source == REVEAL_VISUAL_SOURCE:
        report_path = slide_dir / "reveal_report.json"
        if not report_path.exists():
            raise ValidationError(f"Missing reveal_report.json for reveal scene: {slide_dir}")
        report = reveal_report
        warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
        blocking = [w for w in warnings if isinstance(w, dict) and str(w.get("severity", "warning")) == "blocking"]
        if blocking:
            names = ", ".join(str(w.get("type", "unknown")) for w in blocking)
            raise ValidationError(f"Blocking reveal warnings must be resolved before render: {slide_dir}: {names}")
    layer_ids: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValidationError(f"Invalid scene layer object: {scene_path}")
        layer_id = str(layer.get("id", ""))
        if not layer_id:
            raise ValidationError(f"Layer missing id: {scene_path}")
        if layer_id in layer_ids:
            raise ValidationError(f"Duplicate layer id {layer_id}: {scene_path}")
        layer_ids.add(layer_id)
        if layer.get("type") != "png":
            raise ValidationError(f"Layer type must be png, not {layer.get('type')}: {scene_path}")
        asset_path = resolve_asset(str(layer.get("asset", "")), slide_dir, repo_root)
        box = layer.get("box")
        if not isinstance(box, dict):
            raise ValidationError(f"Layer missing box: {scene_path}: {layer_id}")
        for key in ("x", "y", "w", "h"):
            if not isinstance(box.get(key), (int, float)):
                raise ValidationError(f"Layer box missing numeric {key}: {scene_path}: {layer_id}")
        if box["w"] <= 0 or box["h"] <= 0:
            raise ValidationError(f"Layer box must have positive size: {scene_path}: {layer_id}")
        if box["x"] < 0 or box["y"] < 0 or box["x"] + box["w"] > width or box["y"] + box["h"] > height:
            raise ValidationError(f"Layer box is outside the canvas: {scene_path}: {layer_id}")
        validate_png(asset_path, width=int(round(float(box["w"]))), height=int(round(float(box["h"]))))
    return layer_ids


def validate_animation_timeline(path: Path, layer_ids: set[str], audio_duration_sec: float) -> None:
    timeline = read_json(path)
    events = timeline.get("events")
    if not isinstance(events, list):
        raise ValidationError(f"animation_timeline.json must contain events[]: {path}")
    duration = timeline.get("duration_sec")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValidationError(f"animation_timeline.json missing positive duration_sec: {path}")
    # A static no-Mask slide has no animation events; its rendered duration is
    # derived from audio_timeline.json by build_remotion_props.py.
    if events and float(duration) + 0.2 < audio_duration_sec:
        raise ValidationError(f"animation duration is shorter than audio duration: {path}")
    for event in events:
        if not isinstance(event, dict):
            raise ValidationError(f"Invalid animation event object: {path}")
        target = str(event.get("target", ""))
        if target not in layer_ids:
            raise ValidationError(f"Animation target does not exist in scene layers: {path}: {target}")
        if not isinstance(event.get("at"), (int, float)) or not isinstance(event.get("duration"), (int, float)):
            raise ValidationError(f"Animation event has invalid timing: {path}: {event.get('id')}")
        if float(event["at"]) + float(event["duration"]) > float(duration) + 0.2:
            raise ValidationError(f"Animation event exceeds animation duration: {path}: {event.get('id')}")


def slide_ids_from_planning(run_dir: Path) -> list[str]:
    contract_path = run_dir / "planning" / "visual_contract.json"
    plan_path = run_dir / "planning" / "slide_plan.json"
    planning = read_json(contract_path if contract_path.exists() else plan_path)
    slides = planning.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValidationError(f"Planning file must contain non-empty slides[]: {run_dir}")
    slide_ids = [str(slide.get("slide_id", "")) for slide in slides if isinstance(slide, dict)]
    if not slide_ids or len(slide_ids) != len(set(slide_ids)):
        raise ValidationError(f"Planning file has missing or duplicate slide_id values: {run_dir}")
    return slide_ids


def validate_slide(slide_dir: Path, repo_root: Path, width: int, height: int, require_layered: bool) -> None:
    validate_png(slide_dir / "visual_draft.png")
    voice_path = slide_dir / "voice.mp3"
    if not voice_path.exists() or voice_path.stat().st_size < 1024:
        raise ValidationError(f"Missing or empty voice.mp3: {voice_path}")
    # Current Remotion subtitles are driven by audio_timeline.json. Historical
    # subtitles.srt files are optional and must not block the exact-mask path.
    audio_duration_sec = validate_audio_timeline(slide_dir / "audio_timeline.json")
    validate_voice_duration_matches_timeline(voice_path, audio_duration_sec)
    layer_ids = validate_scene(slide_dir / "scene.json", slide_dir, repo_root, width, height, require_layered)
    validate_animation_timeline(slide_dir / "animation_timeline.json", layer_ids, audio_duration_sec)


def validate_run(run_dir: Path, repo_root: Path, width: int, height: int, require_layered: bool) -> int:
    slide_ids = slide_ids_from_planning(run_dir)
    for slide_id in slide_ids:
        slide_dir = run_dir / "slides" / slide_id
        if not slide_dir.exists():
            raise ValidationError(f"Missing slide directory: {slide_dir}")
        validate_slide(slide_dir, repo_root, width, height, require_layered)
    return len(slide_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a complete article-to-video run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--width", default=DEFAULT_WIDTH, type=int)
    parser.add_argument("--height", default=DEFAULT_HEIGHT, type=int)
    parser.add_argument("--require-layered", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        count = validate_run(
            run_dir=args.run_dir.resolve(),
            repo_root=args.repo_root.resolve(),
            width=args.width,
            height=args.height,
            require_layered=args.require_layered,
        )
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {count} slide(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
