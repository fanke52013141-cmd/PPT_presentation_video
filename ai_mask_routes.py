"""Explicit FastAPI routes for AI Mask configuration and annotation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ai_mask_config import ai_mask_config_payload, save_ai_mask_settings
from ai_mask_service import get_ai_mask_task_service
from database import Project, get_db


router = APIRouter()


@router.get("/api/settings/ai-mask")
def get_ai_mask_settings_route() -> dict[str, Any]:
    return ai_mask_config_payload()


@router.put("/api/settings/ai-mask")
def put_ai_mask_settings_route(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "settings": save_ai_mask_settings(payload),
    }


@router.post("/api/projects/{project_id}/steps/5/ai-mask/annotate")
def annotate_ai_mask_route(
    project_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    settings = (
        payload.get("settings")
        if isinstance(payload, dict) and isinstance(payload.get("settings"), dict)
        else {}
    )
    return get_ai_mask_task_service().annotate_project(project, settings)
