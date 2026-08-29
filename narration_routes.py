"""Explicit FastAPI routes for Step 6 narration."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
import narration_service as service


router = APIRouter()


@router.post("/api/projects/{project_id}/steps/6/init")
def init_step6_narration(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.init_step6_narration(project_id, db)


@router.get("/api/projects/{project_id}/steps/6/result")
def get_step6_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step6_result(project_id, db)


@router.post("/api/projects/{project_id}/steps/6/repair")
def repair_step6_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.repair_step6_result(project_id, db)


@router.get("/api/settings/narration-annotation")
def get_narration_annotation_settings() -> dict[str, Any]:
    return service.get_narration_annotation_settings()


@router.put("/api/settings/narration-annotation")
def update_narration_annotation_settings(
    payload: Dict[str, Any],
) -> dict[str, Any]:
    return service.update_narration_annotation_settings(payload)


@router.post("/api/projects/{project_id}/steps/6/annotate")
def annotate_step6_narration(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.annotate_step6_narration(
        project_id,
        db=db,
        payload=payload,
    )


@router.put("/api/projects/{project_id}/steps/6/result")
def update_step6_result(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step6_result(project_id, payload, db)
