"""Agent common adapters to source-owned business services."""

from __future__ import annotations

from typing import Any, Optional
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import Project
from account_context import get_current_account_id
from agent_api.errors import AgentAPIError, ProjectNotFoundError


def _idempotency_replay_or_raise(claim_result) -> Optional[dict[str, Any]]:
    """Return a replay dict (with header) or None; convert conflicts."""
    if claim_result.replay_response is not None:
        return JSONResponse(
            claim_result.replay_response,
            headers={"X-Agent-Idempotency-Replay": "true"},
        )
    return None


def finalize_claim_failure(claim, exc: BaseException) -> None:
    """Terminalize an idempotency claim after a failed execution.

    4xx contract failures (validation, resource-not-found, CAS conflict) are
    raised before any business side effect, so the exact same request may
    re-claim the key (``failed_retryable``). Anything else keeps the
    conservative burned-key semantics: the client must verify project state
    and retry with a NEW key (OPERATION_OUTCOME_UNKNOWN).
    """
    from agent_idempotency_service import get_idempotency_service

    status_code = getattr(exc, "status_code", None)
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
    retryable = isinstance(status_code, int) and 400 <= status_code < 500
    get_idempotency_service().finalize(claim.record_pk, False, None, retryable=retryable)


# 直接 HTTP 路由的业务错误必须给出机器可读错误码（审查 2026-10-24 P1-4）：
# 历史实现把 Web 翻译器的 HTTPException 统一退化为 code=HTTP_ERROR，
# 外部 Agent 只能解析 message 文本，无法编程化恢复。
_HTTP_ERROR_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "UPSTREAM_UNAVAILABLE",
}

# Web 层 dict detail 里的语义码 → Agent 错误码
_DICT_CODE_ALIASES = {
    "revision_conflict": "REVISION_CONFLICT",
}


def agent_http_error(status_code: int, detail: Any) -> AgentAPIError:
    """Build the typed AgentAPIError for a would-be HTTPException."""
    status = int(status_code)
    if isinstance(detail, dict):
        # Web 层的 HTTPException 允许 dict detail（如 annotation_service 的
        # {"code": "revision_conflict", "current_revision": N}）。直接 str() 会
        # 把 repr 塞进 message，外部 Agent 无法按码处理——拆开映射。
        raw_code = str(detail.get("code") or "").strip()
        code = _DICT_CODE_ALIASES.get(raw_code.lower()) or (
            raw_code.upper().replace("-", "_") if raw_code
            else _HTTP_ERROR_CODES.get(status, "HTTP_ERROR")
        )
        message = str(detail.get("message") or raw_code or code)
        rest = {key: value for key, value in detail.items() if key not in {"code", "message"}}
        return AgentAPIError(code, message, status, details=rest)
    return AgentAPIError(_HTTP_ERROR_CODES.get(status, "HTTP_ERROR"), str(detail), status)


def raise_typed_http_error(exc: BaseException) -> None:
    """Re-raise a caught HTTPException with its machine-readable Agent code."""
    if isinstance(exc, AgentAPIError):
        raise exc
    if isinstance(exc, HTTPException):
        raise agent_http_error(exc.status_code, exc.detail) from exc
    raise exc


def _resolve_project(db: Session, project_id: str) -> Project:
    """Find a project or raise ProjectNotFoundError."""
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.account_id == get_current_account_id(),
        )
        .first()
    )
    if not project:
        raise ProjectNotFoundError(project_id)
    return project
