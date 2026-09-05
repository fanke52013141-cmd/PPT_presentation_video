"""Agent API authentication middleware.

Provides bearer-token or API-key authentication for ``/api/agent/v1`` endpoints.
The expected token is read from the ``PPT_AGENT_API_KEY`` environment variable.
When no token is configured (the default for local/loopback use), the middleware
is a no-op and all requests pass through.
"""

from __future__ import annotations

import json
import os
import secrets
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

AGENT_API_KEY_ENV = "PPT_AGENT_API_KEY"
_HEADER_AUTH = "authorization"
_HEADER_API_KEY = "x-api-key"
_HEADER_AGENT_TOKEN = "x-agent-token"

# Paths under the agent prefix that remain public even when auth is enabled
# (e.g. health/ping for connectivity checks).
_PUBLIC_SUFFIXES = ("/ping", "/health")


class AgentAuthMiddleware(BaseHTTPMiddleware):
    """Enforce bearer-token or API-key authentication on the Agent API.

    Token resolution order:
    1. ``Authorization: Bearer <token>``
    2. ``X-API-Key: <token>``
    3. ``X-Agent-Token: <token>``
    4. ``?token=<token>`` query parameter (GET only)

    When ``PPT_AGENT_API_KEY`` is unset or empty, the middleware passes all
    requests through (loopback / development default).
    """

    def __init__(self, app, *, prefix: str = "/api/agent/v1") -> None:
        super().__init__(app)
        self._prefix = prefix
        self._expected_token = os.environ.get(AGENT_API_KEY_ENV, "").strip()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self._expected_token)

    def _extract_token(self, request: Request) -> Optional[str]:
        # Authorization: Bearer <token>
        authorization = request.headers.get(_HEADER_AUTH, "")
        if authorization.startswith("Bearer "):
            return authorization[7:].strip()
        # X-API-Key
        api_key = request.headers.get(_HEADER_API_KEY)
        if api_key:
            return api_key.strip()
        # X-Agent-Token
        agent_token = request.headers.get(_HEADER_AGENT_TOKEN)
        if agent_token:
            return agent_token.strip()
        # Query-string token (GET only)
        if request.method.upper() == "GET":
            query_token = request.query_params.get("token")
            if query_token:
                return query_token.strip()
        return None

    # ------------------------------------------------------------------
    # middleware entry-point
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path

        # Only protect Agent API paths.
        if not path.startswith(self._prefix):
            return await call_next(request)

        # Allow public sub-endpoints (ping/health).
        if any(path.endswith(suffix) for suffix in _PUBLIC_SUFFIXES):
            return await call_next(request)

        token = self._extract_token(request)
        account_id = "default"
        authenticated = False
        scopes: set[str] = set()
        if token and self._expected_token and secrets.compare_digest(token, self._expected_token):
            authenticated = True
            # The legacy process token remains a deliberately local default
            # account token until it is replaced by a per-account token.
        elif token:
            try:
                from database import SessionLocal
                from account_service import authenticate_agent_token
                db = SessionLocal()
                try:
                    account_token = authenticate_agent_token(db, token)
                    if account_token is not None:
                        account_id = account_token.account_id
                        scopes = set(filter(None, account_token.scopes.split(",")))
                        authenticated = True
                finally:
                    db.close()
            except Exception:
                # Authentication must fail closed when token storage is not
                # available; do not turn a database error into anonymous access.
                authenticated = False

        # If neither the legacy key nor a stored account token is configured,
        # preserve the existing loopback development behavior. A caller may
        # select an account explicitly in local development with the header.
        if not authenticated and self.enabled:
            body = json.dumps(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing or invalid API key.",
                    }
                },
                ensure_ascii=False,
            )
            return Response(
                content=body,
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not authenticated and not self.enabled:
            account_id = request.headers.get("x-ppt-account-id", "default").strip() or "default"
        if authenticated and scopes:
            required_scope = "project:read"
            if request.method.upper() != "GET":
                required_scope = "project:write"
            if "/runs" in path or path.endswith("/render"):
                required_scope = "pipeline:write"
            if "/artifacts" in path and request.method.upper() == "GET":
                required_scope = "artifact:read"
            if required_scope not in scopes:
                return Response(
                    content=json.dumps({"error": {"code": "FORBIDDEN", "message": f"Missing scope: {required_scope}"}}, ensure_ascii=False),
                    status_code=403,
                    media_type="application/json",
                )
        from account_context import set_current_account_id, reset_current_account_id
        context_token = set_current_account_id(account_id)
        request.state.account_id = account_id
        request.state.agent_scopes = scopes
        request.state.agent_authenticated = authenticated
        try:
            return await call_next(request)
        finally:
            reset_current_account_id(context_token)
