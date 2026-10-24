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
