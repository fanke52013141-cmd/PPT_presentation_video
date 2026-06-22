#!/usr/bin/env python3
"""Self-check optional settings masking runtime patch.

Run from the repository root:

    PPT_STUDIO_MASK_SETTINGS_SECRETS=1 python scripts/check_runtime_settings_mask.py
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeRoute:
    def __init__(self, path: str, methods: set[str]) -> None:
        self.path = path
        self.methods = methods
        self.endpoint = None
        self.dependant = SimpleNamespace(call=None)


class FakeApp:
    def __init__(self) -> None:
        self.routes = [
            FakeRoute('/api/settings', {'GET'}),
            FakeRoute('/api/settings', {'PUT'}),
        ]


class FakePayload:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings


def main() -> int:
    os.environ['PPT_STUDIO_MASK_SETTINGS_SECRETS'] = '1'
    module = importlib.import_module('runtime_settings_mask')

    stored = {
        'llm_api_key': 'real-llm-key',
        'image_api_key': 'real-image-key',
        'tts_api_key': 'real-tts-key',
        'tts_secret_key': 'real-tts-secret',
        'tts_provider_extra': '{"private":"value"}',
        'llm_model': 'model-name',
    }

    fake_server = ModuleType('fake_settings_server')
    fake_server.app = FakeApp()
    fake_server.get_all_settings = lambda: dict(stored)

    def update_settings(settings: dict[str, Any]) -> None:
        stored.update(settings)

    fake_server.update_settings = update_settings

    if module._install_on_server_module(fake_server) is not True:
        print('FAIL settings mask patch did not install')
        return 1

    masked = fake_server.get_settings()
    if masked['llm_api_key'] != module.MASKED_VALUE:
        print('FAIL llm_api_key was not masked')
        return 1
    if masked['tts_secret_key'] != module.MASKED_VALUE:
        print('FAIL tts_secret_key was not masked')
        return 1
    if masked['llm_model'] != 'model-name':
        print('FAIL non-sensitive setting was modified')
        return 1

    fake_server.update_system_settings(
        FakePayload(
            {
                'llm_api_key': module.MASKED_VALUE,
                'image_api_key': module.MASKED_VALUE,
                'tts_api_key': module.MASKED_VALUE,
                'tts_secret_key': module.MASKED_VALUE,
                'tts_provider_extra': module.MASKED_VALUE,
                'llm_model': 'new-model',
            }
        )
    )

    if stored['llm_api_key'] != 'real-llm-key':
        print('FAIL masked llm_api_key placeholder overwrote stored value')
        return 1
    if stored['tts_secret_key'] != 'real-tts-secret':
        print('FAIL masked tts_secret_key placeholder overwrote stored value')
        return 1
    if stored['llm_model'] != 'new-model':
        print('FAIL ordinary setting was not updated')
        return 1

    print('OK settings mask self-check passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
