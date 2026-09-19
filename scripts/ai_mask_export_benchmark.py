"""Read-only export of automatic RLE masks into benchmark PNGs; no app imports."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def export(manifest_path, slide_id, mapping_path, output):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8-sig"))
    slides = [s for s in manifest["slides"] if s.get("slide_id") == slide_id]
    if len(slides) != 1:
        raise ValueError("Slide ID must identify exactly one slide")
    if output.exists():
        raise ValueError("Choose a new output directory; existing predictions are never overwritten")
    results = {}
    groups = slides[0].get("groups", [])
    for target, source in mapping.items():
        if not (target.startswith("group_") and len(target) == 9 and target[6:].isdigit()):
            raise ValueError("Target IDs must be group_001, group_002, ...")
        matched = [g for g in groups if source in (g.get("id"), g.get("group_id"), g.get("visual_group_id"))]
        if len(matched) != 1:
            raise ValueError(f"Expected one manifest group for {source}, got {len(matched)}")
        manual = matched[0].get("manual_mask", {})
        if manual.get("strokes"):
            raise ValueError("Manual strokes need production rasterization; this exporter scores automatic RLE only")
        rle = manual.get("rle", {})
        if rle.get("encoding") != "row_runs_v1" or (rle.get("width"), rle.get("height")) != (1920, 1080):
            raise ValueError(f"Unsupported/missing RLE for {source}")
        mask = np.zeros((1080, 1920), np.uint8)
        for run in rle.get("runs", []):
            if len(run) != 3 or any(type(v) is not int for v in run):
                raise ValueError("RLE requires three integers")
            y, x1, x2 = run
            if not (0 <= y < 1080 and 0 <= x1 < x2 <= 1920):
                raise ValueError("Out of bounds RLE")
            mask[y, x1:x2] = 255
        results[target] = mask
    output.mkdir(parents=True)
    for target, mask in results.items():
        Image.fromarray(mask).save(output / (target + ".png"))
    print(f"Exported {len(results)} masks into {output}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--slide", required=True)
    p.add_argument("--mapping", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    export(args.manifest, args.slide, args.mapping, args.output)
