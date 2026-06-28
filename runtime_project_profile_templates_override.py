"""Override Project Profile template listing for the simplified create flow.

Creation should only expose automation mode. Storyboard style belongs to Step 2;
image style and references belong to Step 3. The original Project Profile bridge
keeps compatibility routes and storage, but this response prevents the create
modal from seeing project-level storyboard/image-style templates.

The lightweight profile and Step 3 state modules are installed explicitly by
runtime_bootstrap; this module only owns the simplified template response.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_project_profile_templates_override_patch__"

AUTOMATION_MODES = [
    {"id": "manual_review", "name": "手动审核模式", "description": "按原流程逐步生成、检查和确认。"},
    {"id": "auto", "name": "全自动模式", "description": "配合一键生成运行完整链路；失败时暂停给用户处理。"},
]


def _route_methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", []) or [])


def _insert_before_existing(app: Any, path: str, methods: set[str], route: Any) -> None:
    routes = getattr(getattr(app, "router", None), "routes", None)
    if not isinstance(routes, list):
        app.router.routes.append(route)
        return
    for index, existing in enumerate(routes):
        if str(getattr(existing, "path", "")) == path and methods.issubset(_route_methods(existing)):
            routes.insert(index, route)
            return
    routes.append(route)


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app",)
    if not all(hasattr(server_module, name) for name in required):
        return False
    app = server_module.app

    def get_simplified_templates() -> dict[str, Any]:
        return {
            "success": True,
            "automation_modes": AUTOMATION_MODES,
            "storyboard_templates": [],
            "image_style_templates": [],
            "note": "Creation only exposes automation mode. Step 2 owns storyboard style; Step 3 owns image style.",
        }

    from fastapi.routing import APIRoute

    route = APIRoute(
        path="/api/project-profile/templates",
        endpoint=get_simplified_templates,
        methods=["GET"],
        name="get_simplified_project_profile_templates",
    )
    _insert_before_existing(app, "/api/project-profile/templates", {"GET"}, route)
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_PROJECT_PROFILE_TEMPLATES_OVERRIDE") and time.monotonic() - started_at < 120:
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-project-profile-templates-override", target=worker, daemon=True).start()


_install_when_ready()
