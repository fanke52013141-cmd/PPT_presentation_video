import io
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_provider_service as provider  # noqa: E402


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "PNG")
    return buffer.getvalue()


def test_empty_and_oversize_payloads_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as value:
        output = Path(value) / "image.png"
        with pytest.raises(ValueError, match="为空"):
            provider.process_and_save_image(b"", str(output))
        with patch(
            "ai_provider_service.MAX_IMAGE_UPLOAD_BYTES",
            4,
        ):
            with pytest.raises(ValueError, match="超过"):
                provider.process_and_save_image(
                    b"12345",
                    str(output),
                )


def test_pixel_limit_is_enforced_before_resize() -> None:
    with tempfile.TemporaryDirectory() as value:
        output = Path(value) / "image.png"
        with patch("ai_provider_service.MAX_IMAGE_PIXELS", 99):
            with pytest.raises(ValueError, match="像素总量"):
                provider.process_and_save_image(
                    _png(10, 10),
                    str(output),
                )
        assert not output.exists()


def test_valid_image_is_normalized_to_canvas() -> None:
    with tempfile.TemporaryDirectory() as value:
        output = Path(value) / "image.png"
        provider.process_and_save_image(_png(16, 9), str(output))
        with Image.open(output) as image:
            assert image.size == (1920, 1080)
            assert image.mode == "RGB"


def test_valid_image_can_be_normalized_to_portrait_canvas() -> None:
    with tempfile.TemporaryDirectory() as value:
        output = Path(value) / "portrait.png"
        provider.process_and_save_image(
            _png(16, 9),
            str(output),
            target_width=1080,
            target_height=1920,
        )
        with Image.open(output) as image:
            assert image.size == (1080, 1920)
            assert image.mode == "RGB"


if __name__ == "__main__":
    test_empty_and_oversize_payloads_are_rejected()
    test_pixel_limit_is_enforced_before_resize()
    test_valid_image_is_normalized_to_canvas()
    test_valid_image_can_be_normalized_to_portrait_canvas()
    print("image upload limit checks passed")
