"""Read-only diagnostics for explicitly registered source services."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from route_inventory import iter_effective_routes


router = APIRouter()

EXPECTED_SOURCE_ROUTES = {
    "/api/projects/{project_id}/one-click-generate": {"POST"},
    "/api/projects/{project_id}/steps/5/ai-mask/annotate": {"POST"},
    "/api/projects/{project_id}/steps/3/image-style": {"GET", "PUT"},
}


def _route_methods_by_path(app: Any) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for route in iter_effective_routes(app):
        path = route.path
        if not path:
            continue
        methods = set(route.methods)
        if methods:
            result.setdefault(path, set()).update(methods)
    return {path: sorted(methods) for path, methods in sorted(result.items())}


def _diagnostics_payload(app: Any) -> dict[str, Any]:
    routes = _route_methods_by_path(app)
    effective_route_count = sum(1 for _ in iter_effective_routes(app))
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
        "route_count": effective_route_count,
        "routes": routes,
    }


@router.get("/api/runtime/diagnostics")
def runtime_diagnostics(request: Request) -> dict[str, Any]:
    return _diagnostics_payload(request.app)
