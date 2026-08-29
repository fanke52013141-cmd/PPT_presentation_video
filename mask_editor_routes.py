"""Explicit FastAPI routes for Step 5 Mask editing."""

from __future__ import annotations

from typing import Any, Dict, NoReturn, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
import mask_manifest_service as manifest_service
import mask_preview_service as preview_service


router = APIRouter()


from project_path_service import project_or_404 as _project_or_404


def _translate_error(exc: Exception) -> NoReturn:
    if isinstance(
        exc,
        (manifest_service.MaskManifestError, preview_service.MaskPreviewError),
    ):
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc
    raise exc


@router.post("/api/projects/{project_id}/steps/5/semantic-blocks")
def semantic_blocks_project(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return manifest_service.semantic_blocks_project(
            _project_or_404(db, project_id),
            payload,
        )
    except Exception as exc:
        _translate_error(exc)


@router.get("/api/projects/{project_id}/steps/5/result")
def get_step5_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return manifest_service.get_step5_result(
        _project_or_404(db, project_id)
    )


@router.post("/api/projects/{project_id}/steps/5/repair")
def repair_step5_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return manifest_service.repair_step5_result(
            _project_or_404(db, project_id)
        )
    except Exception as exc:
        _translate_error(exc)


@router.put("/api/projects/{project_id}/steps/5/draft")
def update_step5_draft(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return manifest_service.update_step5_draft(
        _project_or_404(db, project_id),
        payload,
    )


@router.post(
    "/api/projects/{project_id}/steps/5/slides/{slide_id}/preview"
)
def build_step5_mask_preview(
    project_id: str,
    slide_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    del payload
    try:
        return preview_service.build_step5_mask_preview(
            _project_or_404(db, project_id),
            slide_id,
        )
    except Exception as exc:
        _translate_error(exc)


@router.get(
    "/api/projects/{project_id}/slides/{slide_id}/mask-preview"
)
def get_step5_mask_preview(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        preview_path = preview_service.get_step5_mask_preview_path(
            _project_or_404(db, project_id),
            slide_id,
        )
    except Exception as exc:
        _translate_error(exc)
    return FileResponse(preview_path, media_type="image/png")


@router.put("/api/projects/{project_id}/steps/5/result")
def update_step5_result(
    project_id: str,
    payload: Dict[str, Any],
    build_assets: bool = Query(True),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return manifest_service.update_step5_result(
            _project_or_404(db, project_id),
            payload,
            build_assets=build_assets,
            db=db,
        )
    except Exception as exc:
        _translate_error(exc)
