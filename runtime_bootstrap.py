"""Runtime bridge bootstrap for PPT Visualization Studio.

The runtime bridge modules add routes and UI injection around the large ``server.py``
module. Relying on Python's optional ``usercustomize`` import is not sufficient for
normal local launches, so this bootstrap is imported from ``database.py`` and waits
briefly for the server module to expose its FastAPI app and project helpers.

The loader is intentionally bounded and non-blocking. It only imports bridge modules
when a server-like module is present in ``sys.modules``.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

BOOTSTRAP_MARKER = "__ppt_runtime_bootstrap_started__"
INSTALL_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 0.05

RUNTIME_MODULES = [
    "runtime_settings_mask",
    "runtime_ai_mask",
    "runtime_storyboard_background",
    "runtime_storyboard_background_render",
    "runtime_project_profile",
    "runtime_project_style_references",
    "runtime_project_style_reference_manager",
    "runtime_project_style_reference_step3",
    "runtime_image_style_reverse",
    "runtime_one_click_orchestrator",
]


def _server_candidates() -> list[ModuleType]:
    candidates: list[ModuleType] = []
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        if all(hasattr(module, attr) for attr in ("app", "Project", "get_db")):
            candidates.append(module)
    return candidates


def _logger() -> Any:
    for module in _server_candidates():
        logger = getattr(module, "logger", None)
        if logger is not None:
            return logger
    return None


def _import_runtime_modules() -> bool:
    ok = True
    for module_name in RUNTIME_MODULES:
        try:
            __import__(module_name)
        except Exception as exc:
            ok = False
            logger = _logger()
            if logger is not None:
                logger.warning("Failed to import runtime bridge %s: %s", module_name, exc)
    return ok


def install_when_server_ready() -> None:
    if os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_BOOTSTRAP"):
        return
    if getattr(sys, BOOTSTRAP_MARKER, False):
        return
    setattr(sys, BOOTSTRAP_MARKER, True)

    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_BOOTSTRAP"):
            if _server_candidates():
                _import_runtime_modules()
                return
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                logger = _logger()
                if logger is not None:
                    logger.warning("Runtime bridge bootstrap did not find server app within %.0f seconds.", INSTALL_TIMEOUT_SEC)
                return
            time.sleep(POLL_INTERVAL_SEC)

    threading.Thread(name="ppt-runtime-bootstrap", target=worker, daemon=True).start()
