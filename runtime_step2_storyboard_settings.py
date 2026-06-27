"""Step 2 storyboard settings UI injection.

This keeps storyboard prompt controls inside Step 2 and hides technical labels
such as "article 2slide" behind a user-facing "分镜设置" entry.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_step2_storyboard_settings_patch__"
SCRIPT_NAME = "step2_storyboard_settings_extension.js"
SCRIPT_TAG = '<script src="step2_storyboard_settings_extension.js?v=20260627.1"></script>'


def _install_injection(app: Any) -> None:
    if getattr(app.state, PATCH_MARKER, False):
        return

    @app.middleware("http")
    async def step2_storyboard_settings_injection(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", "").lower():
            return response
        try:
            body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        except Exception:
            return response
        if SCRIPT_NAME not in body and "</body>" in body:
            body = body.replace("</body>", f"  {SCRIPT_TAG}\n</body>")
        from starlette.responses import Response
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body, status_code=response.status_code, headers=headers, media_type="text/html")

    setattr(app.state, PATCH_MARKER, True)


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    if not hasattr(server_module, "app"):
        return False
    _install_injection(server_module.app)
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_STEP2_STORYBOARD_SETTINGS"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-step2-storyboard-settings-runtime", target=worker, daemon=True).start()


_install_when_ready()
