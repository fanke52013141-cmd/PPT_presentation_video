from pathlib import Path
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.background_color import (
    detect_border_background,
    detect_project_background,
    normalize_connected_background,
    rgb_to_hex,
)


with tempfile.TemporaryDirectory() as temp_dir_value:
    root = Path(temp_dir_value)
    paths = []
    for index, background in enumerate(((254, 253, 249), (253, 252, 249), (254, 253, 248))):
        image = Image.new("RGB", (240, 135), background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((35, 35, 205, 105), radius=12, fill=(231, 245, 210), outline=(8, 8, 8), width=3)
        path = root / f"slide_{index}.png"
        image.save(path)
        paths.append(path)

    canonical, details = detect_project_background(paths)
    assert rgb_to_hex(canonical) == "#FEFDF9"
    assert len(details) == 3
    assert detect_border_background(Image.open(paths[0])) == (254, 253, 249)

    source = Image.open(paths[1]).convert("RGB")
    normalized, changed_count = normalize_connected_background(source, canonical)
    assert changed_count > 0
    assert normalized.getpixel((0, 0)) == canonical
    assert normalized.getpixel((120, 70)) == source.getpixel((120, 70))

print("background color checks passed")
