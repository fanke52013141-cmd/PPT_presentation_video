"""Detect and normalize the nearly-solid slide background without touching content."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw


DEFAULT_BACKGROUND_RGB = (255, 253, 247)


def rgb_to_hex(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in color)


def detect_border_background(image: Image.Image, border: int = 32, stride: int = 4) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    border = max(1, min(border, width // 4, height // 4))
    samples: list[tuple[int, int, int]] = []
    for y in range(0, border, stride):
        for x in range(0, width, stride):
            samples.append(rgb.getpixel((x, y)))
            samples.append(rgb.getpixel((x, height - 1 - y)))
    for x in range(0, border, stride):
        for y in range(border, height - border, stride):
            samples.append(rgb.getpixel((x, y)))
            samples.append(rgb.getpixel((width - 1 - x, y)))
    if not samples:
        return DEFAULT_BACKGROUND_RGB
    return tuple(
        int(round(statistics.median(sample[channel] for sample in samples)))
        for channel in range(3)
    )


def detect_project_background(paths: Iterable[Path]) -> tuple[tuple[int, int, int], list[dict[str, object]]]:
    detected: list[dict[str, object]] = []
    colors: list[tuple[int, int, int]] = []
    for path in paths:
        if not path.exists():
            continue
        with Image.open(path) as image:
            color = detect_border_background(image)
        colors.append(color)
        detected.append({"path": str(path), "color": rgb_to_hex(color)})
    if not colors:
        return DEFAULT_BACKGROUND_RGB, detected
    canonical = tuple(
        int(round(statistics.median(color[channel] for color in colors)))
        for channel in range(3)
    )
    return canonical, detected


def normalize_connected_background(
    image: Image.Image,
    background_rgb: tuple[int, int, int],
    threshold: int = 8,
) -> tuple[Image.Image, int]:
    """Replace only background connected to a corner; interior card fills are untouched."""
    original = image.convert("RGB")
    marked = original.copy()
    width, height = marked.size
    marker_rgb = tuple(255 - channel for channel in background_rgb)
    for seed in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        if marked.getpixel(seed) != marker_rgb:
            ImageDraw.floodfill(marked, seed, marker_rgb, thresh=threshold)
    red, green, blue = ImageChops.difference(original, marked).split()
    changed = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
        lambda value: 255 if value else 0
    )
    normalized = Image.composite(
        Image.new("RGB", original.size, background_rgb),
        original,
        changed,
    )
    changed_pixel_count = changed.histogram()[255]
    return normalized, int(changed_pixel_count)
