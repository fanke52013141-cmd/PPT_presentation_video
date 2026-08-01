"""Explicit FastAPI routes for video rendering and MP4 artifacts."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from video_contracts import VideoRenderError
from video_render_service import VideoRenderService, get_video_render_service


router = APIRouter()


def _service_call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except VideoRenderError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@router.post("/api/projects/{project_id}/steps/8/render")
def render_video(
    project_id: str,
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.start_render(db, project_id)
    )


@router.get("/api/projects/{project_id}/steps/8/render-status")
def get_render_status(
    project_id: str,
    task_id: str | None = Query(None),
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.render_status(
            db,
            project_id,
            task_id=task_id,
        )
    )


@router.get("/api/projects/{project_id}/videos")
def list_project_videos(
    project_id: str,
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.list_videos(db, project_id)
    )


@router.get("/api/projects/{project_id}/videos/{filename}")
def get_project_video(
    project_id: str,
    filename: str,
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> FileResponse:
    path = _service_call(
        lambda: service.video_download(
            db,
            project_id,
            filename,
        )
    )
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename,
    )


@router.post(
    "/api/projects/{project_id}/videos/{filename}/speed"
)
def create_speed_adjusted_video(
    project_id: str,
    filename: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.create_speed_adjusted_video(
            db,
            project_id,
            filename,
            payload,
        )
    )


@router.delete("/api/projects/{project_id}/videos/{filename}")
def delete_project_video(
    project_id: str,
    filename: str,
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.delete_video(
            db,
            project_id,
            filename,
        )
    )


@router.get("/api/projects/{project_id}/video/status")
def get_final_video_status(
    project_id: str,
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.final_video_status(db, project_id)
    )


@router.get("/api/projects/{project_id}/video")
def get_final_video(
    project_id: str,
    db: Session = Depends(get_db),
    service: VideoRenderService = Depends(
        get_video_render_service
    ),
) -> FileResponse:
    path = _service_call(
        lambda: service.final_video_download(
            db,
            project_id,
        )
    )
    return FileResponse(path, media_type="video/mp4")
