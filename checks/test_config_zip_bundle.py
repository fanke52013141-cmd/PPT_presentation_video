import base64
import io
import json
from pathlib import Path
from unittest.mock import patch
import sys
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import config_portability_service as config_service  # noqa: E402
import settings_service  # noqa: E402


def png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, "PNG")
    return output.getvalue()


def sample_reference() -> dict:
    return {
        "exists": True,
        "data": base64.b64encode(png_bytes(8, 8)).decode("ascii"),
        "mime": "image/png",
        "filename": "ref-style.png",
    }


def configured_config_dependencies(**changes):
    dependencies = config_service._deps()
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values.update(changes)
    return config_service.ConfigPortabilityDependencies(**values)


def zip_asset_names(data: bytes) -> list:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return [
            name
            for name in archive.namelist()
            if name.startswith(config_service.CONFIG_ZIP_ASSETS_PREFIX)
        ]


def test_zip_export_extracts_assets_and_round_trips() -> None:
    bundle = {
        "settings": {"llm_model": "m"},
        "image_style": {
            "active_references": {"style": sample_reference()},
        },
    }
    zip_bytes = config_service.build_config_zip_bytes(bundle)
    assert zip_bytes[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        assert config_service.CONFIG_ZIP_ENTRY in names
        assert config_service.CONFIG_ZIP_README_ENTRY in names
        assets = [
            name
            for name in names
            if name.startswith(config_service.CONFIG_ZIP_ASSETS_PREFIX)
        ]
        assert len(assets) == 1
        stored = json.loads(
            archive.read(config_service.CONFIG_ZIP_ENTRY).decode("utf-8")
        )
        reference = stored["image_style"]["active_references"]["style"]
        assert reference["asset"] == assets[0]
        assert "data" not in reference
        assert archive.read(assets[0]) == png_bytes(8, 8)

    payload = config_service._read_zip_bundle_payload(zip_bytes)
    restored = payload["image_style"]["active_references"]["style"]
    assert restored == sample_reference()
    assert "asset" not in restored


def test_zip_export_sanitizes_asset_filenames() -> None:
    bundle = {
        "image_style": {
            "active_references": {
                "style": {
                    **sample_reference(),
                    "filename": "../../evil name.png",
                }
            }
        }
    }
    assets = zip_asset_names(config_service.build_config_zip_bytes(bundle))
    assert assets == ["assets/0001_evil_name.png"]
    assert all(".." not in name for name in assets)


def test_json_importer_rejects_bare_zip_config_json() -> None:
    payload = {
        "image_style": {
            "active_references": {
                "style": {
                    "asset": "assets/0001_ref.png",
                    "mime": "image/png",
                    "filename": "ref.png",
                }
            }
        }
    }
    with pytest.raises(ValueError, match="压缩包"):
        config_service.import_full_config(payload)
    response = TestClient(server.app).post("/api/config/import", json=payload)
    assert response.status_code == 400
    assert "压缩包" in response.json()["detail"]


def test_zip_import_rejects_unsafe_or_missing_asset_paths() -> None:
    traversal_buffer = io.BytesIO()
    with zipfile.ZipFile(traversal_buffer, "w") as archive:
        archive.writestr(
            config_service.CONFIG_ZIP_ENTRY,
            json.dumps(
                {
                    "image_style": {
                        "active_references": {
                            "style": {
                                "asset": "assets/../../evil.png",
                                "mime": "image/png",
                            }
                        }
                    }
                }
            ),
        )
        archive.writestr("assets/0001_ref.png", png_bytes(8, 8))
    with pytest.raises(ValueError, match="路径无效"):
        config_service.import_full_config_zip(traversal_buffer.getvalue())

    missing_buffer = io.BytesIO()
    with zipfile.ZipFile(missing_buffer, "w") as archive:
        archive.writestr(
            config_service.CONFIG_ZIP_ENTRY,
            json.dumps(
                {
                    "image_style": {
                        "active_references": {
                            "style": {
                                "asset": "assets/0002_missing.png",
                                "mime": "image/png",
                            }
                        }
                    }
                }
            ),
        )
        archive.writestr("assets/0001_ref.png", png_bytes(8, 8))
    with pytest.raises(ValueError, match="缺少参考图片"):
        config_service.import_full_config_zip(missing_buffer.getvalue())


def test_zip_asset_total_size_limit_is_enforced() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            config_service.CONFIG_ZIP_ENTRY,
            json.dumps(
                {
                    "image_style": {
                        "active_references": {
                            "style": {
                                "asset": "assets/0001_big.png",
                                "mime": "image/png",
                            }
                        }
                    }
                }
            ),
        )
        archive.writestr("assets/0001_big.png", b"0123456789")
    with patch.object(config_service, "CONFIG_ZIP_MAX_ASSET_BYTES", 4):
        with pytest.raises(ValueError, match="总大小超过限制"):
            config_service.import_full_config_zip(buffer.getvalue())


