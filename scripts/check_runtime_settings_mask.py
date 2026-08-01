#!/usr/bin/env python3
"""Self-check the production Settings API credential contract."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402, F401
import settings_service  # noqa: E402


def main() -> int:
    stored = {
        "llm_api_key": "real-llm-key",
        "image_api_key": "real-image-key",
        "tts_api_key": "real-tts-key",
        "tts_secret_key": "real-tts-secret",
        "tts_provider_extra": '{"private":"value"}',
        "llm_model": "model-name",
    }

    def update(values: dict[str, str]) -> None:
        stored.update(values)

    original = settings_service._deps()
    dependencies = settings_service.SettingsDependencies(
        **{
            **{
                field: getattr(original, field)
                for field in original.__dataclass_fields__
            },
            "get_all_settings": lambda: dict(stored),
            "update_settings": update,
        }
    )
    settings_service.configure_settings_dependencies(dependencies)
    try:
        with patch.dict(os.environ, {}, clear=True):
            masked = settings_service.get_settings()
            for key in settings_service.SETTINGS_SECRET_KEYS:
                if (
                    masked[key]
                    != settings_service.MASKED_SETTINGS_VALUE
                ):
                    print(
                        f"FAIL {key} was not masked by the "
                        "production route"
                    )
                    return 1
            if masked["llm_model"] != "model-name":
                print("FAIL non-sensitive setting was modified")
                return 1

            settings_service.update_system_settings(
                settings_service.SettingsUpdate(
                    settings={
                        **{
                            key: settings_service.MASKED_SETTINGS_VALUE
                            for key in (
                                settings_service.SETTINGS_SECRET_KEYS
                            )
                        },
                        "llm_model": "new-model",
                    }
                )
            )
            if (
                stored["llm_api_key"] != "real-llm-key"
                or stored["tts_secret_key"] != "real-tts-secret"
            ):
                print(
                    "FAIL masked placeholder overwrote a stored "
                    "credential"
                )
                return 1
            if stored["llm_model"] != "new-model":
                print("FAIL ordinary setting was not updated")
                return 1
    finally:
        settings_service.configure_settings_dependencies(original)

    print("OK production settings mask self-check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
