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
from fastapi.exceptions import RequestValidationError
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
        code = (details or {}).get("code", "CONFLICT")
        super().__init__(code, message, 409, details)


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
                "retryable": exc.code in {"RATE_LIMITED", "UPSTREAM_UNAVAILABLE"},
                "repair_actions": exc.details.get("repair_actions", []),
                "trace_id": getattr(request.state, "request_id", None),
            }
        },
    )


def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """框架层请求校验错误（422）统一为 Agent 信封（此前是 FastAPI 默认
    ``{"detail": [...]}`` 形状，接入指南第 31 行承认的边界欠账）。"""
    errors = [{key: value for key, value in item.items() if key != "input"}
              for item in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request payload",
                "details": {"errors": errors},
                "retryable": False,
                "repair_actions": [],
                "trace_id": getattr(request.state, "request_id", None),
            }
        },
    )


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Wrap FastAPI HTTPException into Agent API error format.

    信封字段与 agent_error_handler 对齐（details/retryable/repair_actions/
    trace_id），避免边界错误出现第二种形状。经由此处理器的是中间件/框架层
    错误——适配器自身的业务错误已在源头转为类型化 AgentAPIError。
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
                "details": {},
                "retryable": exc.status_code in {429, 502, 503, 504},
                "repair_actions": [],
                "trace_id": getattr(request.state, "request_id", None),
            }
        },
    )
