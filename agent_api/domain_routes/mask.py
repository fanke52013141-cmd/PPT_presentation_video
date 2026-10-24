"""Agent mask adapters: AI Mask configuration and the Step 5 mask editor."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from agent_contract.domains.mask import (
    MaskAnnotateRequest,
    MaskResultUpdateRequest,
)
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest
from database import Project, get_db
from account_context import get_current_account_id
from ai_mask_config import ai_mask_config_payload, save_ai_mask_settings

import invalidation_service
import mask_manifest_service as manifest_service
import mask_preview_service as preview_service

from project_path_service import project_or_404 as _project_or_404

router = APIRouter()


def _translate_error(exc: Exception) -> None:
    from agent_api.domain_routes.common import agent_http_error

    if isinstance(
        exc,
        (manifest_service.MaskManifestError, preview_service.MaskPreviewError),
    ):
        raise agent_http_error(exc.status_code, exc.detail) from exc
    raise exc


@router.get("/ai-mask/settings")
def agent_get_ai_mask_settings() -> dict[str, Any]:
    return ai_mask_config_payload()


@router.put("/ai-mask/settings")
def agent_update_ai_mask_settings(payload: FreeFormRequest) -> dict[str, Any]:
    return {"success": True, "settings": save_ai_mask_settings(payload.payload)}


@router.post("/projects/{project_id}/mask/annotate")
def agent_annotate_ai_mask(
    project_id: str,
    payload: MaskAnnotateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from ai_mask_service import get_ai_mask_task_service

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.account_id == get_current_account_id())
        .first()
    )
    if not project:
        from agent_api.errors import ProjectNotFoundError
        raise ProjectNotFoundError(project_id)
    try:
        return get_ai_mask_task_service().annotate_project(
            project, payload.settings or {}, payload.slide_ids
        )
    except ValueError as exc:
        from agent_api.domain_routes.common import agent_http_error
        raise agent_http_error(400, str(exc)) from exc
    except RuntimeError as exc:
        # 引擎启动时读取 reveal_manifest.json（image.confirm 产物），缺失说明
        # Step 3 尚未确认——前置条件语义（真实供应商演练 2026-10-24：此前
        # RuntimeError 直接 500）。
        if "reveal_manifest" in str(exc):
            from agent_api.domain_routes.common import agent_http_error
            raise agent_http_error(
                409, "请先完成 Step 3 图片确认以生成 Reveal manifest，再执行 AI Mask 标注"
            ) from exc
        raise


@router.post("/projects/{project_id}/mask/semantic-blocks")
def agent_mask_semantic_blocks(
    project_id: str,
    payload: OptionalFreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return manifest_service.semantic_blocks_project(_project_or_404(db, project_id), payload.payload)
    except Exception as exc:
        _translate_error(exc)


@router.get("/projects/{project_id}/mask")
def agent_get_mask_result(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return manifest_service.get_step5_result(_project_or_404(db, project_id))


@router.post("/projects/{project_id}/mask/repair")
def agent_repair_mask_result(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return manifest_service.repair_step5_result(_project_or_404(db, project_id))
    except Exception as exc:
        _translate_error(exc)


@router.put("/projects/{project_id}/mask/draft")
def agent_update_mask_draft(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    result = manifest_service.update_step5_draft(project, payload.payload)
    if result.get("changed"):
        invalidation_service.mask_content_changed(project)
        db.commit()
    return result


@router.put("/projects/{project_id}/mask")
def agent_update_mask_result(
    project_id: str,
    payload: MaskResultUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return manifest_service.update_step5_result(
            _project_or_404(db, project_id),
            payload.payload,
            build_assets=payload.build_assets,
            db=db,
        )
    except Exception as exc:
        _translate_error(exc)


@router.post("/projects/{project_id}/mask/previews/{slide_id}")
def agent_build_mask_preview(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return preview_service.build_step5_mask_preview(_project_or_404(db, project_id), slide_id)
    except Exception as exc:
        _translate_error(exc)


@router.get("/projects/{project_id}/mask/previews/{slide_id}/content")
def agent_get_mask_preview(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    try:
        preview_path = preview_service.get_step5_mask_preview_path(
            _project_or_404(db, project_id), slide_id
        )
    except Exception as exc:
        _translate_error(exc)
    return FileResponse(preview_path, media_type="image/png")
