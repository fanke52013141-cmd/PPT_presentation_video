"""Agent API package — versioned, stable interface for Agent integration.

The Agent API wraps existing pipeline services into a unified, consistent
contract. It does NOT re-implement business logic — every endpoint delegates
to the same source-owned services used by the web UI.
"""

from agent_api.routes import router
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from agent_api.errors import (
    AgentAPIError,
    agent_error_handler,
    http_exception_handler,
    request_validation_error_handler,
)

__all__ = ["router", "register_agent_error_handlers"]


def register_agent_error_handlers(app) -> None:
    """Register Agent API exception handlers on the FastAPI application.

    Handler scoping lives inside each wrapper: only ``/api/agent/v1/`` paths
    get the unified Agent error envelope, so existing web-UI routes keep
    FastAPI's default error response shape.
    """
    app.add_exception_handler(AgentAPIError, agent_error_handler)

    def _scoped(agent_handler, exc_class):
        # FastAPI registers its default HTTPException handler under
        # starlette's HTTPException key, not the fastapi.HTTPException
        # subclass, so the previous-handler lookup must use the same key.
        previous = app.exception_handlers.get(exc_class)

        async def scoped_handler(request, exc):
            if request.url.path.startswith("/api/agent/v1/"):
                return agent_handler(request, exc)
            if previous is not None:
                return await previous(request, exc)
            raise exc

        app.add_exception_handler(exc_class, scoped_handler)

    _scoped(http_exception_handler, HTTPException)
    _scoped(request_validation_error_handler, RequestValidationError)
