"""Explicit FastAPI routes for the Step 3 image workflow."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
import image_workflow_service as service


router = APIRouter()


@router.get("/api/projects/{project_id}/steps/3/prompt-settings")
def get_step3_prompt_settings(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step3_prompt_settings(project_id, db)


@router.put("/api/projects/{project_id}/steps/3/prompt-settings")
def update_step3_prompt_settings(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step3_prompt_settings(
        project_id,
        payload,
        db,
    )


@router.get("/api/projects/{project_id}/steps/3/prompts")
def get_slide_prompts(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_slide_prompts(project_id, db)


@router.post("/api/projects/{project_id}/steps/3/generate")
def generate_slide_image(
    project_id: str,
    slide_id: str = Form(...),
    prompt: str = Form(...),
    preview: bool = Form(False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.generate_slide_image(
        project_id,
        slide_id,
        prompt,
        preview,
        db,
    )


@router.post("/api/projects/{project_id}/steps/3/upload")
def upload_slide_image(
    project_id: str,
    slide_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.upload_slide_image(
        project_id,
        slide_id,
        file,
        db,
    )


@router.get("/api/projects/{project_id}/slides/{slide_id}/image")
def get_slide_image_file(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    return service.get_slide_image_file(project_id, slide_id, db)


@router.get("/api/projects/{project_id}/slides/{slide_id}/candidate")
def get_slide_candidate_file(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    return service.get_slide_candidate_file(project_id, slide_id, db)


@router.post("/api/projects/{project_id}/steps/3/apply-candidate")
def apply_slide_candidate(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.apply_slide_candidate(project_id, payload, db)


@router.delete("/api/projects/{project_id}/steps/3/images")
def delete_all_slide_images(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.delete_all_slide_images(project_id, db)


@router.delete(
    "/api/projects/{project_id}/steps/3/images/{slide_id}"
)
def delete_slide_image(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.delete_slide_image(project_id, slide_id, db)


@router.get("/api/projects/{project_id}/steps/3/images")
def get_all_images(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_all_images(project_id, db)


@router.put("/api/projects/{project_id}/steps/3/image-order")
def update_step3_image_order(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step3_image_order(project_id, payload, db)


@router.post("/api/projects/{project_id}/steps/3/confirm")
def confirm_images(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.confirm_images(project_id, db)
