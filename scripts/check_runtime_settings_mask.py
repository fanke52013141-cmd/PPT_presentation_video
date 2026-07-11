#!/usr/bin/env python3
"""Self-check the production Settings API credential contract."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


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

    with patch.dict(os.environ, {}, clear=True), patch.object(server, "get_all_settings", side_effect=lambda: dict(stored)), patch.object(server, "update_settings", side_effect=update):
        masked = server.get_settings()
        for key in server.SETTINGS_SECRET_KEYS:
            if masked[key] != server.MASKED_SETTINGS_VALUE:
                print(f"FAIL {key} was not masked by the production route")
                return 1
        if masked["llm_model"] != "model-name":
            print("FAIL non-sensitive setting was modified")
            return 1

        server.update_system_settings(
            server.SettingsUpdate(
                settings={
                    **{key: server.MASKED_SETTINGS_VALUE for key in server.SETTINGS_SECRET_KEYS},
                    "llm_model": "new-model",
                }
            )
        )
        if stored["llm_api_key"] != "real-llm-key" or stored["tts_secret_key"] != "real-tts-secret":
            print("FAIL masked placeholder overwrote a stored credential")
            return 1
        if stored["llm_model"] != "new-model":
            print("FAIL ordinary setting was not updated")
            return 1

    print("OK production settings mask self-check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
