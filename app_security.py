"""Explicit FastAPI access control for non-local PPT Studio deployments."""

from __future__ import annotations

import os
import secrets
from typing import Any, Mapping
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse


ACCESS_TOKEN_ENV = "PPT_STUDIO_ACCESS_TOKEN"
ALLOWED_ORIGINS_ENV = "PPT_STUDIO_ALLOWED_ORIGINS"
COOKIE_NAME = "ppt_studio_access_token"


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str | None) -> set[str]:
    return {item.strip().rstrip("/") for item in str(value or "").split(",") if item.strip()}


def _safe_eq(left: str | None, right: str | None) -> bool:
    return bool(left and right) and secrets.compare_digest(str(left), str(right))


def _request_token(request: Any) -> tuple[str, bool]:
    query_token = request.query_params.get("access_token") or request.query_params.get("token")
    if query_token:
        return str(query_token), True
    authorization = str(request.headers.get("authorization") or "")
    bearer = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    header_token = request.headers.get("x-app-token") or bearer
    if header_token:
        return str(header_token), False
    return str(request.cookies.get(COOKIE_NAME) or ""), False


def install_access_control(app: FastAPI, environ: Mapping[str, str] | None = None) -> bool:
    """Install token/origin middleware once; return whether auth is enabled."""
    env = os.environ if environ is None else environ
    if getattr(app.state, "ppt_access_control_installed", False):
        return bool(getattr(app.state, "ppt_access_control_enabled", False))
    token = str(env.get(ACCESS_TOKEN_ENV, "")).strip()
    app.state.ppt_access_control_installed = True
    app.state.ppt_access_control_enabled = bool(token)
    if not token:
        return False
    allowed_origins = _split_csv(env.get(ALLOWED_ORIGINS_ENV))
    secure_cookie = _enabled(env.get("PPT_STUDIO_SECURE_COOKIE"))
    cookie_max_age = int(env.get("PPT_STUDIO_AUTH_COOKIE_MAX_AGE", "43200"))
    exempt_paths = _split_csv(env.get("PPT_STUDIO_AUTH_EXEMPT_PATHS")) | {"/favicon.ico"}

    @app.middleware("http")
    async def ppt_access_control(request: Any, call_next: Any) -> Any:
        path = str(request.url.path)
        if request.method == "OPTIONS" or path in exempt_paths:
            return await call_next(request)
        origin = request.headers.get("origin")
        if allowed_origins and origin and origin.rstrip("/") not in allowed_origins:
            return JSONResponse({"detail": "Origin is not allowed by PPT_STUDIO_ALLOWED_ORIGINS."}, status_code=403)
        supplied_token, token_from_query = _request_token(request)
        if not _safe_eq(supplied_token, token):
            response = (
                JSONResponse({"detail": "Missing or invalid PPT Studio access token."}, status_code=401)
                if path.startswith("/api")
                else PlainTextResponse("Missing or invalid PPT Studio access token.", status_code=401)
            )
            response.headers["WWW-Authenticate"] = "Bearer"
            return response
        if token_from_query:
            if request.method not in {"GET", "HEAD"}:
                return JSONResponse(
                    {"detail": "Query-string access tokens are only accepted for GET or HEAD requests."},
                    status_code=400,
                )
            clean_query = urlencode(
                [
                    (key, value)
                    for key, value in request.query_params.multi_items()
                    if key not in {"access_token", "token"}
                ],
                doseq=True,
            )
            clean_url = request.url.replace(query=clean_query)
            response = RedirectResponse(str(clean_url), status_code=303)
            response.set_cookie(
                COOKIE_NAME,
                token,
                httponly=True,
                samesite="lax",
                secure=secure_cookie,
                max_age=cookie_max_age,
            )
            return response
        response = await call_next(request)
        return response

    return True
