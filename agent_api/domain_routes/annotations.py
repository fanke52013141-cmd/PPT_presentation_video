"""Agent annotation adapters to the source-owned annotation service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from agent_contract.domains.annotations import AnnotationPromptsRequest
from agent_contract.domains.freeform import FreeFormRequest
from annotation_service import get_annotation_service
from database import get_db

router = APIRouter()


@router.get("/projects/{project_id}/annotations")
def agent_get_annotation_summary(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.get_summary(db, project_id)


@router.put("/projects/{project_id}/annotations/settings")
def agent_update_annotation_settings(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    result = service.update_settings(db, project_id, payload.payload)
    db.commit()
    return result


@router.get("/projects/{project_id}/annotations/slides/{slide_id}")
def agent_get_annotation_slide(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.get_slide(db, project_id, slide_id)


@router.patch("/projects/{project_id}/annotations/slides/{slide_id}")
def agent_patch_annotation_slide(
    project_id: str,
    slide_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    result = service.patch_slide(db, project_id, slide_id, payload.payload)
    db.commit()
    return result


@router.get("/projects/{project_id}/annotations/slides/{slide_id}/text-layout")
def agent_get_annotation_text_layout(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.get_text_layout(db, project_id, slide_id)


@router.patch("/projects/{project_id}/annotations/slides/{slide_id}/text-layout")
def agent_patch_annotation_text_layout(
    project_id: str,
    slide_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.patch_text_layout(db, project_id, slide_id, payload.payload)


@router.get("/projects/{project_id}/annotations/prompts")
def agent_get_annotation_prompts(
    project_id: str,
    db: Session = Depends(get_db),
    slide_id: str | None = None,
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.get_prompts(db, project_id, slide_id)


@router.put("/projects/{project_id}/annotations/prompts")
def agent_put_annotation_prompts(
    project_id: str,
    payload: AnnotationPromptsRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.put_prompts(db, project_id, payload.payload)


@router.post("/projects/{project_id}/annotations/slides/{slide_id}/prepare")
def agent_prepare_annotation_slide(
    project_id: str,
    slide_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.prepare_slide(db, project_id, slide_id, payload.payload)


@router.post("/projects/{project_id}/annotations/slides/{slide_id}/confirm")
def agent_confirm_annotation_slide(
    project_id: str,
    slide_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    result = service.confirm_slide(db, project_id, slide_id, payload.payload)
    db.commit()
    return result


@router.post("/projects/{project_id}/annotations/jobs")
def agent_submit_annotation_job(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.submit_job(db, project_id, payload.payload)


@router.get("/projects/{project_id}/annotations/jobs/{job_id}")
def agent_get_annotation_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.get_job(db, project_id, job_id)


@router.post("/projects/{project_id}/annotations/jobs/{job_id}/cancel")
def agent_cancel_annotation_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.cancel_job(db, project_id, job_id)


@router.post("/projects/{project_id}/annotations/slides/{slide_id}/export-preview")
def agent_export_annotation_preview(
    project_id: str,
    slide_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = get_annotation_service()
    return service.export_preview(db, project_id, slide_id, payload.payload)


@router.get("/projects/{project_id}/annotations/slides/{slide_id}/scene-assets/{asset}")
def agent_get_annotation_scene_asset(
    project_id: str,
    slide_id: str,
    asset: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    service = get_annotation_service()
    return FileResponse(
        service.preview_scene_asset(db, project_id, slide_id, asset), media_type="image/png"
    )


@router.get("/projects/{project_id}/annotations/slides/{slide_id}/editor-inks/{annotation_id}/{stroke_index}")
def agent_get_annotation_editor_ink(
    project_id: str,
    slide_id: str,
    annotation_id: str,
    stroke_index: int,
    revision: int,
    db: Session = Depends(get_db),
) -> Response:
    service = get_annotation_service()
    return Response(
        service.annotation_editor_ink(db, project_id, slide_id, annotation_id, stroke_index, revision),
        media_type="image/png",
        headers={"Cache-Control": "private, no-cache"},
    )


@router.get("/projects/{project_id}/annotations/slides/{slide_id}/inks/{build_id}/{annotation_id}/{stroke_index}/{frame_index}")
def agent_get_annotation_ink(
    project_id: str,
    slide_id: str,
    build_id: str,
    annotation_id: str,
    stroke_index: int,
    frame_index: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    service = get_annotation_service()
    path = service.annotation_asset(
        db, project_id, slide_id, build_id, annotation_id, stroke_index, frame_index
    )
    return FileResponse(path, media_type="image/png")


@router.get("/projects/{project_id}/annotations/slides/{slide_id}/export-previews/{token}")
def agent_download_annotation_preview(
    project_id: str,
    slide_id: str,
    token: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    import re

    service = get_annotation_service()
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise HTTPException(404, "预览不存在")
    source = service.preview_scene_asset(db, project_id, slide_id, "visual_draft.png").parent
    path = source / "preview_exports" / (token + ".mp4")
    if not path.is_file():
        raise HTTPException(404, "预览不存在")
    return FileResponse(path, media_type="video/mp4", filename=f"{slide_id}_annotation_preview.mp4")
