"""Unified error handling for the Agent API.

All Agent API errors return a consistent JSON structure:
{
  "error": {
    "code": "NOT_FOUND" | "VALIDATION_ERROR" | "CONFLICT" | ...,
    "message": "Human-readable description",
    "details": {...}  # optional
  }
}
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Any, Optional


class AgentAPIError(Exception):
    """Base error for Agent API operations."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ProjectNotFoundError(AgentAPIError):
    def __init__(self, project_id: str) -> None:
        super().__init__("PROJECT_NOT_FOUND", f"Project '{project_id}' not found", 404)


class ValidationFailedError(AgentAPIError):
    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("VALIDATION_ERROR", message, 422, details)


class ConflictError(AgentAPIError):
    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("CONFLICT", message, 409, details)


class OperationFailedError(AgentAPIError):
    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__("OPERATION_FAILED", message, 500, details)


def agent_error_handler(request: Request, exc: AgentAPIError) -> JSONResponse:
    """FastAPI exception handler for AgentAPIError."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Wrap FastAPI HTTPException into Agent API error format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "details": {},
            }
        },
    )
