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


def connected_background_mask(
    image: Image.Image,
    min_channel: int = 245,
    max_chroma: int = 12,
) -> Image.Image:
    """Return 255 only for near-white pixels connected to the outer image edge."""
    original = image.convert("RGB")
    red, green, blue = original.split()
    channel_floor = ImageChops.multiply(
        ImageChops.multiply(
            red.point(lambda value: 255 if value >= min_channel else 0),
            green.point(lambda value: 255 if value >= min_channel else 0),
        ),
        blue.point(lambda value: 255 if value >= min_channel else 0),
    )
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    low_chroma = ImageChops.subtract(maximum, minimum).point(
        lambda value: 255 if value <= max_chroma else 0
    )
    near_white = ImageChops.multiply(channel_floor, low_chroma)

    # The padded frame represents the area outside the image. Flooding from it
    # reaches every near-white region connected to any edge, while enclosed
    # white areas remain content.
    padded = Image.new("L", (original.width + 2, original.height + 2), 255)
    padded.paste(near_white, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    connected = padded.crop((1, 1, original.width + 1, original.height + 1))
    return connected.point(lambda value: 255 if value == 128 else 0)


def connected_content_alpha(image: Image.Image) -> Image.Image:
    return ImageChops.invert(connected_background_mask(image))


def normalize_connected_background(
    image: Image.Image,
    background_rgb: tuple[int, int, int],
) -> tuple[Image.Image, int]:
    """Replace only outer-connected near-white; interior white fills are untouched."""
    original = image.convert("RGB")
    changed = connected_background_mask(original)
    normalized = Image.composite(
        Image.new("RGB", original.size, background_rgb),
        original,
        changed,
    )
    changed_pixel_count = changed.histogram()[255]
    return normalized, int(changed_pixel_count)
