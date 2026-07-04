#!/usr/bin/env python3
"""Locate local FFmpeg tools and read media durations consistently."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def media_tool_candidate_dirs(repo_root: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    for value in (os.environ.get("PPT_STUDIO_FFMPEG_DIR"), os.environ.get("FFMPEG_DIR")):
        if value:
            candidates.append(Path(value))

    if repo_root:
        root = Path(repo_root).resolve()
        candidates.extend(
            [
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
    )
    if result.returncode != 0:
        return None
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None
