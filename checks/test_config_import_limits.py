import base64
import io
from pathlib import Path
from unittest.mock import patch
import sys

from fastapi.testclient import TestClient
from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import config_portability_service as config_service  # noqa: E402


def png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, "PNG")
    return output.getvalue()


def test_config_request_body_limit_is_enforced_before_import() -> None:
    with patch("settings_routes._max_config_import_bytes", 64):
        response = TestClient(server.app).post(
            "/api/config/import",
            content=b'{"padding":"' + (b"x" * 100) + b'"}',
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413


def test_invalid_config_json_is_rejected() -> None:
    response = TestClient(server.app).post(
        "/api/config/import",
        content=b'{"settings":',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "配置文件不是有效 JSON"


def test_imported_reference_requires_valid_bounded_image() -> None:
    with pytest.raises(ValueError, match="Base64"):
        config_service.decode_config_reference_bytes(
            {"exists": True, "data": "not base64!"}
        )

    image_data = png_bytes(10, 10)
    encoded = base64.b64encode(image_data).decode("ascii")
    with patch(
        "ai_provider_service.MAX_IMAGE_UPLOAD_BYTES",
        len(image_data) - 1,
    ):
        with pytest.raises(ValueError, match="超过"):
            config_service.decode_config_reference_bytes(
                {"exists": True, "data": encoded}
            )
    with patch("ai_provider_service.MAX_IMAGE_PIXELS", 99):
        with pytest.raises(ValueError, match="像素总量"):
            config_service.decode_config_reference_bytes(
                {"exists": True, "data": encoded}
            )


def test_reference_upload_reads_only_limit_plus_one() -> None:
    global_style_source = (
        ROOT / "global_image_style_service.py"
    ).read_text(encoding="utf-8")
    image_workflow_source = (
        ROOT / "image_workflow_service.py"
    ).read_text(encoding="utf-8")
    for source in (global_style_source, image_workflow_source):
        assert "file.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)" in source
    assert (
        'image = open_validated_image(content).convert("RGB")'
        in global_style_source
    )


if __name__ == "__main__":
    test_config_request_body_limit_is_enforced_before_import()
    test_imported_reference_requires_valid_bounded_image()
    test_reference_upload_reads_only_limit_plus_one()
    print("config import limit checks passed")
