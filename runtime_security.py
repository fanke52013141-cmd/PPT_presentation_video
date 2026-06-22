"""Optional runtime security hardening for PPT Visualization Studio.

This module is intentionally opt-in. It only enforces access control when
``PPT_STUDIO_ACCESS_TOKEN`` is set in the environment.

Supported authentication mechanisms:
- ``Authorization: Bearer <token>``
- ``X-App-Token: <token>``
- ``?access_token=<token>`` or ``?token=<token>``; a successful query-token
  request also receives an HttpOnly cookie for same-origin browser use.
- ``ppt_studio_access_token`` cookie

Optional origin restriction:
- ``PPT_STUDIO_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000``

This is a runtime bridge until the large ``server.py`` file can be safely
patched directly.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from types import ModuleType
from typing import Any


ACCESS_TOKEN_ENV = "PPT_STUDIO_ACCESS_TOKEN"
ALLOWED_ORIGINS_ENV = "PPT_STUDIO_ALLOWED_ORIGINS"
DISABLE_FLAG = "PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES"
COOKIE_NAME = "ppt_studio_access_token"
_PATCH_MARKER = "__ppt_runtime_security_patch__"


def _split_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().rstrip("/") for item in value.split(",") if item.strip()}


def _safe_eq(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return secrets.compare_digest(str(left), str(right))


def _extract_bearer(value: str | None) -> str:
    if not value:
        return ""
    prefix = "Bearer "
    if value.startswith(prefix):
        return value[len(prefix):].strip()
    return ""


def _request_token(request: Any) -> tuple[str, bool]:
    """Return ``(token, came_from_query_string)``."""
    query_token = request.query_params.get("access_token") or request.query_params.get("token")
    if query_token:
        return str(query_token), True
    header_token = request.headers.get("x-app-token") or _extract_bearer(request.headers.get("authorization"))
    if header_token:
        return str(header_token), False
    cookie_token = request.cookies.get(COOKIE_NAME)
    if cookie_token:
        return str(cookie_token), False
    return "", False


def _is_exempt_path(path: str) -> bool:
    explicit = _split_csv(os.environ.get("PPT_STUDIO_AUTH_EXEMPT_PATHS"))
    if path in explicit:
        return True
    # Keep preflight and trivial browser noise out of the way. Everything useful
    # is protected when PPT_STUDIO_ACCESS_TOKEN is set.
    return path in {"/favicon.ico"}


def _json_response(status_code: int, detail: str) -> Any:
    try:
        from starlette.responses import JSONResponse
        return JSONResponse({"detail": detail}, status_code=status_code)
    except Exception:  # pragma: no cover - defensive fallback
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": detail}, status_code=status_code)


def _text_response(status_code: int, detail: str) -> Any:
    try:
        from starlette.responses import PlainTextResponse
        return PlainTextResponse(detail, status_code=status_code)
    except Exception:  # pragma: no cover - defensive fallback
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(detail, status_code=status_code)


def _origin_allowed(origin: str | None, allowed_origins: set[str]) -> bool:
    if not allowed_origins or not origin:
        return True
    return origin.rstrip("/") in allowed_origins


def _install_on_server_module(server_module: ModuleType) -> bool:
    if os.environ.get(DISABLE_FLAG):
        return True
    if getattr(server_module, _PATCH_MARKER, False):
        return True

    token = os.environ.get(ACCESS_TOKEN_ENV, "").strip()
    if not token:
        setattr(server_module, _PATCH_MARKER, True)
        return True

    app = getattr(server_module, "app", None)
    if app is None or not hasattr(app, "middleware"):
        return False

    allowed_origins = _split_csv(os.environ.get(ALLOWED_ORIGINS_ENV))

    @app.middleware("http")
    async def ppt_runtime_security_middleware(request: Any, call_next: Any) -> Any:
        path = str(request.url.path)

        if request.method == "OPTIONS" or _is_exempt_path(path):
            return await call_next(request)

        origin = request.headers.get("origin")
        if not _origin_allowed(origin, allowed_origins):
            return _json_response(403, "Origin is not allowed by PPT_STUDIO_ALLOWED_ORIGINS.")

        supplied_token, token_from_query = _request_token(request)
        if not _safe_eq(supplied_token, token):
            response = _json_response(401, "Missing or invalid PPT Studio access token.") if path.startswith("/api") else _text_response(401, "Missing or invalid PPT Studio access token.")
            response.headers["WWW-Authenticate"] = "Bearer"
            return response

        response = await call_next(request)
        if token_from_query:
            response.set_cookie(
                COOKIE_NAME,
                token,
                httponly=True,
                samesite="lax",
                secure=os.environ.get("PPT_STUDIO_SECURE_COOKIE", "").lower() in {"1", "true", "yes"},
                max_age=int(os.environ.get("PPT_STUDIO_AUTH_COOKIE_MAX_AGE", "43200")),
            )
        return response

    setattr(server_module, _PATCH_MARKER, True)
    return True


def _candidate_server_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType):
            continue
        app = getattr(module, "app", None)
        if app is not None and hasattr(app, "middleware"):
            modules.append(module)
    return modules


def install_when_server_is_ready() -> None:
    """Install optional auth middleware once the FastAPI app module is loaded."""
    def worker() -> None:
        while not os.environ.get(DISABLE_FLAG):
            for module in _candidate_server_modules():
                if _install_on_server_module(module):
                    return
            time.sleep(0.1)

    threading.Thread(target=worker, name="ppt-runtime-security-patch", daemon=True).start()


install_when_server_is_ready()
