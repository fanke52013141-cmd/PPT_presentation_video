import os
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def test_default_config_export_masks_credentials() -> None:
    settings = {
        "llm_api_key": "llm-secret",
        "image_api_key": "image-secret",
        "tts_secret_key": "tts-secret",
        "llm_model": "model-name",
    }
    with patch.dict(os.environ, {"PPT_STUDIO_MASK_SETTINGS_SECRETS": "1"}), patch(
        "server.get_all_settings", return_value=settings
    ):
        payload = server.export_full_config()
    assert payload["contains_secrets"] is False
    assert payload["settings"]["llm_api_key"] == server.MASKED_SETTINGS_VALUE
    assert payload["settings"]["image_api_key"] == server.MASKED_SETTINGS_VALUE
    assert payload["settings"]["tts_secret_key"] == server.MASKED_SETTINGS_VALUE
    assert payload["settings"]["llm_model"] == "model-name"

    with patch.dict(os.environ, {"PPT_STUDIO_MASK_SETTINGS_SECRETS": "0"}), patch(
        "server.get_all_settings", return_value=settings
    ):
        forced_payload = server.export_full_config()
    assert forced_payload["settings"]["llm_api_key"] == server.MASKED_SETTINGS_VALUE


def test_secret_export_requires_explicit_confirmation() -> None:
    try:
        server.export_full_config_with_secrets({})
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("secret export unexpectedly succeeded without confirmation")

    with patch("server.get_all_settings", return_value={"llm_api_key": "secret"}):
        payload = server.export_full_config_with_secrets({"confirmation": "EXPORT_SECRETS"})
    assert payload["contains_secrets"] is True
    assert payload["settings"]["llm_api_key"] == "secret"


def test_imported_mask_placeholder_preserves_existing_secret() -> None:
    captured = {}

    def capture_update(settings):
        captured.update(settings)

    with patch("server.get_all_settings", return_value={"llm_api_key": "existing"}), patch(
        "server.update_settings", side_effect=capture_update
    ):
        response = TestClient(server.app).post(
            "/api/config/import",
            json={"settings": {"llm_api_key": server.MASKED_SETTINGS_VALUE, "llm_model": "new-model"}},
        )
    assert response.status_code == 200
    assert captured == {"llm_api_key": "existing", "llm_model": "new-model"}
