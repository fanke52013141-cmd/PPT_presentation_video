"""Runtime bridge bootstrap for PPT Visualization Studio.

Runtime bridge modules add routes and UI injection around the large ``server.py``
module. Relying on Python's optional ``usercustomize`` import is not sufficient for
normal local launches.

This bootstrap is imported from ``database.py`` early during ``server.py`` import.
It patches ``FastAPI.mount`` so the bridge modules are imported immediately before
the final static catch-all mount is registered. That guarantees API routes are
registered before ``app.mount("/", StaticFiles(...))`` can shadow them.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

BOOTSTRAP_MARKER = "__ppt_runtime_bootstrap_started__"
MOUNT_PATCH_MARKER = "__ppt_runtime_bootstrap_mount_patch__"
IMPORT_MARKER = "__ppt_runtime_bridges_imported__"
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
    if getattr(sys, IMPORT_MARKER, False):
        return True
    ok = True
    for module_name in RUNTIME_MODULES:
        try:
            __import__(module_name)
        except Exception as exc:
            ok = False
            logger = _logger()
            if logger is not None:
                logger.warning("Failed to import runtime bridge %s: %s", module_name, exc)
    if ok:
        setattr(sys, IMPORT_MARKER, True)
    return ok


def _patch_fastapi_mount() -> None:
    try:
        from fastapi import FastAPI
    except Exception:
        return

    current_mount = getattr(FastAPI, "mount", None)
    if current_mount is None or getattr(current_mount, MOUNT_PATCH_MARKER, False):
        return
    original_mount = current_mount

    def mount_with_runtime_bridges(self: Any, path: str, *args: Any, **kwargs: Any):
        if not os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_BOOTSTRAP"):
            # Import bridge modules before the static catch-all mount is added.
            _import_runtime_modules()
        return original_mount(self, path, *args, **kwargs)

    setattr(mount_with_runtime_bridges, MOUNT_PATCH_MARKER, True)
    FastAPI.mount = mount_with_runtime_bridges


def install_when_server_ready() -> None:
    if os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_BOOTSTRAP"):
        return
    if getattr(sys, BOOTSTRAP_MARKER, False):
        return
    setattr(sys, BOOTSTRAP_MARKER, True)
    _patch_fastapi_mount()

    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_BOOTSTRAP"):
            if _server_candidates():
                # Fallback for non-standard apps that do not call FastAPI.mount.
                # In normal server.py startup, the mount patch above imports the
                # bridges at the safer pre-static-mount point.
                if getattr(sys, IMPORT_MARKER, False):
                    return
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                logger = _logger()
                if logger is not None:
                    logger.warning("Runtime bridge bootstrap did not import bridges within %.0f seconds.", INSTALL_TIMEOUT_SEC)
                return
            time.sleep(POLL_INTERVAL_SEC)

    threading.Thread(name="ppt-runtime-bootstrap", target=worker, daemon=True).start()
