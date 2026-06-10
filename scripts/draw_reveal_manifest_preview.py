#!/usr/bin/env python3
"""Draw reveal_manifest.json boxes on top of visual_draft.png for review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


class PreviewError(RuntimeError):
    pass


PALETTE = [
    (239, 68, 68),
    (245, 158, 11),
    (34, 197, 94),
    (59, 130, 246),
    (168, 85, 247),
    (236, 72, 153),
    (20, 184, 166),
    (132, 204, 22),
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PreviewError(f"Missing JSON file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise PreviewError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreviewError(f"JSON file must contain an object: {path}")
    return value


def resolve_path(value: str, manifest_dir: Path, slide_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    for candidate in (slide_dir / path, manifest_dir / path, repo_root / path):
        if candidate.exists():
            return candidate
    return slide_dir / path


def font(size: int) -> ImageFont.ImageFont:
    for candidate in [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, color: tuple[int, int, int]) -> None:
    label_font = font(26)
    x, y = xy
    bbox = draw.textbbox((x, y), text, font=label_font)
    pad = 6
    draw.rectangle((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad), fill=(255, 253, 247), outline=color, width=2)
    draw.text((x, y), text, fill=color, font=label_font)


def preview_slide(slide: dict[str, Any], manifest_dir: Path, repo_root: Path, out_root: Path | None) -> Path:
    slide_id = str(slide.get("slide_id", "")).strip()
    if not slide_id:
        raise PreviewError("Slide missing slide_id")
    slide_dir = resolve_path(str(slide.get("slide_dir", "")), manifest_dir, manifest_dir, repo_root)
    master_path = resolve_path(str(slide.get("master", "visual_draft.png")), manifest_dir, slide_dir, repo_root)
    if not master_path.exists():
        raise PreviewError(f"Missing visual draft for {slide_id}: {master_path}")
    image = Image.open(master_path).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    groups = slide.get("groups")
    if not isinstance(groups, list):
        raise PreviewError(f"Slide missing groups[]: {slide_id}")
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict) or not isinstance(group.get("box"), dict):
            continue
        box = group["box"]
        x = int(round(float(box.get("x", 0))))
        y = int(round(float(box.get("y", 0))))
        w = int(round(float(box.get("w", 1))))
        h = int(round(float(box.get("h", 1))))
        color = PALETTE[(index - 1) % len(PALETTE)]
        fill = (*color, 34)
        outline = (*color, 255)
        draw.rectangle((x, y, x + w, y + h), fill=fill, outline=outline, width=5)
        group_id = str(group.get("id", f"group_{index}"))
        action = str((group.get("reveal") or {}).get("type", "")) if isinstance(group.get("reveal"), dict) else ""
        label = f"{index}. {group_id} | {action}"
        draw_label(draw, (x + 8, max(0, y - 36)), label, color)
    composed = Image.alpha_composite(image, overlay).convert("RGB")
    out_dir = out_root or slide_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slide_id}_reveal_manifest_preview.png"
    composed.save(out_path, format="PNG")
    return out_path


def build_previews(manifest: dict[str, Any], manifest_path: Path, repo_root: Path, out_dir: Path | None) -> list[Path]:
    slides = manifest.get("slides")
    if not isinstance(slides, list) or not slides:
        raise PreviewError("Manifest must contain non-empty slides[]")
    outputs: list[Path] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        outputs.append(preview_slide(slide, manifest_path.parent, repo_root, out_dir))
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render reveal manifest box preview images.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--repo-root", default=Path("."), type=Path)
    parser.add_argument("--out-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        outputs = build_previews(read_json(args.manifest.resolve()), args.manifest.resolve(), args.repo_root.resolve(), args.out_dir.resolve() if args.out_dir else None)
    except PreviewError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for output in outputs:
        print(output)
    print(f"Wrote {len(outputs)} preview image(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
