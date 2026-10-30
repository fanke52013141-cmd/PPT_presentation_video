#!/usr/bin/env python3
"""Locate local FFmpeg tools and read media durations consistently."""

from __future__ import annotations

import os
import json
import math
import shutil
import subprocess
from pathlib import Path


def media_tool_candidate_dirs(repo_root: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    for value in (os.environ.get("PPT_STUDIO_FFMPEG_DIR"), os.environ.get("PPT_DIGITAL_HUMAN_FFMPEG_DIR"), os.environ.get("FFMPEG_DIR")):
        if value:
            candidates.append(Path(value))

    if repo_root:
        root = Path(repo_root).resolve()
        candidates.extend(
            [
                root / "scripts" / "remotion" / "node_modules" / "@remotion" / "compositor-win32-x64-msvc",
                root.parent / "work" / "runtime" / "ffmpeg" / "bin",
                root.parent / "work" / "runtime" / "ffmpeg",
                root / "tools" / "ffmpeg" / "bin",
                root / "runtime" / "ffmpeg" / "bin",
                root.parent / "runtime" / "ffmpeg" / "bin",
                root.parent / "runtime" / "ffmpeg",
            ]
        )

    appdata = os.environ.get("APPDATA")
    if appdata:
        roaming = Path(appdata)
        candidates.extend(
            [
                roaming / "TRAE SOLO CN" / "ModularData" / "ai-agent" / "vm" / "tools" / "app" / "ffmpeg",
                roaming / "WEMedia" / "plugin" / "ffmpeg_7_1",
            ]
        )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def resolve_media_tool(name: str, repo_root: Path | None = None) -> str | None:
    direct = os.environ.get(f"{name.upper()}_BINARY")
    if direct and Path(direct).is_file():
        return str(Path(direct))

    found = shutil.which(name)
    if found:
        return found

    executable = f"{name}.exe" if os.name == "nt" else name
    for directory in media_tool_candidate_dirs(repo_root):
        candidate = directory / executable
        if candidate.is_file():
            return str(candidate)
    return None


def probe_media_duration_sec(
    media_path: str | Path,
    *,
    ffprobe_binary: str | None = None,
    repo_root: Path | None = None,
) -> float | None:
    path = Path(media_path)
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    ffprobe = ffprobe_binary or resolve_media_tool("ffprobe", repo_root=repo_root)
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def probe_video_metadata(media_path: str | Path, *, repo_root: Path | None = None) -> dict | None:
    """Require a decodable, finite-duration video stream with positive dimensions."""
    ffprobe = resolve_media_tool("ffprobe", repo_root=repo_root)
    if not ffprobe:
        return None
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration", "-of", "json", str(media_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        if result.returncode:
            return None
        value = json.loads(result.stdout)
        stream = value["streams"][0]
        duration = float(value["format"]["duration"])
        width, height = int(stream["width"]), int(stream["height"])
        if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
            return None
        return {"width": width, "height": height, "duration_sec": duration}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError):
        return None
