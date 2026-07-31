"""Explicit routes for project background and subtitle settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from visual_settings_service import (
    VisualSettingsService,
    get_visual_settings_service,
)


router = APIRouter()


@router.get("/api/projects/{project_id}/steps/3/visual-settings")
def get_step3_visual_settings(
    project_id: str,
    db: Session = Depends(get_db),
    service: VisualSettingsService = Depends(
        get_visual_settings_service
    ),
) -> dict[str, Any]:
    return service.get(project_id, db)


@router.put("/api/projects/{project_id}/steps/3/visual-settings")
def update_step3_visual_settings(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    service: VisualSettingsService = Depends(
        get_visual_settings_service
    ),
) -> dict[str, Any]:
    return service.update_background(project_id, payload, db)


@router.get("/api/projects/{project_id}/subtitle-settings")
def get_project_subtitle_settings(
    project_id: str,
    db: Session = Depends(get_db),
    service: VisualSettingsService = Depends(
        get_visual_settings_service
    ),
) -> dict[str, Any]:
    return service.get_subtitles(project_id, db)


@router.put("/api/projects/{project_id}/subtitle-settings")
def update_project_subtitle_settings(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    service: VisualSettingsService = Depends(
        get_visual_settings_service
    ),
) -> dict[str, Any]:
    return service.update_subtitles(project_id, payload, db)
