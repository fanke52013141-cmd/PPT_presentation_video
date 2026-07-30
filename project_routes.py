"""Explicit FastAPI routes for project lifecycle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from project_service import (
    AiModeUpdate,
    ProjectCreate,
    ProjectService,
    get_project_service,
)


router = APIRouter()


@router.post("/api/projects")
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.create(payload, db)


@router.get("/api/projects")
def list_projects(
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> list[dict[str, Any]]:
    return service.list(db)


@router.get("/api/projects/{project_id}")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.get(project_id, db)


@router.get("/api/projects/{project_id}/ai-mode")
def get_project_ai_mode(
    project_id: str,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, str]:
    return service.get_ai_mode(project_id, db)


@router.put("/api/projects/{project_id}/ai-mode")
def update_project_ai_mode(
    project_id: str,
    payload: AiModeUpdate,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.update_ai_mode(project_id, payload, db)


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.delete(project_id, db)
