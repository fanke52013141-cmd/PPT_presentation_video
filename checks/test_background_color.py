import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.background_color import (
    connected_background_mask,
    masked_outer_white_cutout,
    normalize_connected_background,
)


source = Image.new("RGB", (240, 135), (255, 255, 255))
draw = ImageDraw.Draw(source)
draw.rounded_rectangle(
    (35, 35, 205, 105),
    radius=12,
    fill=(231, 245, 210),
    outline=(8, 8, 8),
    width=3,
)
draw.rectangle((80, 50, 160, 90), fill=(255, 255, 255), outline=(0, 0, 0), width=2)

background = (254, 253, 249)
normalized, changed_count = normalize_connected_background(source, background)
assert changed_count > 0
assert normalized.getpixel((0, 0)) == background
assert normalized.getpixel((120, 70)) == source.getpixel((120, 70))

background_mask = connected_background_mask(source)
assert background_mask.getpixel((0, 0)) == 255
assert background_mask.getpixel((120, 70)) == 0

# A colored edge is content, not removable background.
colored_corner = Image.new("RGB", (40, 30), (220, 235, 250))
assert connected_background_mask(colored_corner).getpixel((0, 0)) == 0

# The manual Mask is a processing boundary. White connected to that boundary
# is removed, while white enclosed by content remains visible.
cutout_source = Image.new("RGB", (80, 60), (255, 255, 255))
cutout_draw = ImageDraw.Draw(cutout_source)
cutout_draw.rectangle((20, 14, 60, 46), fill=(255, 255, 255), outline=(0, 0, 0), width=4)
cutout_source.putpixel((19, 30), (220, 220, 220))
manual_alpha = Image.new("L", cutout_source.size, 0)
ImageDraw.Draw(manual_alpha).rectangle((8, 6, 72, 54), fill=255)
cutout, output_alpha, stats = masked_outer_white_cutout(cutout_source, manual_alpha)
assert output_alpha.getpixel((8, 6)) == 0
assert output_alpha.getpixel((20, 30)) == 255
assert output_alpha.getpixel((40, 30)) == 255
assert output_alpha.getpixel((19, 30)) == 35
assert cutout.getpixel((19, 30))[:3] == (0, 0, 0)
assert stats["removed_outer_white_pixel_count"] > 0
assert stats["soft_edge_pixel_count"] > 0

print("background color checks passed")
