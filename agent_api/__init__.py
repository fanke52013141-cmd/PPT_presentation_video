"""Agent API package — versioned, stable interface for Agent integration.

The Agent API wraps existing pipeline services into a unified, consistent
contract. It does NOT re-implement business logic — every endpoint delegates
to the same source-owned services used by the web UI.
"""

from agent_api.routes import router
from starlette.exceptions import HTTPException

from agent_api.errors import AgentAPIError, agent_error_handler, http_exception_handler

__all__ = ["router", "register_agent_error_handlers"]


def register_agent_error_handlers(app) -> None:
    """Register Agent API exception handlers on the FastAPI application.

    HTTPException handling is scoped by the handler itself to Agent API paths,
    so existing web-UI routes keep FastAPI's default error response shape.
    """
    app.add_exception_handler(AgentAPIError, agent_error_handler)
    # FastAPI registers its default handler under starlette's HTTPException key,
    # not the fastapi.HTTPException subclass, so the lookup must use the same key.
    previous_http_handler = app.exception_handlers.get(HTTPException)

    async def scoped_http_exception_handler(request, exc):
        if request.url.path.startswith("/api/agent/v1/"):
            return http_exception_handler(request, exc)
        if previous_http_handler is not None:
            return await previous_http_handler(request, exc)
        raise exc

    app.add_exception_handler(HTTPException, scoped_http_exception_handler)