def test_invalid_containers_are_rejected_with_clear_errors() -> None:
    with pytest.raises(ValueError, match="不是有效的 ZIP"):
        config_service.import_full_config_zip(b"PK\x03\x04not-a-zip")
    with pytest.raises(ValueError, match="无法识别的配置包格式"):
        config_service.import_config_bundle_bytes(b"definitely not json")
    empty_buffer = io.BytesIO()
    with zipfile.ZipFile(empty_buffer, "w") as archive:
        archive.writestr("README.txt", "no config here")
    with pytest.raises(ValueError, match="缺少 config.json"):
        config_service.import_full_config_zip(empty_buffer.getvalue())


def test_config_bundle_route_accepts_zip_and_legacy_json() -> None:
    captured = {}

    def capture_update(settings):
        captured.update(settings)

    original = config_service._deps()
    config_service.configure_config_portability_dependencies(
        configured_config_dependencies(
            get_all_settings=lambda: {"llm_api_key": "existing"},
            update_settings=capture_update,
        )
    )
    try:
        client = TestClient(server.app)
        bundle = {
            "settings": {
                "llm_api_key": settings_service.MASKED_SETTINGS_VALUE,
                "llm_model": "new-model",
            }
        }
        response = client.post(
            "/api/config/import-zip",
            content=config_service.build_config_zip_bytes(bundle),
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert captured == {"llm_api_key": "existing", "llm_model": "new-model"}

        captured.clear()
        legacy = json.dumps({"settings": {"llm_model": "older"}}).encode("utf-8")
        response = client.post(
            "/api/config/import-zip",
            content=legacy,
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 200
        assert captured == {"llm_model": "older"}

        response = client.post(
            "/api/config/import-zip",
            content=b"",
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "上传的配置包为空"
    finally:
        config_service.configure_config_portability_dependencies(original)


def test_zip_export_route_returns_downloadable_archive() -> None:
    response = TestClient(server.app).get("/api/config/export-zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert ".zip" in disposition
    assert response.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert config_service.CONFIG_ZIP_ENTRY in names
        assert config_service.CONFIG_ZIP_README_ENTRY in names


def test_secret_zip_export_requires_explicit_confirmation() -> None:
    client = TestClient(server.app)
    response = client.post("/api/config/export-with-secrets-zip", json={})
    assert response.status_code == 400

    original = config_service._deps()
    config_service.configure_config_portability_dependencies(
        configured_config_dependencies(
            get_all_settings=lambda: {"llm_api_key": "secret"},
        )
    )
    try:
        response = client.post(
            "/api/config/export-with-secrets-zip",
            json={"confirmation": "EXPORT_SECRETS"},
        )
    finally:
        config_service.configure_config_portability_dependencies(original)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        stored = json.loads(
            archive.read(config_service.CONFIG_ZIP_ENTRY).decode("utf-8")
        )
    assert stored["settings"]["llm_api_key"] == "secret"


if __name__ == "__main__":
    test_zip_export_extracts_assets_and_round_trips()
    test_zip_export_sanitizes_asset_filenames()
    test_json_importer_rejects_bare_zip_config_json()
    test_zip_import_rejects_unsafe_or_missing_asset_paths()
    test_zip_asset_total_size_limit_is_enforced()
    test_invalid_containers_are_rejected_with_clear_errors()
    test_config_bundle_route_accepts_zip_and_legacy_json()
    test_zip_export_route_returns_downloadable_archive()
    test_secret_zip_export_requires_explicit_confirmation()
    print("config zip bundle checks passed")
