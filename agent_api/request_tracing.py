"""Request tracing middleware for the Agent API.

Generates (or propagates) an ``X-Request-ID`` for every Agent API call so
that end-to-end request chains can be correlated in logs and responses.
Also activates a structured trace context (``contextvars``) so any logger
with :class:`~agent_api.trace_context.TraceLoggingFilter` automatically
includes the trace ID.
"""

from __future__ import annotations

import logging
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agent_api.trace_context import TraceLoggingFilter, set_trace_id, clear_trace_id

logger = logging.getLogger("PPTStudio.AgentAPI")
# Attach the trace filter once so all agent logs include trace_id.
if not any(isinstance(f, TraceLoggingFilter) for f in logger.filters):
    logger.addFilter(TraceLoggingFilter())


class AgentRequestTracingMiddleware(BaseHTTPMiddleware):
    """Attach ``X-Request-ID`` to Agent API requests and responses.

    If the caller provides an ``X-Request-ID`` header, it is reused
    (truncated to 128 chars); otherwise a new UUID-based ID is generated.
    The ID is stored on ``request.state.request_id`` and activated in the
    structured trace context so downstream handlers and loggers can
    include it automatically.
    """

    def __init__(self, app, *, prefix: str = "/api/agent/v1") -> None:
        super().__init__(app)
        self._prefix = prefix

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        is_agent = path.startswith(self._prefix)

        trace_token = None
        request_id = None

        if is_agent:
            request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
            if len(request_id) > 128:
                request_id = request_id[:128]
            request.state.request_id = request_id
            # Activate structured trace context for this request.
            trace_token = set_trace_id(request_id)

        try:
            response: Response = await call_next(request)
        finally:
            if trace_token is not None:
                clear_trace_id(trace_token)

        if is_agent and request_id:
            response.headers["X-Request-ID"] = request_id
            # Re-activate context for the access log (cleared in finally above).
            with_trace = set_trace_id(request_id)
            try:
                logger.info(
                    "agent_api %s %s status=%s",
                    request.method,
                    path,
                    response.status_code,
                )
            finally:
                clear_trace_id(with_trace)

        return response
