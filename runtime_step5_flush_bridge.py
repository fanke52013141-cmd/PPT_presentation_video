"""Step 5 draft flush compatibility bridge.

The preferred long-term implementation is a native ``window.PPTStudio.flushStep5Draft``
export in ``static/app.js``. Until every local checkout has that native export,
this bridge keeps older app.js responses working by injecting the same function
inside the app.js script scope. If app.js already exposes the native API, this
bridge leaves app.js unchanged and only keeps script cache-busting active.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_step5_flush_bridge_patch__"
APP_SCRIPT_VERSION = "20260627.6"
AI_MASK_SCRIPT_VERSION = "20260627.7"
APP_FLUSH_MARKER = "__PPT_STEP5_FLUSH_BRIDGE__"
AI_MASK_FLUSH_MARKER = "__PPT_AI_MASK_FLUSH_BRIDGE__"

APP_FLUSH_INSERT = f"""
// {APP_FLUSH_MARKER}
async function flushStep5Draft(options = {{}}) {{
  if (state.step5AutoSaveTimer) {{
    clearTimeout(state.step5AutoSaveTimer);
    state.step5AutoSaveTimer = null;
  }}
  if (state.step5AutoSavePromise) {{
    try {{
      await state.step5AutoSavePromise;
    }} catch (error) {{
      // Retry below with the newest Step 5 editor snapshot.
    }}
  }}
  if (!manifestData?.slides?.length) {{
    return {{ success: false, reason: 'no_step5_manifest' }};
  }}
  saveStep5CurrentState();
  return await saveStep5Draft();
}}

window.PPTStudio = Object.assign(window.PPTStudio || {{}}, {{
  getCurrentProject: () => state.currentProject,
  flushStep5Draft,
}});
"""

AI_MASK_FLUSH_REPLACEMENT = f"""  async function flushStep5DraftBeforeAiMask() {{
    // {AI_MASK_FLUSH_MARKER}
    if (window.PPTStudio && typeof window.PPTStudio.flushStep5Draft === 'function') {{
      await window.PPTStudio.flushStep5Draft({{ source: 'ai-mask', silent: true }});
      return;
    }}
    if (typeof window.saveStep5CurrentState === 'function') {{
      window.saveStep5CurrentState();
    }}
    if (typeof window.saveStep5Draft === 'function') {{
      await window.saveStep5Draft();
    }}
    // Legacy fallback for older app.js: wait once so a pending stale save can finish.
    await sleep(900);
    if (typeof window.saveStep5CurrentState === 'function') {{
      window.saveStep5CurrentState();
    }}
    if (typeof window.saveStep5Draft === 'function') {{
      await window.saveStep5Draft();
    }}
  }}"""


def app_has_native_step5_flush(body: str) -> bool:
    return "flushStep5Draft" in body and "window.PPTStudio" in body


def _rewrite_html(body: str) -> str:
    body = re.sub(r'app\.js(?:\?v=[^"\']+)?', f'app.js?v={APP_SCRIPT_VERSION}', body)
    body = re.sub(r'ai_mask_extension\.js(?:\?v=[^"\']+)?', f'ai_mask_extension.js?v={AI_MASK_SCRIPT_VERSION}', body)
    return body


def _rewrite_app_js(body: str) -> str:
    if APP_FLUSH_MARKER in body or app_has_native_step5_flush(body):
        return body
    anchor = "\nasync function runStep5SemanticBlocks() {"
    if anchor not in body:
        return body
    return body.replace(anchor, "\n" + APP_FLUSH_INSERT + anchor, 1)


def _rewrite_ai_mask_js(body: str) -> str:
    if AI_MASK_FLUSH_MARKER in body:
        return body
    pattern = r"  async function flushStep5DraftBeforeAiMask\(\) \{.*?\n  \}\n\n  function summarizeResult"
    replacement = AI_MASK_FLUSH_REPLACEMENT + "\n\n  function summarizeResult"
    rewritten, count = re.subn(pattern, replacement, body, count=1, flags=re.S)
    return rewritten if count else body


def _script_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].split("?", 1)[0]


def _rewrite_body(path: str, content_type: str, body: str) -> str:
    lower_type = content_type.lower()
    if "text/html" in lower_type:
        return _rewrite_html(body)
    name = _script_name(path)
    if name == "app.js":
        return _rewrite_app_js(body)
    if name == "ai_mask_extension.js":
        return _rewrite_ai_mask_js(body)
    return body


def _register(server_module: ModuleType) -> bool:
    app = getattr(server_module, "app", None)
    if app is None:
        return False
    if getattr(app.state, PATCH_MARKER, False):
        return True

    @app.middleware("http")
    async def step5_flush_bridge(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        path = str(getattr(request, "url", ""))
        if not ("text/html" in content_type.lower() or path.split("?", 1)[0].endswith(("/app.js", "/ai_mask_extension.js"))):
            return response
        try:
            body = b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")
        except Exception:
            return response
        body = _rewrite_body(path, content_type, body)
        from starlette.responses import Response

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body, status_code=response.status_code, headers=headers, media_type=content_type.split(";", 1)[0] or None)

    setattr(app.state, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_STEP5_FLUSH_BRIDGE"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            if time.monotonic() - started_at > 120:
                return
            time.sleep(0.1)

    threading.Thread(name="ppt-step5-flush-bridge", target=worker, daemon=True).start()


_install_when_ready()
