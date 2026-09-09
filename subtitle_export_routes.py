"""HTTP contract for downloading one project's merged SRT subtitle file."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from project_path_service import (
    project_or_404,
    project_run_dir_or_500,
    read_current_slide_ids_or_404,
)
from project_storage import UnsafeProjectPath, safe_identifier
from subtitle_export_service import (
    SubtitleExportError,
    build_subtitle_export,
    subtitle_export_readiness,
)


router = APIRouter()


def _project_subtitle_context(db: Session, project_id: str) -> tuple[str, list[str]]:
    project = project_or_404(db, project_id)
    return (
        project_run_dir_or_500(project),
        read_current_slide_ids_or_404(project),
    )


def _safe_download_name(project_id: str) -> str:
    try:
        return f"{safe_identifier(project_id, label='project_id')}-subtitles.srt"
    except UnsafeProjectPath:
        return "subtitles.srt"


@router.get("/api/projects/{project_id}/subtitles/readiness")
def get_subtitle_export_readiness(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run_dir, slide_ids = _project_subtitle_context(db, project_id)
    return subtitle_export_readiness(run_dir, slide_ids)


@router.get("/api/projects/{project_id}/subtitles.srt")
def download_subtitles_srt(
    project_id: str,
    db: Session = Depends(get_db),
) -> Response:
    run_dir, slide_ids = _project_subtitle_context(db, project_id)
    try:
        export = build_subtitle_export(run_dir, slide_ids)
    except SubtitleExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=export.content,
        headers={
            "Content-Type": "text/srt; charset=utf-8",
            "Content-Disposition": (
                f'attachment; filename="{_safe_download_name(project_id)}"'
            ),
        },
    )
