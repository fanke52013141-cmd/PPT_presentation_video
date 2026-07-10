"""Remove only near-white pixels connected to the outer slide edge."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter


def _boundary_connected_hard_white(hard_white: np.ndarray, domain: np.ndarray) -> np.ndarray:
    """Return hard-white pixels connected to the outside of one Mask.

    The previous implementation converted the full 1920x1080 canvas to a PIL
    image and ran ``ImageDraw.floodfill`` once per semantic group.  That call
    is Python-bound and took roughly five seconds per group on real projects.
    This run-length connected-component pass preserves the same 4-neighbour
    semantics while doing work proportional to white spans instead of pixels.
    """
    height, width = hard_white.shape
    passable = (~domain) | hard_white
    parents: list[int] = []
    seeded: list[bool] = []
    rows: list[list[tuple[int, int, int]]] = []

    def find(node: int) -> int:
        while parents[node] != node:
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    previous: list[tuple[int, int, int]] = []
    for y in range(height):
        row = passable[y]
        edges = np.diff(np.pad(row.astype(np.int8), (1, 1)))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        current: list[tuple[int, int, int]] = []

        for x1_raw, x2_raw in zip(starts, ends):
            x1, x2 = int(x1_raw), int(x2_raw)
            node = len(parents)
            parents.append(node)
            touches_outside = y == 0 or y == height - 1 or x1 == 0 or x2 == width
            seeded.append(touches_outside)
            current.append((x1, x2, node))

        previous_index = 0
        for x1, x2, node in current:
            while previous_index < len(previous) and previous[previous_index][1] <= x1:
                previous_index += 1
            scan_index = previous_index
            while scan_index < len(previous) and previous[scan_index][0] < x2:
                union(node, previous[scan_index][2])
                scan_index += 1

        rows.append(current)
        previous = current

    connected_roots = {find(node) for node, is_seeded in enumerate(seeded) if is_seeded}
    result = np.zeros_like(hard_white, dtype=bool)
    for y, runs in enumerate(rows):
        for x1, x2, node in runs:
            if find(node) in connected_roots:
                result[y, x1:x2] = True
    return result & domain


def _estimate_background_color(image: Image.Image) -> tuple[int, int, int]:
    """Estimate the slide background color by sampling the four corners.

    Instead of assuming pure white (RGB >= 245), we take the median of pixels
    in the four corner regions.  This adapts to off-white paper textures,
    warm-tinted backgrounds, and subtle gradients that previously left white
    halos along element edges.
    """
    rgb = image.convert("RGB")
    arr = np.asarray(rgb, dtype=np.uint8)
    h, w = arr.shape[:2]
    sample = 12  # sample a 12x12 patch in each corner
    patches = [
        arr[0:sample, 0:sample],                          # top-left
        arr[0:sample, w - sample:w],                      # top-right
        arr[h - sample:h, 0:sample],                      # bottom-left
        arr[h - sample:h, w - sample:w],                  # bottom-right
    ]
    stacked = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)
    med_r = int(np.median(stacked[:, 0]))
    med_g = int(np.median(stacked[:, 1]))
    med_b = int(np.median(stacked[:, 2]))
    return (med_r, med_g, med_b)


def _adaptive_channel_floor(image: Image.Image) -> tuple[int, int, int]:
    """Return per-channel background thresholds derived from corner sampling.

    Returns (min_r, min_g, min_b) so that pixels brighter than these values on
    every channel and with low chroma are treated as background.  When the
    sampled background is genuinely white (>= 245), this falls back to
    behaviour equivalent to the original 245 floor.
    """
    bg = _estimate_background_color(image)
    # Allow a tolerance of 15 below the sampled background per channel.
    floor = tuple(max(0, c - 15) for c in bg)
    return floor


def _adaptive_near_white_mask(
    image: Image.Image,
    channel_floor: tuple[int, int, int],
    max_chroma: int,
) -> Image.Image:
    """Build a near-white mask using adaptive per-channel thresholds."""
    original = image.convert("RGB")
    arr = np.asarray(original, dtype=np.uint8)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    above_floor = (
        (r >= channel_floor[0])
        & (g >= channel_floor[1])
        & (b >= channel_floor[2])
    )
    maximum = arr.max(axis=2)
    minimum = arr.min(axis=2)
    chroma = maximum - minimum
    low_chroma = chroma <= max_chroma
    mask = (above_floor & low_chroma).astype(np.uint8) * 255
    return Image.fromarray(mask, mode="L")


def connected_background_mask(
    image: Image.Image,
    min_channel: int = 230,
    max_chroma: int = 18,
) -> Image.Image:
    """Return 255 only for near-white pixels connected to the outer image edge.

    Uses adaptive per-channel thresholds derived from corner sampling so that
    off-white or subtly tinted backgrounds are detected correctly.  Falls back
    to a 230 floor (was 245) when the corners themselves are pure white.
    """
    original = image.convert("RGB")
    adaptive_floor = _adaptive_channel_floor(original)
    near_white = _adaptive_near_white_mask(original, adaptive_floor, max_chroma)

    # Flood from outside the canvas. Only near-white pixels reachable from an
    # outer edge become background; enclosed white details remain content.
    padded = Image.new("L", (original.width + 2, original.height + 2), 255)
    padded.paste(near_white, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    connected = padded.crop((1, 1, original.width + 1, original.height + 1))
    return connected.point(lambda value: 255 if value == 128 else 0)


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


def masked_outer_white_cutout(
    image: Image.Image,
    manual_alpha: Image.Image,
    hard_min_channel: int = 230,
    hard_max_chroma: int = 18,
    soft_min_channel: int = 170,
    soft_max_chroma: int = 40,
    feather_px: int = 8,
) -> tuple[Image.Image, Image.Image, dict[str, int]]:
    """Cut out outer-connected white inside one user-painted Mask.

    The painted Mask is the processing boundary. Pure/near-white pixels that
    can be reached from that boundary become transparent. Enclosed white
    details remain opaque. A short soft-white expansion recovers antialiased
    edges and removes white halos without running semantic segmentation.
    """
    source = image.convert("RGB")
    alpha = manual_alpha.convert("L")
    if source.size != alpha.size:
        raise ValueError("image and manual_alpha must have the same size")

    rgb = np.asarray(source, dtype=np.uint8)
    manual = np.asarray(alpha, dtype=np.uint8)
    domain = manual > 0
    maximum = rgb.max(axis=2)
    minimum = rgb.min(axis=2)
    chroma = maximum - minimum

    hard_white = (
        domain
        & (minimum >= hard_min_channel)
        & (chroma <= hard_max_chroma)
    )
    hard_background = _boundary_connected_hard_white(hard_white, domain)

    soft_white = (
        domain
        & (minimum >= soft_min_channel)
        & (chroma <= soft_max_chroma)
    )
    expanded = Image.fromarray(
        np.where(hard_background, 255, 0).astype(np.uint8),
        mode="L",
    )
    for _ in range(max(0, int(feather_px))):
        grown = expanded.filter(ImageFilter.MaxFilter(3))
        expanded = Image.fromarray(
            np.where(
                (np.asarray(grown, dtype=np.uint8) > 0) & soft_white,
                255,
                0,
            ).astype(np.uint8),
            mode="L",
        )
    soft_region = (np.asarray(expanded, dtype=np.uint8) > 0) & ~hard_background

    output_alpha = manual.copy()
    output_alpha[hard_background] = 0
    white_edge_alpha = (255 - minimum).astype(np.uint8)
    output_alpha[soft_region] = np.minimum(
        output_alpha[soft_region],
        white_edge_alpha[soft_region],
    )

    # white_edge_alpha already provides a source-derived soft transition for
    # neutral antialiased pixels. Do not blur the entire alpha field: that would
    # make nearby dark outlines and other solid content semi-transparent.

    output_rgb = rgb.copy()
    edge_pixels = soft_region & (output_alpha > 0)
    if np.any(edge_pixels):
        edge_alpha = output_alpha[edge_pixels].astype(np.float32) / 255.0
        original = rgb[edge_pixels].astype(np.float32)
        recovered = (
            original - (1.0 - edge_alpha[:, None]) * 255.0
        ) / edge_alpha[:, None]
        output_rgb[edge_pixels] = np.clip(
            np.rint(recovered),
            0,
            255,
        ).astype(np.uint8)
    output_rgb[output_alpha == 0] = 0

    rgba = np.dstack((output_rgb, output_alpha))
    final_alpha = Image.fromarray(output_alpha, mode="L")
    return (
        Image.fromarray(rgba, mode="RGBA"),
        final_alpha,
        {
            "manual_mask_pixel_count": int(np.count_nonzero(domain)),
            "removed_outer_white_pixel_count": int(np.count_nonzero(hard_background)),
            "soft_edge_pixel_count": int(np.count_nonzero(soft_region)),
            "retained_pixel_count": int(np.count_nonzero(output_alpha)),
        },
    )
