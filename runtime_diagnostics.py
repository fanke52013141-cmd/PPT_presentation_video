"""Runtime diagnostics endpoint.

This read-only route helps local operators verify that additive runtime bridges,
critical API routes, and middleware-only UI bridges are installed after startup.
It does not expose secrets or project data.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_runtime_diagnostics_patch__"
INSTALL_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 0.1

MIDDLEWARE_BRIDGE_MARKERS = {
    "runtime_ai_mask_ui_cache_buster": "__ppt_ai_mask_ui_cache_buster_patch__",
    "runtime_one_click_ui_cache_buster": "__ppt_one_click_ui_cache_buster_patch__",
    "runtime_step5_flush_bridge": "__ppt_step5_flush_bridge_patch__",
    "runtime_step2_storyboard_settings": "__ppt_step2_storyboard_settings_patch__",
    "runtime_project_style_reference_manager": "__ppt_project_style_reference_manager_inject_patch__",
}


def _runtime_bootstrap() -> ModuleType | None:
    try:
        return importlib.import_module("runtime_bootstrap")
    except Exception:
        return None


def _route_methods_by_path(app: Any) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for route in getattr(app, "routes", []) or []:
        path = str(getattr(route, "path", ""))
        if not path:
            continue
        methods = {str(method).upper() for method in (getattr(route, "methods", []) or [])}
        if methods:
            result.setdefault(path, set()).update(methods)
    return {path: sorted(methods) for path, methods in sorted(result.items())}


def _module_status(module_names: list[str]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for name in module_names:
        try:
            module = importlib.import_module(name)
            statuses.append({"name": name, "imported": True, "file": getattr(module, "__file__", "")})
        except Exception as exc:
            statuses.append({"name": name, "imported": False, "error": f"{type(exc).__name__}: {exc}"})
    return statuses


def _middleware_marker_status(app: Any) -> dict[str, bool]:
    return {name: bool(getattr(app.state, marker, False)) for name, marker in MIDDLEWARE_BRIDGE_MARKERS.items()}


def _script_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {}
    for module_name, attrs in {
        "runtime_step5_flush_bridge": ["APP_SCRIPT_VERSION", "AI_MASK_SCRIPT_VERSION"],
        "runtime_ai_mask_ui_cache_buster": ["SCRIPT_VERSION"],
        "runtime_one_click_ui_cache_buster": ["SCRIPT_VERSION"],
    }.items():
        try:
            module = importlib.import_module(module_name)
            versions[module_name] = {attr: getattr(module, attr, None) for attr in attrs}
        except Exception as exc:
            versions[module_name] = {"error": f"{type(exc).__name__}: {exc}"}
    return versions


def _diagnostics_payload(server_module: ModuleType) -> dict[str, Any]:
    app = server_module.app
    bootstrap = _runtime_bootstrap()
    runtime_modules = list(getattr(bootstrap, "RUNTIME_MODULES", [])) if bootstrap else []
    expected_routes = getattr(bootstrap, "EXPECTED_RUNTIME_ROUTES", {}) if bootstrap else {}
    missing_routes = sorted(bootstrap.missing_runtime_routes(server_module)) if bootstrap and hasattr(bootstrap, "missing_runtime_routes") else []
    routes = _route_methods_by_path(app)
    return {
        "success": True,
        "runtime_bootstrap_loaded": bootstrap is not None,
        "runtime_modules": _module_status(runtime_modules),
        "expected_routes": {path: sorted(methods) for path, methods in sorted(expected_routes.items())},
        "missing_routes": missing_routes,
        "route_count": len(getattr(app, "routes", []) or []),
        "routes": routes,
        "middleware_markers": _middleware_marker_status(app),
        "script_versions": _script_versions(),
    }


def _register(server_module: ModuleType) -> bool:
    app = getattr(server_module, "app", None)
    if app is None:
        return False
    if getattr(server_module, PATCH_MARKER, False):
        return True

    def runtime_diagnostics() -> dict[str, Any]:
        return _diagnostics_payload(server_module)

    app.add_api_route("/api/runtime/diagnostics", runtime_diagnostics, methods=["GET"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_DIAGNOSTICS"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                return
            time.sleep(POLL_INTERVAL_SEC)

    threading.Thread(name="ppt-runtime-diagnostics", target=worker, daemon=True).start()


_install_when_ready()
