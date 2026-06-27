"""One-click UI cache-buster bridge.

The one-click backend status and UI copy can change independently from the large
orchestrator runtime. This bridge keeps the injected ``one_click_extension.js``
query string current without rewriting ``runtime_one_click_orchestrator.py``.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_one_click_ui_cache_buster_patch__"
SCRIPT_NAME = "one_click_extension.js"
SCRIPT_VERSION = "20260627.7"
SCRIPT_TAG = f'<script src="{SCRIPT_NAME}?v={SCRIPT_VERSION}"></script>'


def _rewrite_one_click_script(body: str) -> str:
    if SCRIPT_TAG in body:
        return body
    if SCRIPT_NAME in body:
        import re

        return re.sub(
            rf'<script\s+src="{SCRIPT_NAME}(?:\?v=[^"]+)?"></script>',
            SCRIPT_TAG,
            body,
        )
    if "</body>" in body:
        return body.replace("</body>", f"  {SCRIPT_TAG}\n</body>")
    return body


def _register(server_module: ModuleType) -> bool:
    app = getattr(server_module, "app", None)
    if app is None:
        return False
    if getattr(app.state, PATCH_MARKER, False):
        return True

    @app.middleware("http")
    async def one_click_ui_cache_buster(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", "").lower():
            return response
        try:
            body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        except Exception:
            return response
        body = _rewrite_one_click_script(body)
        from starlette.responses import Response

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body, status_code=response.status_code, headers=headers, media_type="text/html")

    setattr(app.state, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_ONE_CLICK_UI_CACHE_BUSTER"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)

    threading.Thread(name="ppt-one-click-ui-cache-buster", target=worker, daemon=True).start()


_install_when_ready()
