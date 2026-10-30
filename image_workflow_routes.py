"""Explicit FastAPI routes for the Step 3 image workflow."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from database import get_db
import image_workflow_service as service
from image_region_repair import ImageCandidateApplyPayload


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
    disposition: str = Form("keep"),
    expected_version: str = Form(""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.generate_slide_image(
        project_id,
        slide_id,
        prompt,
        preview,
        db,
        disposition=disposition,
        expected_version=expected_version or None,
    )


@router.post("/api/projects/{project_id}/steps/3/upload")
def upload_slide_image(
    project_id: str,
    slide_id: str = Form(...),
    file: UploadFile = File(...),
    disposition: str = Form("keep"),
    expected_version: str = Form(""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.upload_slide_image(
        project_id,
        slide_id,
        file,
        db,
        disposition=disposition,
        expected_version=expected_version or None,
    )


@router.get("/api/projects/{project_id}/steps/3/images/{slide_id}/change-preview")
def get_slide_image_change_preview(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_slide_image_change_preview(project_id, slide_id, db)


@router.get("/api/projects/{project_id}/steps/3/images/{slide_id}/recovery")
def list_slide_image_recovery(
    project_id: str, slide_id: str, db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.list_slide_image_recovery(project_id, slide_id, db)


@router.get("/api/projects/{project_id}/steps/3/images/{slide_id}/recovery/{archive_id}/overlay")
def image_recovery_overlay(
    project_id: str, slide_id: str, archive_id: str, db: Session = Depends(get_db),
) -> Response:
    return service.image_recovery_overlay(project_id, slide_id, archive_id, db)


@router.post("/api/projects/{project_id}/steps/3/images/{slide_id}/reuse-geometry")
def reuse_slide_image_geometry(
    project_id: str, slide_id: str, payload: dict[str, Any], db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.reuse_slide_image_geometry(project_id, slide_id, payload, db)


@router.get("/api/projects/{project_id}/slides/{slide_id}/image")
def get_slide_image_file(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    return service.get_slide_image_file(project_id, slide_id, db)


@router.get("/api/projects/{project_id}/steps/3/images/download")
def download_all_slide_images(
    project_id: str,
    db: Session = Depends(get_db),
):
    return service.download_all_slide_images(project_id, db)


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
    payload: ImageCandidateApplyPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.apply_slide_candidate(project_id, payload.model_dump(exclude_unset=True), db)


@router.delete("/api/projects/{project_id}/steps/3/images")
def delete_all_slide_images(
    project_id: str,
    payload: dict[str, Any] | None = Body(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.delete_all_slide_images(project_id, db, payload or {})


@router.delete(
    "/api/projects/{project_id}/steps/3/images/{slide_id}"
)
def delete_slide_image(
    project_id: str,
    slide_id: str,
    disposition: str = Query("keep"),
    expected_version: str = Query(""),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.delete_slide_image(
        project_id, slide_id, db,
        disposition=disposition, expected_version=expected_version or None,
    )


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
