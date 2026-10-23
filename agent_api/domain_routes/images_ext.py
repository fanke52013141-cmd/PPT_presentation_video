"""Agent image adapters to the source-owned Step 3 image workflow service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from agent_contract.domains.images import ImageGenerateRequest
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest
from database import get_db

import image_workflow_service as service

router = APIRouter()


@router.get("/projects/{project_id}/image-prompt-settings")
def agent_get_image_prompt_settings(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_step3_prompt_settings(project_id, db)


@router.put("/projects/{project_id}/image-prompt-settings")
def agent_update_image_prompt_settings(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step3_prompt_settings(project_id, payload.payload, db)


@router.get("/projects/{project_id}/image-prompts")
def agent_get_image_prompts(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_slide_prompts(project_id, db)


@router.post("/projects/{project_id}/images/generate")
def agent_generate_image(
    project_id: str,
    payload: ImageGenerateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from agent_api.errors import ConflictError
    from agent_api.fingerprints import request_fingerprint
    from agent_api.domain_routes.common import _idempotency_replay_or_raise
    from agent_idempotency_service import get_idempotency_service, IdempotencyConflictError

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "image.generate",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "image.generate",
                payload.model_dump(mode="json"),
                project_id=project_id,
            ),
        )
    except IdempotencyConflictError as exc:
        raise ConflictError(str(exc), details=exc.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        result = service.generate_slide_image(
            project_id,
            payload.slide_id,
            payload.prompt,
            payload.preview,
            db,
            disposition=payload.disposition,
            expected_version=payload.expected_version or None,
        )
        idempotency.finalize(claim.record_pk, True, result)
        return result
    except Exception:
        idempotency.finalize(claim.record_pk, False, None)
        raise


@router.post("/projects/{project_id}/images/upload")
def agent_upload_image(
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


@router.get("/projects/{project_id}/images/{slide_id}/change-preview")
def agent_get_image_change_preview(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_slide_image_change_preview(project_id, slide_id, db)


@router.get("/projects/{project_id}/images/{slide_id}/recovery")
def agent_list_image_recovery(
    project_id: str, slide_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.list_slide_image_recovery(project_id, slide_id, db)


@router.get("/projects/{project_id}/images/{slide_id}/recovery/{archive_id}/overlay")
def agent_image_recovery_overlay(
    project_id: str, slide_id: str, archive_id: str, db: Session = Depends(get_db)
) -> Response:
    return service.image_recovery_overlay(project_id, slide_id, archive_id, db)


@router.post("/projects/{project_id}/images/{slide_id}/reuse-geometry")
def agent_reuse_image_geometry(
    project_id: str,
    slide_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.reuse_slide_image_geometry(project_id, slide_id, payload.payload, db)


@router.post("/projects/{project_id}/images/apply-candidate")
def agent_apply_image_candidate(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.apply_slide_candidate(project_id, payload.payload, db)


@router.get("/projects/{project_id}/images/{slide_id}/candidate")
def agent_get_image_candidate(
    project_id: str, slide_id: str, db: Session = Depends(get_db)
) -> FileResponse:
    return service.get_slide_candidate_file(project_id, slide_id, db)


@router.get("/projects/{project_id}/images/download")
def agent_download_all_images(project_id: str, db: Session = Depends(get_db)):
    return service.download_all_slide_images(project_id, db)


@router.delete("/projects/{project_id}/images")
def agent_delete_all_images(
    project_id: str,
    payload: OptionalFreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.delete_all_slide_images(project_id, db, payload.payload or {})


@router.delete("/projects/{project_id}/images/{slide_id}")
def agent_delete_image(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
    disposition: str = Query("keep"),
    expected_version: str = Query(""),
) -> dict[str, Any]:
    return service.delete_slide_image(
        project_id, slide_id, db,
        disposition=disposition, expected_version=expected_version or None,
    )


@router.get("/projects/{project_id}/images")
def agent_list_images(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_all_images(project_id, db)


@router.put("/projects/{project_id}/image-order")
def agent_update_image_order(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step3_image_order(project_id, payload.payload, db)


@router.post("/projects/{project_id}/images/confirm")
def agent_confirm_images(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.confirm_images(project_id, db)
