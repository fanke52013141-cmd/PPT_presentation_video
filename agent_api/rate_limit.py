"""Lightweight sliding-window rate limiter for the Agent API."""

from __future__ import annotations

import json
import hashlib
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class AgentRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter scoped to ``/api/agent/v1``.

    Each client is identified by ``X-Agent-Token`` (or the request token
    parameter) falling back to the client IP address.  When the caller
    exceeds *max_requests* inside *window_seconds* a ``429 Too Many
    Requests`` JSON response is returned with ``Retry-After`` and
    ``X-RateLimit-*`` headers.

    By default the limiter uses an in-memory ``defaultdict``. Pass
    *persistent_store* (a :class:`~agent_api.rate_limit_store.RateLimitStore`)
    to persist hit timestamps to SQLite so limits survive restarts.
    """

    def __init__(
        self,
        app,
        *,
        prefix: str = "/api/agent/v1",
        max_requests: int = 120,
        window_seconds: int = 60,
        persistent_store: Optional[object] = None,
        trust_proxy_headers: bool = False,
    ) -> None:
        super().__init__(app)
        self._prefix = prefix
        self._max = max_requests
        self._window = window_seconds
        self._lock = Lock()
        # client_key -> list[int]  (request timestamps within window)
        self._hits: dict[str, list[float]] = defaultdict(list)
        # Optional SQLite-backed store for persistence across restarts.
        self._store = persistent_store
        self._trust_proxy_headers = trust_proxy_headers

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _client_key(self, request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        if not token:
            token = request.headers.get("x-api-key") or request.headers.get("x-agent-token")
        if not token:
            token = request.query_params.get("token")
        if token:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
            return f"token:{digest}"
        forwarded = request.headers.get("x-forwarded-for", "") if self._trust_proxy_headers else ""
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"

    def _check_and_record(self, key: str) -> tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds)."""
        # Delegate to the persistent store when configured.
        if self._store is not None:
            return self._store.record_and_check(key, self._max, self._window)

        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            hits = self._hits[key]
            # Trim expired entries.
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if len(hits) >= self._max:
                retry_after = int(hits[0] + self._window - now) + 1
                return False, 0, max(retry_after, 1)
            hits.append(now)
            remaining = self._max - len(hits)
            return True, remaining, 0

    # ------------------------------------------------------------------
    # middleware entry-point
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if not path.startswith(self._prefix):
            return await call_next(request)

        key = self._client_key(request)
        allowed, remaining, retry_after = self._check_and_record(key)

        if not allowed:
            body = json.dumps(
                {
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Rate limit exceeded. Please retry later.",
                        "retry_after_seconds": retry_after,
                    }
                },
                ensure_ascii=False,
            )
            return Response(
                content=body,
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self._max),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._max)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
