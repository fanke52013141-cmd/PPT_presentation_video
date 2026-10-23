"""Agent output adapters: video collection, PPTX export jobs and subtitles.

invoke 与分域 HTTP 共用这些函数；服务实例在函数体内解析，不走
Depends 默认值（invoke 直接调用时 FastAPI 不会解析依赖默认值）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from agent_contract.domains.outputs import (
    VideoSpeedRequest,
)
from database import get_db
from error_log_service import log_pipeline_error
from pptx_export import PPTX_MIME_TYPE
from video_contracts import VideoRenderError
from video_render_service import VideoRenderService, get_video_render_service
from pptx_service import PptxExportService, PptxServiceError, get_pptx_export_service
from subtitle_export_service import (
    SubtitleExportError,
    build_subtitle_export,
    subtitle_export_readiness,
)
from project_path_service import (
    project_or_404,
    project_run_dir_or_500,
    read_current_slide_ids_or_404,
)
from project_storage import UnsafeProjectPath, safe_identifier

router = APIRouter()


def _video_call(operation, *, project_id: str = "", step: str = "step8"):
    try:
        return operation()
    except VideoRenderError as exc:
        log_pipeline_error(
            project_id=project_id,
            step=step,
            error_message=str(exc.detail),
            error_type="VideoRenderError",
        )
        from fastapi import HTTPException
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _pptx_call(operation):
    try:
        return operation()
    except PptxServiceError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/projects/{project_id}/videos")
def agent_list_project_videos(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: VideoRenderService = get_video_render_service()
    return service.list_videos(db, project_id)


@router.get("/projects/{project_id}/videos/{filename}/content")
def agent_download_project_video(
    project_id: str,
    filename: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    service: VideoRenderService = get_video_render_service()
    path = _video_call(lambda: service.video_download(db, project_id, filename), project_id=project_id)
    download_name = _video_call(
        lambda: service.video_download_filename(db, project_id, filename), project_id=project_id
    )
    return FileResponse(path, media_type="video/mp4", filename=download_name)


@router.get("/projects/{project_id}/video/status")
def agent_get_final_video_status(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: VideoRenderService = get_video_render_service()
    return service.final_video_status(db, project_id)


@router.post("/projects/{project_id}/videos/{filename}/speed")
def agent_create_speed_adjusted_video(
    project_id: str,
    filename: str,
    payload: VideoSpeedRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: VideoRenderService = get_video_render_service()
    return _video_call(
        lambda: service.create_speed_adjusted_video(db, project_id, filename, payload.payload),
        project_id=project_id,
        step="speed",
    )


@router.delete("/projects/{project_id}/videos/{filename}")
def agent_delete_project_video(
    project_id: str,
    filename: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: VideoRenderService = get_video_render_service()
    return _video_call(
        lambda: service.delete_video(db, project_id, filename),
        project_id=project_id,
    )


@router.get("/projects/{project_id}/pptx/readiness")
def agent_pptx_readiness(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: PptxExportService = get_pptx_export_service()
    return _pptx_call(lambda: service.readiness(db, project_id))


@router.post("/projects/{project_id}/pptx/exports")
def agent_create_pptx_export(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: PptxExportService = get_pptx_export_service()
    return _pptx_call(lambda: service.create_export(db, project_id))


@router.get("/projects/{project_id}/pptx/exports")
def agent_list_pptx_exports(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: PptxExportService = get_pptx_export_service()
    return _pptx_call(lambda: service.list_exports(db, project_id))


@router.get("/projects/{project_id}/pptx/exports/{artifact_id}/content")
def agent_download_pptx_export(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    service: PptxExportService = get_pptx_export_service()
    path, artifact = _pptx_call(lambda: service.download_export(db, project_id, artifact_id))
    return FileResponse(path, media_type=PPTX_MIME_TYPE, filename=artifact.filename)


@router.delete("/projects/{project_id}/pptx/exports/{artifact_id}")
def agent_delete_pptx_export(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: PptxExportService = get_pptx_export_service()
    return _pptx_call(lambda: service.delete_export(db, project_id, artifact_id))


@router.get("/projects/{project_id}/pptx/jobs")
def agent_list_pptx_jobs(
    project_id: str,
    db: Session = Depends(get_db),
    job_type: str | None = Query(None),
) -> dict[str, Any]:
    service: PptxExportService = get_pptx_export_service()
    return _pptx_call(lambda: service.list_jobs(db, project_id, job_type=job_type))


@router.get("/projects/{project_id}/pptx/jobs/{job_id}")
def agent_get_pptx_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: PptxExportService = get_pptx_export_service()
    return _pptx_call(lambda: service.get_job(db, project_id, job_id))


@router.post("/projects/{project_id}/pptx/jobs/{job_id}/retry")
def agent_retry_pptx_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    service: PptxExportService = get_pptx_export_service()
    return _pptx_call(lambda: service.retry_job(db, project_id, job_id))


def _subtitle_context(db: Session, project_id: str):
    project = project_or_404(db, project_id)
    return project_run_dir_or_500(project), read_current_slide_ids_or_404(project)


def _safe_download_name(project_id: str) -> str:
    try:
        return f"{safe_identifier(project_id, label='project_id')}-subtitles.srt"
    except UnsafeProjectPath:
        return "subtitles.srt"


@router.get("/projects/{project_id}/subtitles/readiness")
def agent_subtitle_export_readiness(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run_dir, slide_ids = _subtitle_context(db, project_id)
    return subtitle_export_readiness(run_dir, slide_ids)


@router.get("/projects/{project_id}/subtitles/content")
def agent_download_subtitles_srt(
    project_id: str,
    db: Session = Depends(get_db),
) -> Response:
    from fastapi import HTTPException

    run_dir, slide_ids = _subtitle_context(db, project_id)
    try:
        export = build_subtitle_export(run_dir, slide_ids)
    except SubtitleExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=export.content,
        headers={
            "Content-Type": "text/srt; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{_safe_download_name(project_id)}"',
        },
    )
