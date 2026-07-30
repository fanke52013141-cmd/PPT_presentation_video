"""Explicit FastAPI routes for image-only PPTX exports."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from pptx_export import PPTX_MIME_TYPE
from pptx_service import (
    PptxExportService,
    PptxServiceError,
    get_pptx_export_service,
)


router = APIRouter(prefix="/api/projects/{project_id}")


def _service_call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except PptxServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@router.get("/exports/pptx/readiness")
def pptx_readiness(
    project_id: str,
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> dict[str, Any]:
    return _service_call(lambda: service.readiness(db, project_id))


@router.post("/exports/pptx")
def create_pptx_export(
    project_id: str,
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> dict[str, Any]:
    return _service_call(lambda: service.create_export(db, project_id))


@router.get("/jobs")
def list_jobs(
    project_id: str,
    job_type: str | None = Query(None),
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.list_jobs(
            db,
            project_id,
            job_type=job_type,
        )
    )


@router.get("/jobs/{job_id}")
def get_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.get_job(db, project_id, job_id)
    )


@router.post("/jobs/{job_id}/retry")
def retry_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.retry_job(db, project_id, job_id)
    )


@router.get("/exports")
def list_exports(
    project_id: str,
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> dict[str, Any]:
    return _service_call(lambda: service.list_exports(db, project_id))


@router.get("/exports/{artifact_id}/download")
def download_export(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> FileResponse:
    path, artifact = _service_call(
        lambda: service.download_export(
            db,
            project_id,
            artifact_id,
        )
    )
    return FileResponse(
        path,
        media_type=PPTX_MIME_TYPE,
        filename=artifact.filename,
    )


@router.delete("/exports/{artifact_id}")
def delete_export(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    service: PptxExportService = Depends(get_pptx_export_service),
) -> dict[str, Any]:
    return _service_call(
        lambda: service.delete_export(
            db,
            project_id,
            artifact_id,
        )
    )
