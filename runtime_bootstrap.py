"""Runtime bridge bootstrap for PPT Visualization Studio.

Runtime bridge modules add routes and UI injection around the large ``server.py``
module. Relying on Python's optional ``usercustomize`` import is not sufficient
for normal local launches.

This bootstrap is imported from ``database.py`` early during ``server.py`` import.
It patches ``FastAPI.mount`` and also exposes a synchronous installer so runtime
API routes are registered before ``app.mount("/", StaticFiles(...))`` can shadow
them.
"""

from __future__ import annotations

import importlib
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
    "runtime_project_profile_templates_override",
    "runtime_project_style_references",
    "runtime_project_style_reference_manager",
    "runtime_project_style_reference_step3",
    "runtime_image_style_reverse",
    "runtime_step3_image_style",
    "runtime_one_click_orchestrator",
]

EXPECTED_RUNTIME_PATHS = {
    "/api/settings/ai-mask",
    "/api/project-profile/templates",
    "/api/projects/{project_id}/one-click-generate",
}


def _server_candidates() -> list[ModuleType]:
    candidates: list[ModuleType] = []
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        if getattr(module, "__name__", "") == "__main__":
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


def _route_paths(server_module: ModuleType) -> set[str]:
    app = getattr(server_module, "app", None)
    return {
        str(getattr(route, "path", ""))
        for route in getattr(app, "routes", []) or []
        if getattr(route, "path", "")
    }


def _move_root_static_mount_to_end(server_module: ModuleType) -> None:
    app = getattr(server_module, "app", None)
    router = getattr(app, "router", None)
    routes = getattr(router, "routes", None)
    if not isinstance(routes, list):
        return

    seen: set[tuple[Any, ...]] = set()
    deduped = []
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        key = (
            route.__class__.__name__,
            str(getattr(route, "path", "")),
            tuple(sorted(getattr(route, "methods", []) or [])),
            getattr(endpoint, "__module__", ""),
            getattr(endpoint, "__qualname__", ""),
            getattr(route, "name", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(route)
    if len(deduped) != len(routes):
        routes[:] = deduped

    root_mounts = [
        route
        for route in routes
        if route.__class__.__name__ == "Mount" and str(getattr(route, "path", "")) in {"", "/"}
    ]
    if not root_mounts:
        return
    ordered = [route for route in routes if route not in root_mounts] + root_mounts
    if ordered != routes:
        routes[:] = ordered


def runtime_paths_ready(server_module: ModuleType) -> bool:
    return EXPECTED_RUNTIME_PATHS.issubset(_route_paths(server_module))


def _import_runtime_modules() -> bool:
    if getattr(sys, IMPORT_MARKER, False):
        return True

    ok = True
    for module_name in RUNTIME_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            ok = False
            logger = _logger()
            if logger is not None:
                logger.warning("Failed to import runtime bridge %s: %s", module_name, exc)
    if ok:
        setattr(sys, IMPORT_MARKER, True)
    return ok


def install_for_server_module(server_module: ModuleType) -> bool:
    """Install runtime bridge routes on a concrete server module."""

    ok = True
    for module_name in RUNTIME_MODULES:
        try:
            runtime_module = importlib.import_module(module_name)
        except Exception as exc:
            ok = False
            logger = getattr(server_module, "logger", None) or _logger()
            if logger is not None:
                logger.warning("Failed to import runtime bridge %s: %s", module_name, exc)
            continue

        register = getattr(runtime_module, "_register", None)
        if callable(register):
            try:
                if register(server_module) is False:
                    ok = False
            except Exception as exc:
                ok = False
                logger = getattr(server_module, "logger", None) or _logger()
                if logger is not None:
                    logger.warning("Failed to register runtime bridge %s: %s", module_name, exc)

    if ok:
        setattr(sys, IMPORT_MARKER, True)
    _move_root_static_mount_to_end(server_module)
    return ok


def _server_module_for_app(app: Any) -> ModuleType | None:
    for module in _server_candidates():
        if getattr(module, "app", None) is app:
            return module
    return None


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
            server_module = _server_module_for_app(self)
            if server_module is not None:
                install_for_server_module(server_module)
            else:
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
            for module in _server_candidates():
                if runtime_paths_ready(module):
                    return
                install_for_server_module(module)
                if runtime_paths_ready(module):
                    return
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                logger = _logger()
                if logger is not None:
                    logger.warning("Runtime bridge bootstrap did not import bridges within %.0f seconds.", INSTALL_TIMEOUT_SEC)
                return
            time.sleep(POLL_INTERVAL_SEC)

    threading.Thread(name="ppt-runtime-bootstrap", target=worker, daemon=True).start()
