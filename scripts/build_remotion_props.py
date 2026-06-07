#!/usr/bin/env python3
"""
Build remotion_props.json from a run directory.

This script is the glue between the production pipeline and Remotion.

Input run structure:

runs/<run_id>/
  slides/
    slide_001/
      scene.json
      animation_timeline.json
      audio_timeline.json
      voice.mp3
    slide_002/
      ...

Output:

runs/<run_id>/remotion_props.json

The generated props are consumed by:

scripts/remotion/src/Video.tsx
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname


DEFAULT_FPS = 30
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_REMOTION_PUBLIC_DIR = Path("scripts/remotion/public")


class BuildError(RuntimeError):
    pass


class RuntimeAssetStore:
    def __init__(self, public_dir: Path, run_id: str) -> None:
        self.public_dir = public_dir.resolve()
        self.run_id = run_id

    def copy(
        self,
        value: str,
        slide_dir: Path,
        repo_root: Path,
        subdir: str,
        required_suffix: str | None = None,
    ) -> str:
        if is_url(value):
            return value

        local_asset = resolve_local_path(value, slide_dir, repo_root)
        if not local_asset.exists():
            raise BuildError(f"Missing local file: {local_asset}")

        if required_suffix and local_asset.suffix.lower() != required_suffix:
            raise BuildError(f"Asset must be a {required_suffix} file: {local_asset}")

        destination = (
            self.public_dir
            / "runtime"
            / self.run_id
            / slide_dir.name
            / subdir
            / local_asset.name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_asset, destination)

        return destination.relative_to(self.public_dir).as_posix()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BuildError(f"Missing required file: {path}")

    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise BuildError(f"Invalid JSON file: {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise BuildError(f"JSON file must contain an object: {path}")

    return value


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def is_file_uri(value: str) -> bool:
    return value.startswith("file://")


def path_from_file_uri(value: str) -> Path:
    parsed = urlparse(value)
    path = url2pathname(unquote(parsed.path))

    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"

    return Path(path)


def slide_sort_key(path: Path) -> tuple[int, str]:
    """
    Sort slide_001, slide_002, slide_010 in natural order.
    """
    match = re.search(r"(\d+)$", path.name)
    if match:
        return int(match.group(1)), path.name

    return 999999, path.name


def resolve_local_path(value: str, slide_dir: Path, repo_root: Path) -> Path:
    """
    Resolve an asset path.

    Supported forms:
    - assets/title.png
    - runs/demo/slides/slide_001/assets/title.png
    - C:/.../title.png
    - file:///C:/.../title.png
    """
    if is_file_uri(value):
        return path_from_file_uri(value)

    raw = Path(value)

    if raw.is_absolute():
        return raw

    candidates = [
        slide_dir / raw,
        repo_root / raw,
        Path.cwd() / raw,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Return the most likely path for a clear error message.
    return slide_dir / raw


def validate_layer(layer: dict[str, Any], slide_dir: Path) -> None:
    if layer.get("type") != "png":
        raise BuildError(
            f"Only PNG layers are supported in Remotion scene model. "
            f"Bad layer in {slide_dir}: {layer.get('id')}"
        )

    if not layer.get("id"):
        raise BuildError(f"Layer missing id in {slide_dir}")

    if not layer.get("asset"):
        raise BuildError(f"Layer missing asset in {slide_dir}: {layer.get('id')}")

    box = layer.get("box")
    if not isinstance(box, dict):
        raise BuildError(f"Layer missing box in {slide_dir}: {layer.get('id')}")

    for key in ["x", "y", "w", "h"]:
        if key not in box:
            raise BuildError(f"Layer box missing {key} in {slide_dir}: {layer.get('id')}")

    if "z_index" not in layer:
        raise BuildError(f"Layer missing z_index in {slide_dir}: {layer.get('id')}")


def convert_scene_assets(
    scene: dict[str, Any],
    slide_dir: Path,
    repo_root: Path,
    asset_store: RuntimeAssetStore,
) -> dict[str, Any]:
    """
    Copy scene assets into Remotion public/runtime and convert to staticFile paths.
    """
    if "elements" in scene:
        raise BuildError(
            f"scene.json contains deprecated elements[] in {slide_dir}. "
            "Use layers[] with PNG assets only."
        )

    layers = scene.get("layers")

    if not isinstance(layers, list) or not layers:
        raise BuildError(f"scene.json must contain non-empty layers[]: {slide_dir}")

    converted_layers: list[dict[str, Any]] = []

    for layer in layers:
        if not isinstance(layer, dict):
            raise BuildError(f"Invalid layer object in {slide_dir}")

        validate_layer(layer, slide_dir)

        converted = dict(layer)
        converted["asset"] = asset_store.copy(
            str(layer["asset"]),
            slide_dir,
            repo_root,
            subdir="assets",
            required_suffix=".png",
        )
        converted_layers.append(converted)

    converted_scene = dict(scene)
    converted_scene["layers"] = converted_layers

    canvas = converted_scene.get("canvas")
    if not isinstance(canvas, dict):
        raise BuildError(f"scene.json missing canvas object: {slide_dir}")

    background_asset = canvas.get("background_asset")
    if isinstance(background_asset, str) and background_asset:
        converted_canvas = dict(canvas)
        converted_canvas["background_asset"] = asset_store.copy(
            background_asset,
            slide_dir,
            repo_root,
            subdir="assets",
        )
        converted_scene["canvas"] = converted_canvas

    return converted_scene


def require_slide_id(slide_dir: Path, *values: Any) -> str:
    slide_ids = [str(value) for value in values if isinstance(value, str) and value]

    if not slide_ids:
        return slide_dir.name

    first = slide_ids[0]
    mismatches = sorted({value for value in slide_ids if value != first})
    if mismatches:
        raise BuildError(f"slide_id mismatch in {slide_dir}: {[first, *mismatches]}")

    return first


def validate_audio_timeline(audio_timeline: dict[str, Any], slide_dir: Path) -> None:
    segments = audio_timeline.get("segments")
    if not isinstance(segments, list):
        raise BuildError(f"audio_timeline.json must contain segments[]: {slide_dir}")

    for segment in segments:
        if not isinstance(segment, dict):
            raise BuildError(f"Invalid audio segment in {slide_dir}")

        for key in ["id", "start", "end", "text"]:
            if key not in segment:
                raise BuildError(f"Audio segment missing {key} in {slide_dir}")

        if not isinstance(segment["start"], (int, float)) or not isinstance(segment["end"], (int, float)):
            raise BuildError(f"Audio segment start/end must be numbers in {slide_dir}: {segment.get('id')}")

        if segment["end"] < segment["start"]:
            raise BuildError(f"Audio segment end before start in {slide_dir}: {segment.get('id')}")


def validate_animation_timeline(
    animation_timeline: dict[str, Any],
    layer_ids: set[str],
    slide_dir: Path,
) -> None:
    events = animation_timeline.get("events")
    if not isinstance(events, list):
        raise BuildError(f"animation_timeline.json must contain events[]: {slide_dir}")

    for event in events:
        if not isinstance(event, dict):
            raise BuildError(f"Invalid animation event in {slide_dir}")

        for key in ["target", "action", "at", "duration"]:
            if key not in event:
                raise BuildError(f"Animation event missing {key} in {slide_dir}")

        target = str(event["target"])
        if target not in layer_ids:
            raise BuildError(f"Animation event targets unknown layer in {slide_dir}: {target}")

        if not isinstance(event["at"], (int, float)) or not isinstance(event["duration"], (int, float)):
            raise BuildError(f"Animation event at/duration must be numbers in {slide_dir}: {event.get('id')}")


def max_segment_end(audio_timeline: dict[str, Any]) -> float:
    values: list[float] = []

    for segment in audio_timeline.get("segments", []):
        if isinstance(segment, dict) and isinstance(segment.get("end"), (int, float)):
            values.append(float(segment["end"]))

    return max(values, default=0.0)


def max_event_end(animation_timeline: dict[str, Any]) -> float:
    values: list[float] = []

    for event in animation_timeline.get("events", []):
        if (
            isinstance(event, dict)
            and isinstance(event.get("at"), (int, float))
            and isinstance(event.get("duration"), (int, float))
        ):
            values.append(float(event["at"]) + float(event["duration"]))

    return max(values, default=0.0)


def optional_duration(value: Any) -> float:
    if isinstance(value, (int, float)) and value > 0:
        return float(value)

    return 0.0


def slide_duration(audio_timeline: dict[str, Any], animation_timeline: dict[str, Any], slide_dir: Path) -> float:
    duration = max(
        optional_duration(audio_timeline.get("duration_sec")),
        optional_duration(animation_timeline.get("duration_sec")),
        max_segment_end(audio_timeline),
        max_event_end(animation_timeline),
    )

    if duration <= 0:
        raise BuildError(f"Could not determine positive duration_sec for {slide_dir}")

    return round(duration, 3)


def build_slide(
    slide_dir: Path,
    repo_root: Path,
    asset_store: RuntimeAssetStore,
    start_sec: float,
) -> dict[str, Any]:
    scene = convert_scene_assets(read_json(slide_dir / "scene.json"), slide_dir, repo_root, asset_store)
    audio_timeline = read_json(slide_dir / "audio_timeline.json")
    animation_timeline = read_json(slide_dir / "animation_timeline.json")

    validate_audio_timeline(audio_timeline, slide_dir)
    layer_ids = {str(layer["id"]) for layer in scene["layers"]}
    validate_animation_timeline(animation_timeline, layer_ids, slide_dir)

    voice_path = slide_dir / "voice.mp3"
    audio_file = asset_store.copy(str(voice_path), slide_dir, repo_root, subdir="audio", required_suffix=".mp3")
    converted_audio_timeline = dict(audio_timeline)
    converted_audio_timeline["audio_file"] = audio_file
    slide_id = require_slide_id(
        slide_dir,
        scene.get("slide_id"),
        audio_timeline.get("slide_id"),
        animation_timeline.get("slide_id"),
    )
    duration_sec = slide_duration(audio_timeline, animation_timeline, slide_dir)

    return {
        "slide_id": slide_id,
        "start_sec": round(start_sec, 3),
        "duration_sec": duration_sec,
        "scene": scene,
        "audio_file": audio_file,
        "audio_timeline": converted_audio_timeline,
        "animation_timeline": animation_timeline,
    }


def build_props(
    run_dir: Path,
    repo_root: Path,
    asset_store: RuntimeAssetStore,
    fps: int,
    width: int,
    height: int,
    slide_ids: set[str] | None = None,
) -> dict[str, Any]:
    slides_dir = run_dir / "slides"
    if not slides_dir.exists():
        raise BuildError(f"Missing slides directory: {slides_dir}")

    slide_dirs = sorted(
        [path for path in slides_dir.iterdir() if path.is_dir()],
        key=slide_sort_key,
    )
    if slide_ids:
        slide_dirs = [path for path in slide_dirs if path.name in slide_ids]
    if not slide_dirs:
        raise BuildError(f"No matching slide directories found in: {slides_dir}")

    slides: list[dict[str, Any]] = []
    start_sec = 0.0

    for slide_dir in slide_dirs:
        slide = build_slide(slide_dir, repo_root, asset_store, start_sec)
        slides.append(slide)
        start_sec += float(slide["duration_sec"])

    return {
        "fps": fps,
        "width": width,
        "height": height,
        "total_duration_sec": round(start_sec, 3),
        "slides": slides,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Remotion props JSON from runs/<run_id>/slides/* inputs."
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Run directory, for example runs/demo")
    parser.add_argument(
        "--out",
        type=Path,
        help="Output props JSON path. Defaults to <run-dir>/remotion_props.json",
    )
    parser.add_argument("--repo-root", default=Path("."), type=Path, help="Repository root for resolving assets")
    parser.add_argument(
        "--remotion-public-dir",
        default=DEFAULT_REMOTION_PUBLIC_DIR,
        type=Path,
        help="Remotion public directory. Assets are copied to public/runtime/<run_id>/...",
    )
    parser.add_argument(
        "--slide-id",
        dest="slide_ids",
        action="append",
        help="Only include one slide id. Can be repeated for multiple slides.",
    )
    parser.add_argument("--fps", default=DEFAULT_FPS, type=int)
    parser.add_argument("--width", default=DEFAULT_WIDTH, type=int)
    parser.add_argument("--height", default=DEFAULT_HEIGHT, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    repo_root = args.repo_root.resolve()
    public_dir = args.remotion_public_dir
    if not public_dir.is_absolute():
        public_dir = repo_root / public_dir
    out_path = (args.out or run_dir / "remotion_props.json").resolve()
    asset_store = RuntimeAssetStore(public_dir=public_dir, run_id=run_dir.name)

    try:
        props = build_props(
            run_dir=run_dir,
            repo_root=repo_root,
            asset_store=asset_store,
            fps=args.fps,
            width=args.width,
            height=args.height,
            slide_ids=set(args.slide_ids) if args.slide_ids else None,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(props, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except BuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
