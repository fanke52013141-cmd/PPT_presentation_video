"""Agent common adapters to source-owned business services."""

from __future__ import annotations

from typing import Any, Optional
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from database import Project
from account_context import get_current_account_id
from agent_api.errors import ProjectNotFoundError


def _idempotency_replay_or_raise(claim_result) -> Optional[dict[str, Any]]:
    """Return a replay dict (with header) or None; convert conflicts."""
    if claim_result.replay_response is not None:
        return JSONResponse(
            claim_result.replay_response,
            headers={"X-Agent-Idempotency-Replay": "true"},
        )
    return None


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
