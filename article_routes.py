"""Explicit FastAPI routes for Step 1 article generation and editing."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from database import Project, get_db
import article_service as service


router = APIRouter()


def _project_or_404(
    db: Session,
    project_id: str,
) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.get("/api/settings/article-generation")
def get_article_generation_settings() -> Dict[str, Any]:
    return service.get_article_generation_settings()


@router.put("/api/settings/article-generation")
def update_article_generation_settings(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return service.update_article_generation_settings(payload)


@router.post(
    "/api/projects/{project_id}/steps/1/generate-article"
)
def generate_article_from_topic(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return service.generate_article_from_topic(
        _project_or_404(db, project_id),
        payload,
    )


@router.post("/api/projects/{project_id}/steps/1/import")
def import_article(
    project_id: str,
    content: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return service.import_article(
        _project_or_404(db, project_id),
        content,
        db,
    )


@router.get("/api/projects/{project_id}/steps/1/result")
def get_step1_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return service.get_step1_result(
        _project_or_404(db, project_id)
    )


@router.put("/api/projects/{project_id}/steps/1/result")
def update_step1_result(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return service.update_step1_result(
        _project_or_404(db, project_id),
        payload,
        db,
    )
