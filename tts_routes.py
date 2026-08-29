"""Explicit FastAPI routes for Step 7 audio generation."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
import tts_service as service


router = APIRouter()


@router.post("/api/projects/{project_id}/steps/7/synthesize")
def synthesize_tts_resumable(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.synthesize_tts_resumable(project_id, db)


@router.post("/api/projects/{project_id}/steps/7/synthesize-async")
def create_tts_synthesis_job(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """提交后台合成任务并立即返回 job_id（审查 M-09 第二步）。"""
    return service.get_tts_async_service().create_job(db, project_id)


@router.get("/api/projects/{project_id}/steps/7/synthesize-jobs")
def list_tts_synthesis_jobs(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_tts_async_service().list_jobs(db, project_id)


@router.get("/api/projects/{project_id}/steps/7/synthesize-jobs/{job_id}")
def get_tts_synthesis_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_tts_async_service().get_job(db, project_id, job_id)


@router.get("/api/projects/{project_id}/steps/7/audio-status")
def get_tts_audio_status(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_tts_audio_status(project_id, db)


@router.get("/api/projects/{project_id}/slides/{slide_id}/audio")
def get_slide_audio_file(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    return service.get_slide_audio_file(project_id, slide_id, db)


@router.post("/api/projects/{project_id}/steps/7/confirm")
def confirm_tts_audio(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.confirm_tts_audio(project_id, db=db, payload=payload)
