"""Deterministic background-aware defaults for newly generated AI annotations."""

from dataclasses import replace
from pathlib import Path
from statistics import median
import math


def contrast_ratio(first, second):
    def luminance(rgb):
        channels = [v / 255 for v in rgb]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


def readable_ai_style(image_path: str | Path, polygons, default):
    """Preserve defaults on neutral paper; use a contrasting underline on similar/dark fills.

    Called only when creating AI suggestions. Existing manual styles are never rewritten.
    """
    from PIL import Image

    if not polygons:
        return default
    backgrounds = []
    try:
        from PIL import ImageDraw

        with Image.open(image_path) as image:
            image = image.convert("RGB")
            for polygon in polygons:
                if len(polygon) < 3:
                    continue
                left = max(0, math.floor(min(p[0] for p in polygon)))
                top = max(0, math.floor(min(p[1] for p in polygon)))
                right = min(image.width, math.ceil(max(p[0] for p in polygon)))
                bottom = min(image.height, math.ceil(max(p[1] for p in polygon)))
                if right <= left or bottom <= top:
                    continue
                # Sample each actual target, excluding gaps between lines/cards and
                # pixels outside tilted quadrilaterals. Bound work per token.
                crop = image.crop((left, top, right, bottom)).resize((24, 12))
                mask = Image.new("L", (24, 12))
                ImageDraw.Draw(mask).polygon([
                    ((p[0] - left) * 24 / (right - left), (p[1] - top) * 12 / (bottom - top))
                    for p in polygon], fill=255)
                pixels = [pixel for pixel, selected in zip(crop.getdata(), mask.getdata()) if selected]
                if pixels:
                    backgrounds.append(tuple(median(pixel[c] for pixel in pixels) for c in range(3)))
    except (OSError, ValueError):
        return default
    if not backgrounds:
        return default
    marker = tuple(int(default.color[i:i + 2], 16) for i in (1, 3, 5))
    similar = any(sum(abs(a - b) for a, b in zip(background, marker)) / 3 < 65 for background in backgrounds)
    dark = any(max(background) < 115 for background in backgrounds)
    if not similar and not dark:
        return default
    palette = ("#1456B8", "#B42318", "#FDE047", "#FFFFFF", "#111827", "#767676")
    color = max(palette, key=lambda value: min(contrast_ratio(background, tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))) for background in backgrounds))
    return replace(default, type="underline", color=color, opacity=.95, width=3, padding=2)
