"""Step 3 visual draft quality UI injection.

The API lives in ``runtime_visual_draft_quality.py``. This bridge injects the
small Step 3 toolbar extension that calls that API and renders a read-only
quality report before users move into Step 5 Mask work.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_visual_draft_quality_ui_patch__"
SCRIPT_NAME = "visual_draft_quality_extension.js"
SCRIPT_VERSION = "20260627.2"
SCRIPT_TAG = f'<script src="{SCRIPT_NAME}?v={SCRIPT_VERSION}"></script>'
INSTALL_TIMEOUT_SEC = 120.0
POLL_INTERVAL_SEC = 0.1


def _rewrite_visual_quality_script(body: str) -> str:
    if SCRIPT_TAG in body:
        return body
    if SCRIPT_NAME in body:
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
    async def visual_draft_quality_ui(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", "").lower():
            return response
        try:
            body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        except Exception:
            return response
        body = _rewrite_visual_quality_script(body)
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
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_VISUAL_DRAFT_QUALITY_UI"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                return
            time.sleep(POLL_INTERVAL_SEC)

    threading.Thread(name="ppt-visual-draft-quality-ui", target=worker, daemon=True).start()


_install_when_ready()
