"""Agent API v1 routes — the stable, versioned interface for Agent integration.

Every endpoint delegates to existing source-owned services. No business logic
is duplicated here. The routes provide:
- Unified request/response models (from agent_contract)
- Consistent error structure
- Idempotency key support
- Unified Operation status for long-running tasks

Existing web UI routes (/api/projects, /api/projects/{id}/steps/*) are NOT
modified. The Agent API is an additional layer alongside them.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from database import get_db, Project, ArtifactRecord
from project_path_service import project_or_404

from agent_contract.models import (
    ProjectCreateRequest, ProjectCreateResult, ProjectSummary,
    ProjectListResult, ProjectGetResult,
    ProjectUpdateRequest, ProjectUpdateResult,
    SourceSetRequest, SourceSetResult,
    PipelineRunRequest, PipelineRunResult,
    PipelineStatusResult, PipelineResumeRequest,
    StageGetResult, NarrationUpdateRequest,
    ImageRegenerateRequest, ImageRegenerateResult,
    TtsSynthesizeRequest, TtsSynthesizeResult,
    VideoRenderRequest, VideoRenderResult,
    CheckpointApproveRequest, CheckpointResult,
    ArtifactsListResult, ArtifactGetResult,
    DiagnosticsResult,
)
from agent_contract.operations import (
    OperationResult, OperationStatus,
    CHECKPOINT_STAGES, get_checkpoint,
    operation_from_one_click,
)
from agent_contract.artifacts import (
    ArtifactInfo, build_resource_uri, mime_for_type,
)
from agent_contract.versions import get_meta, get_contract_hash, AGENT_API_VERSION
from agent_api.errors import (
    AgentAPIError, ProjectNotFoundError, ValidationFailedError,
    ConflictError, OperationFailedError,
)

logger = logging.getLogger("PPTStudio.AgentAPI")

router = APIRouter(prefix="/api/agent/v1", tags=["Agent API v1"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_summary(project: Project) -> ProjectSummary:
    """Build a ProjectSummary from a database Project."""
    return ProjectSummary(
        project_id=project.id,
        name=project.name,
        description=project.description or "",
        canvas_profile=project.canvas_profile or "landscape_16_9",
        ai_mode=project.ai_mode or "auto",
        current_step=project.current_step or 1,
        status=project.status or "active",
        step_status=project.get_step_status(),
        created_at=project.created_at.isoformat() if project.created_at else None,
    )


def _gen_op_id() -> str:
    return f"op_{uuid.uuid4().hex[:12]}"


def _resolve_project(db: Session, project_id: str) -> Project:
    """Find a project or raise ProjectNotFoundError."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ProjectNotFoundError(project_id)
    return project


# ---------------------------------------------------------------------------
# Meta / Diagnostics
# ---------------------------------------------------------------------------

@router.get("/meta")
def get_agent_meta() -> dict[str, Any]:
    """Return Agent API version, contract hash, and capability list."""
    return get_meta()


@router.get("/diagnostics")
def get_diagnostics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return system diagnostics for troubleshooting."""
    from agent_contract.capabilities import get_stable_capabilities

    project_count = db.query(Project).count()
    artifact_count = db.query(ArtifactRecord).count()

    checks: dict[str, Any] = {
        "database": "ok" if project_count >= 0 else "error",
        "project_count": project_count,
        "artifact_count": artifact_count,
    }

    # Check optional services
    try:
        from config_store import get_setting
        llm_key = bool(get_setting("llm_api_key", ""))
        checks["llm_configured"] = llm_key
    except Exception:
        checks["llm_configured"] = False

    try:
        from config_store import get_setting
        tts_key = bool(get_setting("tts_api_key", ""))
        checks["tts_configured"] = tts_key
    except Exception:
        checks["tts_configured"] = False

    return DiagnosticsResult(
        agent_api_version=AGENT_API_VERSION,
        contract_hash=get_contract_hash(),
        capabilities=[c.id for c in get_stable_capabilities()],
        checks=checks,
    ).model_dump()


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

@router.post("/projects")
def agent_create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new project via Agent API."""
    from project_service import ProjectCreate, get_project_service

    # Map Agent API request to existing service
    service = get_project_service()
    internal_payload = ProjectCreate(
        name=payload.name,
        description=payload.description,
        ai_mode=payload.automation_mode.value if payload.automation_mode else "auto",
        canvas_profile=payload.canvas_profile.value if payload.canvas_profile else "landscape_16_9",
    )
    result = service.create(internal_payload, db)
    project_id = result.get("project", {}).get("id", "")
    project = db.query(Project).filter(Project.id == project_id).first()

    return ProjectCreateResult(
        project=_project_summary(project),
        operation_id=_gen_op_id(),
    ).model_dump()


