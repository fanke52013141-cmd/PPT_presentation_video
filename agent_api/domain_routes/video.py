"""Agent video adapters to source-owned business services."""

from __future__ import annotations

from typing import Any
from fastapi import Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from agent_contract.models import VideoRenderRequest, VideoRenderResult
from agent_contract.operations import normalize_status
from agent_api.errors import ConflictError, OperationFailedError
from agent_api.fingerprints import request_fingerprint
from agent_idempotency_service import get_idempotency_service, IdempotencyConflictError
from fastapi import APIRouter

from agent_api.domain_routes.common import (
    _idempotency_replay_or_raise,
    _resolve_project,
    finalize_claim_failure,
)

router = APIRouter()


@router.get("/projects/{project_id}/videos/latest")
def agent_get_latest_video(
    project_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return the latest final video through the configured video service."""
    from video_render_service import get_video_render_service

    path = get_video_render_service().final_video_download(db, project_id)
    return FileResponse(path, media_type="video/mp4")


@router.post("/projects/{project_id}/videos/render")
def agent_video_render(
    project_id: str,
    payload: VideoRenderRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start video rendering."""
    _resolve_project(db, project_id)

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "videos.render",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "video.render", payload.model_dump(mode="json"), project_id=project_id
            ),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        from pipeline_services import get_project_pipeline_services

        services = get_project_pipeline_services(db, project_id)
        result = services.render_video()
    except Exception as e:
        finalize_claim_failure(claim, e)
        raise OperationFailedError(f"Video render failed: {e}")

    response = VideoRenderResult(
        operation_id="job:" + result["task_id"],
        project_id=project_id,
        status=normalize_status(str(result.get("status", "unknown"))).value,
        job_id=result.get("job_id", result.get("task_id", "")),
    ).model_dump()
    idempotency.finalize(claim.record_pk, True, response)
    return response
