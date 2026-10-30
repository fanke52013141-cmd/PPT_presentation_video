from PIL import Image, ImageDraw, ImageChops
import numpy as np
import pytest

from ai_mask_contracts import mask_source_raw_path
from image_layout_service import fit_generated_body_to_safe_area


@pytest.mark.parametrize("size,area", [
    ((1920, 1080), dict(left=80, top=235, right=1840, bottom=930)),
    ((1080, 1920), dict(left=64, top=180, right=1016, bottom=1650)),
])
def test_overflow_preserves_bottom_object_title_and_raw_alignment(tmp_path, size, area):
    source = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((200, 60, 700, 140), fill="black")
    draw.rectangle((200, area["top"] - 30, size[0] - 100, size[1] - 80), fill="blue")
    draw.rectangle((300, size[1] - 70, 450, size[1] - 10), fill="red")
    path = tmp_path / "image.png"
    source.save(path)
    source.save(mask_source_raw_path(path))
    assert fit_generated_body_to_safe_area(path, area)
    result = Image.open(path).convert("RGB")
    assert result.crop((0, area["bottom"], size[0], size[1])).getextrema() == ((255, 255),) * 3
    colors = result.getcolors(size[0] * size[1])
    assert any(color == (255, 0, 0) for _, color in colors)
    assert any(color == (0, 0, 0) for _, color in colors)
    pixels = np.asarray(result)
    blue_rows = np.unique(np.where((pixels[:, :, 2] > 200) & (pixels[:, :, 0] < 60) & (pixels[:, :, 1] < 60))[0])
    assert np.all(np.diff(blue_rows) == 1), "A card crossing the nominal body top must remain continuous"
    assert ImageChops.difference(result, Image.open(mask_source_raw_path(path))).getbbox() is None
    unchanged = path.read_bytes(), path.stat().st_mtime_ns
    assert not fit_generated_body_to_safe_area(path, area)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == unchanged
