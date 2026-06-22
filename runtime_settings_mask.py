"""Optional masking for sensitive settings returned by the local settings API.

Enable with:

    PPT_STUDIO_MASK_SETTINGS_SECRETS=1

When enabled, GET /api/settings returns placeholders for configured credential
fields. PUT /api/settings preserves existing stored credential values when those
placeholders are submitted back by the browser form.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from types import ModuleType
from typing import Any


ENABLE_ENV = "PPT_STUDIO_MASK_SETTINGS_SECRETS"
DISABLE_FLAG = "PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES"
MASKED_VALUE = "__PPT_STUDIO_MASKED_VALUE__"
_PATCH_MARKER = "__ppt_settings_mask_patch__"

MASK_KEYS = frozenset(
    {
        "llm_api_key",
        "image_api_key",
        "tts_api_key",
        "tts_secret_key",
        "tts_provider_extra",
    }
)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _mask_dict(settings: dict[str, Any]) -> dict[str, Any]:
    masked = dict(settings or {})
    for key in MASK_KEYS:
        if masked.get(key) not in (None, ""):
            masked[key] = MASKED_VALUE
    return masked


def _extract_settings(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "settings") and isinstance(payload.settings, dict):
        return dict(payload.settings)
    if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
        return dict(payload["settings"])
    return {}


def _write_settings_to_payload(payload: Any, settings: dict[str, Any]) -> Any:
    if hasattr(payload, "settings"):
        payload.settings = settings
        return payload
    if isinstance(payload, dict):
        payload["settings"] = settings
        return payload
    return payload


def _install_on_server_module(server_module: ModuleType) -> bool:
    if os.environ.get(DISABLE_FLAG):
        return True
    if getattr(server_module, _PATCH_MARKER, False):
        return True
    if not _enabled(ENABLE_ENV):
        setattr(server_module, _PATCH_MARKER, True)
        return True

    app = getattr(server_module, "app", None)
    if app is None or not hasattr(app, "routes"):
        return False
    if not all(hasattr(server_module, name) for name in ("get_all_settings", "update_settings")):
        return False

    def get_settings() -> dict[str, Any]:
        return _mask_dict(server_module.get_all_settings())

    def update_system_settings(payload: Any) -> dict[str, str | bool]:
        incoming = _extract_settings(payload)
        current = server_module.get_all_settings()
        for key in MASK_KEYS:
            if incoming.get(key) == MASKED_VALUE:
                incoming[key] = current.get(key, "")
        _write_settings_to_payload(payload, incoming)
        server_module.update_settings(incoming)
        return {"success": True, "message": "设置更新成功"}

    get_settings.__name__ = "get_settings"
    update_system_settings.__name__ = "update_system_settings"
    server_module.get_settings = get_settings
    server_module.update_system_settings = update_system_settings

    for route in getattr(app, "routes", []) or []:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path == "/api/settings" and "GET" in methods:
            route.endpoint = get_settings
            if hasattr(route, "dependant"):
                route.dependant.call = get_settings
        if path == "/api/settings" and "PUT" in methods:
            route.endpoint = update_system_settings
            if hasattr(route, "dependant"):
                route.dependant.call = update_system_settings

    setattr(server_module, _PATCH_MARKER, True)
    return True


def _candidate_server_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        app = getattr(module, "app", None)
        if app is not None and hasattr(app, "routes"):
            modules.append(module)
    return modules


def install_when_server_is_ready() -> None:
    def worker() -> None:
        while not os.environ.get(DISABLE_FLAG):
            for module in _candidate_server_modules():
                if _install_on_server_module(module):
                    return
            time.sleep(0.1)

    threading.Thread(target=worker, name="ppt-settings-mask-patch", daemon=True).start()


install_when_server_is_ready()
