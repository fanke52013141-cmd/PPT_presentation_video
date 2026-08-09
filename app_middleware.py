"""Application middleware installers owned outside the composition root."""

from __future__ import annotations

from typing import Any


def install_static_asset_cache_policy(app: Any) -> None:
    """Disable browser caching for the local UI while leaving APIs untouched."""

    @app.middleware("http")
    async def no_cache_static_assets(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api") or not path or path == "/favicon.ico":
            return response
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
