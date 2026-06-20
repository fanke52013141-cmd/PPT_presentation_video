import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.background_color import (
    connected_background_mask,
    connected_content_alpha,
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
content_alpha = connected_content_alpha(source)
assert background_mask.getpixel((0, 0)) == 255
assert content_alpha.getpixel((0, 0)) == 0
assert content_alpha.getpixel((120, 70)) == 255

# A colored edge is content, not removable background.
colored_corner = Image.new("RGB", (40, 30), (220, 235, 250))
assert connected_background_mask(colored_corner).getpixel((0, 0)) == 0
assert connected_content_alpha(colored_corner).getpixel((0, 0)) == 255

print("background color checks passed")
