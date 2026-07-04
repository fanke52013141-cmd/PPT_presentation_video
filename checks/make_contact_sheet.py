#!/usr/bin/env python3
"""Create a labeled contact sheet from ordered frame images for video QA."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--columns", type=int, default=3)
    parser.add_argument("--crop-y", type=int)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    columns = max(1, args.columns)
    thumb_width = 640
    thumb_height = 180 if args.crop_y is not None else 360
    label_height = 34
    rows = (len(args.images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_width, rows * (thumb_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=20)
    for index, path in enumerate(args.images):
        image = Image.open(path).convert("RGB")
        if args.crop_y is not None:
            image = image.crop((0, max(0, args.crop_y), image.width, image.height))
        image.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        x = (index % columns) * thumb_width
        y = (index // columns) * (thumb_height + label_height)
        sheet.paste(image, (x + (thumb_width - image.width) // 2, y))
        draw.text((x + 10, y + thumb_height + 6), path.stem.replace("t_", "t=").replace("_", ".") + "s", fill="black", font=font)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
