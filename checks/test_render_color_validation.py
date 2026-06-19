import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.validate_render_color import (
    RenderColorError,
    frame_mean_absolute_error,
    validate_metadata,
)


validate_metadata(
    {
        "pix_fmt": "yuv420p",
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }
)

try:
    validate_metadata(
        {
            "pix_fmt": "yuvj420p",
            "color_range": "pc",
            "color_space": "bt470bg",
        }
    )
except RenderColorError:
    pass
else:
    raise AssertionError("non-standard color metadata was accepted")

with tempfile.TemporaryDirectory() as temp_dir_value:
    root = Path(temp_dir_value)
    expected = root / "expected.png"
    actual = root / "actual.png"
    Image.new("RGB", (64, 36), (254, 253, 249)).save(expected)
    Image.new("RGB", (64, 36), (252, 251, 247)).save(actual)
    assert frame_mean_absolute_error(expected, actual, 36) == [2.0, 2.0, 2.0]

print("render color validation checks passed")
