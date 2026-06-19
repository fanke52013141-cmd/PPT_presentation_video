#!/usr/bin/env python3
"""Compatibility entrypoint for the current exact manual-Mask scene builder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from build_reveal_scene import RevealBuildError, build_manifest, read_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deprecated alias for build_reveal_scene.py using manual_mask_exact_v2."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    manifest_path = run_dir / "reveal_manifest.json"
    try:
        count = build_manifest(
            read_json(manifest_path),
            manifest_path,
            args.repo_root.resolve(),
        )
    except RevealBuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(
        "prepare_full_slide_scenes.py is deprecated; "
        f"built manual_mask_exact_v2 assets for {count} slide(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
