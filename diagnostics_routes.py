"""Read-only diagnostics for explicitly registered source services."""

from __future__ import annotations

from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_runtime_diagnostics_patch__"

EXPECTED_SOURCE_ROUTES = {
    "/api/projects/{project_id}/one-click-generate": {"POST"},
    "/api/projects/{project_id}/steps/5/ai-mask/annotate": {"POST"},
    "/api/projects/{project_id}/steps/3/image-style": {"GET", "PUT"},
}


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


def _diagnostics_payload(server_module: ModuleType) -> dict[str, Any]:
    app = server_module.app
    routes = _route_methods_by_path(app)
    missing_routes = sorted(
        f"{method} {path}"
        for path, methods in EXPECTED_SOURCE_ROUTES.items()
        for method in methods
        if method not in routes.get(path, [])
    )
    return {
        "success": True,
        "registration_mode": "explicit_source",
        "runtime_bootstrap_loaded": False,
        "runtime_modules": [],
        "expected_routes": {path: sorted(methods) for path, methods in sorted(EXPECTED_SOURCE_ROUTES.items())},
        "missing_routes": missing_routes,
        "route_count": len(getattr(app, "routes", []) or []),
        "routes": routes,
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
