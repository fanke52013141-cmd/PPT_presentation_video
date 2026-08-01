import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
import config_portability_service as config_service  # noqa: E402
import settings_service  # noqa: E402


def configured_config_dependencies(**changes):
    dependencies = config_service._deps()
    values = {
        field: getattr(dependencies, field)
        for field in dependencies.__dataclass_fields__
    }
    values.update(changes)
    return config_service.ConfigPortabilityDependencies(**values)


def test_default_config_export_masks_credentials() -> None:
    settings = {
        "llm_api_key": "llm-secret",
        "image_api_key": "image-secret",
        "tts_secret_key": "tts-secret",
        "llm_model": "model-name",
    }
    original = config_service._deps()
    with patch.dict(
        os.environ,
        {"PPT_STUDIO_MASK_SETTINGS_SECRETS": "1"},
    ):
        config_service.configure_config_portability_dependencies(
            configured_config_dependencies(
                get_all_settings=lambda: settings,
            )
        )
        payload = config_service.export_full_config()
    assert payload["contains_secrets"] is False
    assert (
        payload["settings"]["llm_api_key"]
        == settings_service.MASKED_SETTINGS_VALUE
    )
    assert (
        payload["settings"]["image_api_key"]
        == settings_service.MASKED_SETTINGS_VALUE
    )
    assert (
        payload["settings"]["tts_secret_key"]
        == settings_service.MASKED_SETTINGS_VALUE
    )
    assert payload["settings"]["llm_model"] == "model-name"

    with patch.dict(
        os.environ,
        {"PPT_STUDIO_MASK_SETTINGS_SECRETS": "0"},
    ):
        forced_payload = config_service.export_full_config()
    assert (
        forced_payload["settings"]["llm_api_key"]
        == settings_service.MASKED_SETTINGS_VALUE
    )
    config_service.configure_config_portability_dependencies(original)


def test_secret_export_requires_explicit_confirmation() -> None:
    client = TestClient(server.app)
    response = client.post("/api/config/export-with-secrets", json={})
    assert response.status_code == 400

    original = config_service._deps()
    config_service.configure_config_portability_dependencies(
        configured_config_dependencies(
            get_all_settings=lambda: {"llm_api_key": "secret"},
        )
    )
    response = client.post(
        "/api/config/export-with-secrets",
        json={"confirmation": "EXPORT_SECRETS"},
    )
    config_service.configure_config_portability_dependencies(original)
    assert response.status_code == 200
    payload = response.json()
    assert payload["contains_secrets"] is True
    assert payload["settings"]["llm_api_key"] == "secret"


def test_imported_mask_placeholder_preserves_existing_secret() -> None:
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
        response = TestClient(server.app).post(
            "/api/config/import",
            json={
                "settings": {
                    "llm_api_key": (
                        settings_service.MASKED_SETTINGS_VALUE
                    ),
                    "llm_model": "new-model",
                }
            },
        )
    finally:
        config_service.configure_config_portability_dependencies(
            original
        )
    assert response.status_code == 200
    assert captured == {"llm_api_key": "existing", "llm_model": "new-model"}
