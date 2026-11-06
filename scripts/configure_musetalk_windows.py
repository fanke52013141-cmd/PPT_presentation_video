"""Apply explicit, offline dependency configuration for the RTMCC-only worker.

MMPose 1.2 includes CSPNeXt natively. MuseTalk's legacy config points at the
equivalent MMDetection backbone, unnecessarily importing compiled detector ops.
Its unused EDPose head also imports those ops at package startup. This setup
step is explicit and reproducible, never an application startup monkey patch.
Only the dedicated external model environment is supported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def configure(root: Path) -> None:
    root = root.resolve()
    pose_root = root / ".venv/Lib/site-packages/mmpose"
    version = pose_root / "version.py"
    if not version.is_file() or "1.2.0" not in version.read_text(encoding="utf-8"):
        raise ValueError("This configuration requires a dedicated MMPose 1.2.0 environment")
    heads = pose_root / "models/heads/__init__.py"
    config = root / "musetalk/utils/dwpose/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py"
    changes = {}
    for path, substitutions in [
        (heads, [("from .transformer_heads import EDPoseHead\n", ""),
                 (", 'EDPoseHead'", "")]),
        (config, [("_scope_='mmdet'", "_scope_='mmpose'")]),
    ]:
        original = path.read_text(encoding="utf-8")
        current = original
        for before, after in substitutions:
            current = current.replace(before, after)
        if current != original:
            backup = path.with_suffix(path.suffix + ".ppt-original")
            if not backup.exists():
                backup.write_text(original, encoding="utf-8")
            path.write_text(current, encoding="utf-8")
        changes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "ppt_windows_configuration.json").write_text(
        json.dumps({"recipe": "rtmcc-native-cspnext-v1", "files": changes}, indent=2), encoding="utf-8")
    print("Configured dedicated MuseTalk RTMCC environment.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--musetalk", type=Path, required=True)
    configure(parser.parse_args().musetalk)