@router.get("/projects")
def agent_list_projects(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List projects via Agent API."""
    query = db.query(Project)
    if status_filter and status_filter != "all":
        query = query.filter(Project.status == status_filter)
    query = query.order_by(Project.created_at.desc()).limit(limit)
    projects = query.all()

    return ProjectListResult(
        projects=[_project_summary(p) for p in projects],
        total=len(projects),
    ).model_dump()


@router.get("/projects/{project_id}")
def agent_get_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get project details via Agent API."""
    project = _resolve_project(db, project_id)

    # Check article and contract status
    from pathlib import Path
    run_dir = Path(project.run_dir)
    article_path = run_dir / "inputs" / "article.md"
    contract_path = run_dir / "planning" / "visual_contract.json"

    has_article = article_path.exists()
    has_contract = contract_path.exists()

    slide_ids: list[str] = []
    if has_contract:
        try:
            from visual_contract_service import read_contract_slide_ids
            slide_ids = read_contract_slide_ids(project)
        except Exception:
            pass

    return ProjectGetResult(
        project=_project_summary(project),
        has_article=has_article,
        has_contract=has_contract,
        slide_ids=slide_ids,
    ).model_dump()


@router.patch("/projects/{project_id}")
def agent_update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update project metadata via Agent API."""
    project = _resolve_project(db, project_id)

    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    if payload.ai_mode is not None:
        project.ai_mode = payload.ai_mode

    db.commit()
    db.refresh(project)

    return ProjectUpdateResult(
        project=_project_summary(project),
        updated=True,
    ).model_dump()


# ---------------------------------------------------------------------------
# Source / Article
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/source")
def agent_set_source(
    project_id: str,
    payload: SourceSetRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Set project source — direct content or topic-based generation."""
    project = _resolve_project(db, project_id)

    import article_service as article_svc

    if payload.content:
        # Direct article import
        result = article_svc.import_article(project, payload.content, db)
        article_text = payload.content
    elif payload.topic:
        # Topic-based generation
        gen_payload = {"topic": payload.topic}
        result = article_svc.generate_article_from_topic(project, gen_payload)
        article_text = result.get("article", "")
    else:
        raise ValidationFailedError("Either 'content' or 'topic' must be provided")

    preview = article_text[:500] if article_text else ""
    word_count = len(article_text) if article_text else 0

    return SourceSetResult(
        project_id=project_id,
        article_imported=True,
        article_preview=preview,
        word_count=word_count,
    ).model_dump()


# ---------------------------------------------------------------------------
# Pipeline run / status / resume
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/runs")
def agent_start_pipeline(
    project_id: str,
    payload: PipelineRunRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start or resume the automated pipeline."""
    project = _resolve_project(db, project_id)

    from one_click_orchestrator import start_one_click

    one_click_payload: dict[str, Any] = {}
    if payload.stop_at:
        one_click_payload["stop_at"] = payload.stop_at
    if payload.mode:
        one_click_payload["mode"] = payload.mode

    try:
        result = start_one_click(project, one_click_payload)
    except ValueError as e:
        raise ValidationFailedError(str(e))
    except Exception as e:
        raise OperationFailedError(f"Pipeline start failed: {e}")

    return PipelineRunResult(
        operation_id=result.get("run_id", _gen_op_id()),
        project_id=project_id,
        status=result.get("status", "running"),
        current_stage=result.get("current_stage", "preflight"),
        message=result.get("message", ""),
    ).model_dump()


@router.get("/projects/{project_id}/runs/latest")
def agent_pipeline_status(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get current pipeline status."""
    project = _resolve_project(db, project_id)

    from one_click_orchestrator import get_one_click_status
    status_dict = get_one_click_status(project)
    op = operation_from_one_click(status_dict, project_id)

    return PipelineStatusResult(
        operation_id=op.operation_id,
        project_id=op.project_id,
        status=op.status.value,
        current_stage=op.stage,
        progress=op.progress,
        message=op.message,
        stages=status_dict.get("stages", []),
        blocking_errors=op.blocking_errors,
        warnings=op.warnings,
        artifacts=op.artifacts,
    ).model_dump()


@router.post("/projects/{project_id}/runs/latest/resume")
def agent_resume_pipeline(
    project_id: str,
    payload: PipelineResumeRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Resume a paused or failed pipeline."""
    project = _resolve_project(db, project_id)

    from one_click_orchestrator import start_one_click

    one_click_payload: dict[str, Any] = {"mode": "resume"}
    if payload.stop_at:
        one_click_payload["stop_at"] = payload.stop_at

    try:
        result = start_one_click(project, one_click_payload)
    except ValueError as e:
        raise ValidationFailedError(str(e))
    except Exception as e:
        raise OperationFailedError(f"Pipeline resume failed: {e}")

    return PipelineRunResult(
        operation_id=result.get("run_id", _gen_op_id()),
        project_id=project_id,
        status=result.get("status", "running"),
        current_stage=result.get("current_stage", ""),
        message=result.get("message", ""),
    ).model_dump()


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/checkpoints")
def agent_list_checkpoints(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List available checkpoints for a project."""
    _resolve_project(db, project_id)
    return {
        "project_id": project_id,
        "checkpoints": [
            {"name": k, "label": v["label"], "description": v["description"]}
            for k, v in CHECKPOINT_STAGES.items()
        ],
    }


@router.post("/projects/{project_id}/checkpoints/{checkpoint}/approve")
def agent_approve_checkpoint(
    project_id: str,
    checkpoint: str,
    payload: CheckpointApproveRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve or reject a pipeline checkpoint."""
    project = _resolve_project(db, project_id)
    cp_info = get_checkpoint(checkpoint)

    if payload.approved:
        # Resume pipeline from this checkpoint
        from one_click_orchestrator import start_one_click
        start_one_click(project, {"mode": "resume"})
        next_stage = "pipeline resumed"
    else:
        next_stage = "pipeline halted at checkpoint"

    return CheckpointResult(
        project_id=project_id,
        checkpoint=checkpoint,
        approved=payload.approved,
        next_stage=next_stage,
    ).model_dump()


# ---------------------------------------------------------------------------
# Stage data
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/stages/{stage}")
def agent_get_stage(
    project_id: str,
    stage: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get detailed data for a specific pipeline stage."""
    project = _resolve_project(db, project_id)
    from pathlib import Path
    run_dir = Path(project.run_dir)

    stage_data: dict[str, Any] = {}
    slide_ids: list[str] = []

    if stage == "storyboard":
        contract_path = run_dir / "planning" / "visual_contract.json"
        if contract_path.exists():
            import json
            stage_data = json.loads(contract_path.read_text(encoding="utf-8-sig"))
            slides = stage_data.get("slides", [])
            slide_ids = [s.get("slide_id", "") for s in slides if isinstance(s, dict)]

    elif stage == "narration":
        narration_path = run_dir / "planning" / "narration_beats.json"
        if narration_path.exists():
            import json
            stage_data = json.loads(narration_path.read_text(encoding="utf-8-sig"))

    elif stage == "images":
        slides_dir = run_dir / "slides"
        if slides_dir.exists():
            for d in sorted(slides_dir.iterdir()):
                if d.is_dir():
                    slide_ids.append(d.name)
                    img = d / "visual_draft.png"
                    if img.exists():
                        stage_data.setdefault("slides", {})[d.name] = {
                            "has_image": True,
                            "image_path": str(img.relative_to(run_dir)),
                        }

    elif stage == "mask":
        manifest_path = run_dir / "planning" / "reveal_manifest.json"
        if manifest_path.exists():
            import json
            stage_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))

    return StageGetResult(
        project_id=project_id,
        stage=stage,
        data=stage_data,
        slide_ids=slide_ids,
    ).model_dump()


# ---------------------------------------------------------------------------
# Image regenerate
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/images/{slide_id}/regenerate")
def agent_regenerate_image(
    project_id: str,
    slide_id: str,
    payload: ImageRegenerateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Regenerate a single slide image."""
    project = _resolve_project(db, project_id)

    try:
        from pipeline_services import build_pipeline_services
        services = build_pipeline_services(db, project_id)
        result = services.generate_image(slide_id, payload.instruction or "")
        revision = result.get("revision", 0)
    except Exception as e:
        raise OperationFailedError(f"Image regeneration failed: {e}")

    resource_uri = build_resource_uri(project_id, "image", slide_id)

    return ImageRegenerateResult(
        slide_id=slide_id,
        artifact_id=result.get("artifact_id", ""),
        resource_uri=resource_uri,
        revision=revision,
        message="Image regenerated successfully",
    ).model_dump()


# ---------------------------------------------------------------------------
# Narration update
# ---------------------------------------------------------------------------

@router.patch("/projects/{project_id}/narration/{slide_id}")
def agent_update_narration(
    project_id: str,
    slide_id: str,
    payload: NarrationUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update narration text for a specific slide."""
    _resolve_project(db, project_id)

    try:
        from pathlib import Path
        project = db.query(Project).filter(Project.id == project_id).first()
        run_dir = Path(project.run_dir)
        narration_path = run_dir / "planning" / "narration_beats.json"

        import json
        if narration_path.exists():
            beats = json.loads(narration_path.read_text(encoding="utf-8-sig"))
            for beat in beats if isinstance(beats, list) else []:
                if isinstance(beat, dict) and beat.get("slide_id") == slide_id:
                    beat["tts_text"] = payload.narration_text
                    break
            narration_path.write_text(
                json.dumps(beats, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception as e:
        raise OperationFailedError(f"Narration update failed: {e}")

    return {
        "project_id": project_id,
        "slide_id": slide_id,
        "updated": True,
        "narration_text": payload.narration_text,
    }


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/tts")
def agent_tts_synthesize(
    project_id: str,
    payload: TtsSynthesizeRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start TTS audio synthesis."""
    project = _resolve_project(db, project_id)

    try:
        from pipeline_services import build_pipeline_services
        services = build_pipeline_services(db, project_id)
        result = services.synthesize_audio()
    except Exception as e:
        raise OperationFailedError(f"TTS synthesis failed: {e}")

    return TtsSynthesizeResult(
        operation_id=_gen_op_id(),
        project_id=project_id,
        status=result.get("status", "running"),
        job_id=result.get("job_id", result.get("task_id", "")),
    ).model_dump()


# ---------------------------------------------------------------------------
# Video render
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/videos/render")
def agent_video_render(
    project_id: str,
    payload: VideoRenderRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start video rendering."""
    project = _resolve_project(db, project_id)

    try:
        from pipeline_services import build_pipeline_services
        services = build_pipeline_services(db, project_id)
        result = services.render_video()
    except Exception as e:
        raise OperationFailedError(f"Video render failed: {e}")

    return VideoRenderResult(
        operation_id=_gen_op_id(),
        project_id=project_id,
        status=result.get("status", "running"),
        job_id=result.get("job_id", result.get("task_id", "")),
    ).model_dump()


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

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

        artifacts.append(ArtifactInfo(
            artifact_id=rec.id,
            artifact_type=rec.artifact_type,
            filename=rec.filename,
            mime_type=rec.mime_type or mime_for_type(rec.artifact_type),
            size_bytes=rec.size_bytes,
            resource_uri=build_resource_uri(project_id, rec.artifact_type, rec_slide_id),
            slide_id=rec_slide_id,
            revision=meta.get("revision", 0),
            created_at=rec.created_at.isoformat() if rec.created_at else None,
        ))

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
    _resolve_project(db, project_id)

    record = (
        db.query(ArtifactRecord)
        .filter(
            ArtifactRecord.id == artifact_id,
            ArtifactRecord.project_id == project_id,
        )
        .first()
    )
    if not record:
        raise AgentAPIError("ARTIFACT_NOT_FOUND", f"Artifact '{artifact_id}' not found", 404)

    meta = record.get_metadata()
    slide_id = meta.get("slide_id")

    return ArtifactGetResult(
        artifact=ArtifactInfo(
            artifact_id=record.id,
            artifact_type=record.artifact_type,
            filename=record.filename,
            mime_type=record.mime_type or mime_for_type(record.artifact_type),
            size_bytes=record.size_bytes,
            resource_uri=build_resource_uri(project_id, record.artifact_type, slide_id),
            slide_id=slide_id,
            revision=meta.get("revision", 0),
            created_at=record.created_at.isoformat() if record.created_at else None,
        ),
        download_url=f"/api/projects/{project_id}/artifacts/{artifact_id}/download",
    ).model_dump()
