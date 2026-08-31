"""Agent API package — versioned, stable interface for Agent integration.

The Agent API wraps existing pipeline services into a unified, consistent
contract. It does NOT re-implement business logic — every endpoint delegates
to the same source-owned services used by the web UI.
"""

from agent_api.routes import router
from agent_api.errors import AgentAPIError, agent_error_handler

__all__ = ["router", "register_agent_error_handlers"]


def register_agent_error_handlers(app) -> None:
    """Register Agent API exception handlers on the FastAPI application.

    Only ``AgentAPIError`` (and subclasses) is registered so that existing
    web-UI routes keep their default FastAPI error handling unchanged.
    """
    app.add_exception_handler(AgentAPIError, agent_error_handler)
