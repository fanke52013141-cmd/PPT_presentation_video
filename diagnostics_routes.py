"""Read-only diagnostics for explicitly registered source services."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request


router = APIRouter()

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


def _diagnostics_payload(app: Any) -> dict[str, Any]:
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


@router.get("/api/runtime/diagnostics")
def runtime_diagnostics(request: Request) -> dict[str, Any]:
    return _diagnostics_payload(request.app)
