"""Explicit FastAPI routes for local one-click generation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import Project, get_db
from one_click_orchestrator import get_one_click_status, start_one_click


router = APIRouter()


def _project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("/api/projects/{project_id}/one-click-generate")
def start_one_click_route(
    project_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    try:
        return start_one_click(project, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/projects/{project_id}/one-click-generate/status")
def get_one_click_status_route(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_one_click_status(_project_or_404(db, project_id))
