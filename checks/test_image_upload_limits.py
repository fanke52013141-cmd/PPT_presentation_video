import io
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


def test_empty_and_oversize_payloads_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as value:
        output = Path(value) / "image.png"
        with pytest.raises(ValueError, match="为空"):
            server.process_and_save_image(b"", str(output))
        with patch("server.MAX_IMAGE_UPLOAD_BYTES", 4):
            with pytest.raises(ValueError, match="超过"):
                server.process_and_save_image(b"12345", str(output))


def test_pixel_limit_is_enforced_before_resize() -> None:
    with tempfile.TemporaryDirectory() as value:
        output = Path(value) / "image.png"
        with patch("server.MAX_IMAGE_PIXELS", 99):
            with pytest.raises(ValueError, match="像素总量"):
                server.process_and_save_image(_png(10, 10), str(output))
        assert not output.exists()


def test_valid_image_is_normalized_to_canvas() -> None:
    with tempfile.TemporaryDirectory() as value:
        output = Path(value) / "image.png"
        server.process_and_save_image(_png(16, 9), str(output))
        with Image.open(output) as image:
            assert image.size == (1920, 1080)
            assert image.mode == "RGB"


if __name__ == "__main__":
    test_empty_and_oversize_payloads_are_rejected()
    test_pixel_limit_is_enforced_before_resize()
    test_valid_image_is_normalized_to_canvas()
    print("image upload limit checks passed")
