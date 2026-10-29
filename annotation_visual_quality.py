"""Deterministic background-aware defaults for newly generated AI annotations."""

from dataclasses import replace
from pathlib import Path
from statistics import median


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

    points = [point for polygon in polygons for point in polygon]
    if not points:
        return default
    try:
        with Image.open(image_path) as image:
            left = max(0, int(min(p[0] for p in points)))
            top = max(0, int(min(p[1] for p in points)))
            right = min(image.width, int(max(p[0] for p in points)))
            bottom = min(image.height, int(max(p[1] for p in points)))
            if right <= left or bottom <= top:
                return default
            pixels = list(image.convert("RGB").crop((left, top, right, bottom)).resize((24, 12)).getdata())
    except (OSError, ValueError):
        return default
    background = tuple(median(pixel[channel] for pixel in pixels) for channel in range(3))
    marker = tuple(int(default.color[i:i + 2], 16) for i in (1, 3, 5))
    similar = sum(abs(a - b) for a, b in zip(background, marker)) / 3 < 65
    dark = max(background) < 115
    if not similar and not dark:
        return default
    palette = ("#1456B8", "#B42318", "#FDE047", "#FFFFFF", "#111827")
    color = max(palette, key=lambda value: contrast_ratio(background, tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))))
    return replace(default, type="underline", color=color, opacity=.95, width=3, padding=2)
