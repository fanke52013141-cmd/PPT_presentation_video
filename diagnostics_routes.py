"""Read-only diagnostics for explicitly registered source services."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from error_log_service import ERROR_LOG_DIR, get_latest_error_log_path
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


@router.get("/api/error-log")
def get_error_log(limit: int = 50) -> dict[str, Any]:
    """Return recent error log entries for quick diagnosis."""
    import os

    entries: list[dict[str, Any]] = []
    if not os.path.isdir(ERROR_LOG_DIR):
        return {
            "success": True,
            "entries": [],
            "total": 0,
            "log_dir": ERROR_LOG_DIR,
        }

    files = sorted(
        (f for f in os.listdir(ERROR_LOG_DIR) if f.endswith(".jsonl")),
        reverse=True,
    )
    for fname in files:
        fpath = os.path.join(ERROR_LOG_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            continue
        if len(entries) >= limit:
            break

    entries = entries[-limit:]
    return {
        "success": True,
        "total": len(entries),
        "entries": entries,
        "log_dir": ERROR_LOG_DIR,
    }


@router.get("/api/error-log/latest", response_class=PlainTextResponse)
def get_latest_error_log() -> str:
    """Return the raw contents of today's error log file."""
    log_path = get_latest_error_log_path()
    if not log_path:
        return "# 暂无错误日志记录"
    try:
        with open(log_path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise HTTPException(500, f"读取错误日志失败：{exc}") from exc
