"""Agent artifacts adapters to source-owned business services."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from fastapi import Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db, ArtifactRecord
from agent_contract.models import ArtifactsListResult, ArtifactGetResult, ArtifactInfo
from agent_contract.artifacts import build_resource_uri, mime_for_type
from agent_api.errors import AgentAPIError
from artifact_fingerprint import sha256_file
from project_path_service import project_run_dir_or_500
from fastapi import APIRouter

from agent_api.domain_routes.common import _resolve_project

router = APIRouter()


def _registered_artifact_path(project, record) -> Path | None:
    run_dir = Path(project_run_dir_or_500(project)).resolve()
    candidate = (run_dir / record.relative_path).resolve()
    return candidate if candidate.is_relative_to(run_dir) and candidate.is_file() else None


@router.get("/projects/{project_id}/slides/{slide_id}/image")
def agent_get_slide_image(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return the current slide image through the source-owned image service."""
    from image_workflow_service import get_slide_image_file

    return get_slide_image_file(project_id, slide_id, db)


@router.get("/projects/{project_id}/slides/{slide_id}/audio")
def agent_get_slide_audio(
    project_id: str,
    slide_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return the current non-stale slide audio through the TTS service."""
    from tts_service import get_slide_audio_file

    return get_slide_audio_file(project_id, slide_id, db)


@router.get("/projects/{project_id}/artifacts")
def agent_list_artifacts(
    project_id: str,
    artifact_type: Optional[str] = Query(None),
    slide_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List artifacts for a project."""
    _resolve_project(db, project_id)

    query = db.query(ArtifactRecord).filter(ArtifactRecord.project_id == project_id)
    if artifact_type and artifact_type != "all":
        query = query.filter(ArtifactRecord.artifact_type == artifact_type)

    records = query.order_by(ArtifactRecord.created_at.desc()).all()

    artifacts: list[ArtifactInfo] = []
    for rec in records:
        meta = rec.get_metadata()
        rec_slide_id = meta.get("slide_id")
        if slide_id and rec_slide_id != slide_id:
            continue

        artifacts.append(
            ArtifactInfo(
                artifact_id=rec.id,
                artifact_type=rec.artifact_type,
                filename=rec.filename,
                mime_type=rec.mime_type or mime_for_type(rec.artifact_type),
                size_bytes=rec.size_bytes,
                resource_uri=build_resource_uri(
                    project_id, rec.artifact_type, rec_slide_id, artifact_id=rec.id
                ),
                slide_id=rec_slide_id,
                revision=meta.get("revision", 0),
                created_at=rec.created_at.isoformat() if rec.created_at else None,
            )
        )

    return ArtifactsListResult(
        project_id=project_id,
        artifacts=artifacts,
        total=len(artifacts),
    ).model_dump()


@router.get("/projects/{project_id}/artifacts/{artifact_id}")
def agent_get_artifact(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get artifact details and download URL."""
    project = _resolve_project(db, project_id)

    record = (
        db.query(ArtifactRecord)
        .filter(
            ArtifactRecord.id == artifact_id,
            ArtifactRecord.project_id == project_id,
        )
        .first()
    )
    if not record:
        raise AgentAPIError(
            "ARTIFACT_NOT_FOUND", f"Artifact '{artifact_id}' not found", 404
        )

    meta = record.get_metadata()
    slide_id = meta.get("slide_id")
    path = _registered_artifact_path(project, record)

    return ArtifactGetResult(
        artifact=ArtifactInfo(
            artifact_id=record.id,
            artifact_type=record.artifact_type,
            filename=record.filename,
            mime_type=record.mime_type or mime_for_type(record.artifact_type),
            size_bytes=record.size_bytes,
            resource_uri=build_resource_uri(project_id, record.artifact_type, slide_id, artifact_id=record.id),
            slide_id=slide_id,
            revision=meta.get("revision", 0),
            created_at=record.created_at.isoformat() if record.created_at else None,
            sha256=sha256_file(path) if path is not None else None,
        ),
        download_url=f"/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}/content",
    ).model_dump()


@router.get("/projects/{project_id}/artifacts/{artifact_id}/content")
def agent_download_artifact(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download a database-tracked artifact after validating its project path."""
    project = _resolve_project(db, project_id)
    record = (
        db.query(ArtifactRecord)
        .filter(
            ArtifactRecord.id == artifact_id, ArtifactRecord.project_id == project_id
        )
        .first()
    )
    if not record:
        raise AgentAPIError(
            "ARTIFACT_NOT_FOUND", f"Artifact '{artifact_id}' not found", 404
        )
    candidate = _registered_artifact_path(project, record)
    if candidate is None:
        raise AgentAPIError("ARTIFACT_UNAVAILABLE", "Artifact file is unavailable", 404)
    return FileResponse(
        candidate,
        media_type=record.mime_type or mime_for_type(record.artifact_type),
        filename=record.filename,
    )
