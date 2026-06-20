#!/usr/bin/env python3
"""Validate standard video color metadata and decoded-frame fidelity."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


class RenderColorError(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def probe_video(video_path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt,color_range,color_space,color_transfer,color_primaries",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RenderColorError(f"ffprobe failed: {result.stderr}")
    streams = json.loads(result.stdout).get("streams") or []
    if not streams:
        raise RenderColorError("Rendered video has no video stream")
    return streams[0]


def validate_metadata(metadata: dict) -> None:
    expected = {
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }
    mismatches = {
        key: {"expected": expected_value, "actual": metadata.get(key)}
        for key, expected_value in expected.items()
        if metadata.get(key) != expected_value
    }
    if mismatches:
        raise RenderColorError(f"Non-standard video color metadata: {mismatches}")


def frame_mean_absolute_error(
    expected: Image.Image | Path,
    actual_path: Path,
    safe_height: int,
) -> list[float]:
    if isinstance(expected, Path):
        expected = Image.open(expected)
    expected = expected.convert("RGB")
    actual = Image.open(actual_path).convert("RGB")
    if expected.size != actual.size:
        raise RenderColorError(f"Frame size mismatch: expected {expected.size}, got {actual.size}")
    safe_height = max(1, min(safe_height, expected.height))
    difference = ImageChops.difference(
        expected.crop((0, 0, expected.width, safe_height)),
        actual.crop((0, 0, actual.width, safe_height)),
    )
    return [float(value) for value in ImageStat.Stat(difference).mean]


def verification_time(slide: dict) -> float:
    duration = float(slide.get("duration_sec", 0) or 0)
    events = ((slide.get("animation_timeline") or {}).get("events") or [])
    event_end = max(
        (
            float(event.get("at", 0) or 0) + float(event.get("duration", 0) or 0)
            for event in events
            if isinstance(event, dict)
        ),
        default=0.5,
    )
    local_time = min(max(0.5, event_end + 0.3), max(0.5, duration - 0.5))
    return float(slide.get("start_sec", 0) or 0) + local_time


def expected_slide_image(run_dir: Path, slide_id: str) -> Image.Image:
    slide_dir = run_dir / "slides" / slide_id
    scene = read_json(slide_dir / "scene.json")
    canvas = scene.get("canvas") or {}
    width = int(canvas.get("width", 1920))
    height = int(canvas.get("height", 1080))
    background = str(canvas.get("background", "#FEFDF9")).lstrip("#")
    if len(background) != 6:
        raise RenderColorError(f"Invalid scene background for {slide_id}: {background}")
    background_rgb = tuple(int(background[index:index + 2], 16) for index in (0, 2, 4))
    expected = Image.new("RGBA", (width, height), (*background_rgb, 255))
    layers = sorted(
        (layer for layer in scene.get("layers") or [] if isinstance(layer, dict)),
        key=lambda layer: int(layer.get("z_index", 0)),
    )
    for layer in layers:
        asset = slide_dir / str(layer.get("asset", ""))
        if not asset.exists():
            raise RenderColorError(f"Missing scene asset for {slide_id}: {asset}")
        box = layer.get("box") or {}
        x = int(round(float(box.get("x", 0))))
        y = int(round(float(box.get("y", 0))))
        width = int(round(float(box.get("w", 0))))
        height = int(round(float(box.get("h", 0))))
        image = Image.open(asset).convert("RGBA")
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        expected.alpha_composite(image, (x, y))
    return expected.convert("RGB")


def validate_video(video_path: Path, run_dir: Path, max_channel_mae: float = 4.0) -> dict:
    metadata = probe_video(video_path)
    validate_metadata(metadata)
    props = read_json(run_dir / "remotion_props.json")
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as temp_dir_value:
        temp_dir = Path(temp_dir_value)
        for slide in props.get("slides") or []:
            slide_id = str(slide.get("slide_id") or "")
            if not slide_id:
                continue
            frame_path = temp_dir / f"{slide_id}.png"
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{verification_time(slide):.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    str(frame_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode != 0 or not frame_path.exists():
                raise RenderColorError(f"Could not decode validation frame for {slide_id}: {result.stderr}")
            safe_height = int(((slide.get("scene") or {}).get("canvas") or {}).get("subtitle_safe_y", 930) or 930)
            mae = frame_mean_absolute_error(expected_slide_image(run_dir, slide_id), frame_path, safe_height)
            if max(mae) > max_channel_mae:
                raise RenderColorError(
                    f"{slide_id} decoded color drift is too large: "
                    f"MAE={[round(value, 3) for value in mae]}, limit={max_channel_mae}"
                )
            results.append({"slide_id": slide_id, "mean_absolute_error": [round(value, 3) for value in mae]})
    return {"metadata": metadata, "slides": results}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate rendered MP4 color fidelity.")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--max-channel-mae", default=4.0, type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        print("Error: ffmpeg and ffprobe are required", file=sys.stderr)
        return 1
    try:
        result = validate_video(args.video.resolve(), args.run_dir.resolve(), args.max_channel_mae)
    except RenderColorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
