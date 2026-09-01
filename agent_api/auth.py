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

        # If no token is configured, pass through (development mode).
        if not self.enabled:
            return await call_next(request)

        token = self._extract_token(request)
        if not token or not secrets.compare_digest(token, self._expected_token):
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

        return await call_next(request)
