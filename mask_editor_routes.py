"""Explicit FastAPI routes for Step 5 Mask editing."""

from __future__ import annotations

from typing import Any, Dict, NoReturn, Optional

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
import invalidation_service
import mask_manifest_service as manifest_service
import mask_preview_service as preview_service
from ai_mask_contracts import resolve_mask_source_master
from ai_mask_config import get_ai_mask_settings
from ai_mask_segmentation_backend import run_smart_selection


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
    project = _project_or_404(db, project_id)
    result = manifest_service.update_step5_draft(project, payload)
    if result.get("changed"):
        invalidation_service.mask_content_changed(project)
        db.commit()
    return result


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


def _validate_points(raw: Any, limit: int = 30) -> list[dict[str, int]]:
    """校验并归一化点提示为 [{"x": int, "y": int}]，过滤非法项。"""
    if not isinstance(raw, list):
        return []
    points: list[dict[str, int]] = []
    for item in raw[:limit]:
        if not isinstance(item, dict):
            continue
        try:
            x = int(round(float(item.get("x"))))
            y = int(round(float(item.get("y"))))
        except (TypeError, ValueError):
            continue
        if x >= 0 and y >= 0:
            points.append({"x": x, "y": y})
    return points


@router.post("/api/projects/{project_id}/steps/5/slides/{slide_id}/smart-selection")
def post_step5_smart_selection(
    project_id: str,
    slide_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = _project_or_404(db, project_id)
    master = Path(project.run_dir) / "slides" / slide_id / "visual_draft.png"
    image_path = resolve_mask_source_master(master)
    if not image_path or not Path(image_path).exists():
        raise HTTPException(status_code=404, detail="当前页原图不存在")

    positive = _validate_points((payload or {}).get("positive"))
    negative = _validate_points((payload or {}).get("negative"))
    if not positive:
        raise HTTPException(status_code=400, detail="至少需要一个有效的正点")

    result = run_smart_selection(Path(image_path), positive, negative, get_ai_mask_settings())
    if not result.get("success"):
        raise HTTPException(
            status_code=503, detail=result.get("reason") or "智能分割后端不可用"
        )
    return result

