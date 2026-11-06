"""Run the real photo + driving-video + narration pipeline in external runtimes."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from digital_human_lipsync import LipSyncRuntime
from digital_human_motion import PortraitRuntime
from digital_human_portrait_service import PortraitPipelineDependencies, run_portrait_pipeline
from scripts.media_tools import resolve_media_tool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--driving", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--liveportrait", type=Path, required=True)
    parser.add_argument("--liveportrait-revision", required=True)
    parser.add_argument("--musetalk", type=Path, required=True)
    parser.add_argument("--musetalk-revision", required=True)
    args = parser.parse_args()
    ffmpeg = resolve_media_tool("ffmpeg", Path(__file__).resolve().parents[1])
    if not ffmpeg:
        raise ValueError("FFmpeg is required")
    output = run_portrait_pipeline(args.photo, args.driving, args.audio, args.output,
        PortraitPipelineDependencies(
            PortraitRuntime(args.liveportrait, args.liveportrait / ".venv/Scripts/python.exe",
                            args.liveportrait_revision),
            LipSyncRuntime(args.musetalk, args.musetalk / ".venv/Scripts/python.exe",
                           args.musetalk_revision, Path(ffmpeg)), args.cache))
    print(f"Validated lip-sync result: {output}", flush=True)


if __name__ == "__main__":
    main()
