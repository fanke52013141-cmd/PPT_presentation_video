"""Remove only near-white pixels connected to the outer slide edge."""

from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw


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

    # Flood from outside the canvas. Only near-white pixels reachable from an
    # outer edge become background; enclosed white details remain content.
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
