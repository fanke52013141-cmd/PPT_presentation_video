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
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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
    DigitalHumanConfigUpdateRequest, DigitalHumanConfigResult,
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
    operation_from_one_click, unwrap_one_click_status,
)
from agent_contract.artifacts import (
    ArtifactInfo, build_resource_uri, mime_for_type,
)
from agent_contract.versions import get_meta, get_contract_hash, AGENT_API_VERSION
from agent_api.errors import (
    AgentAPIError, ProjectNotFoundError, ValidationFailedError,
    ConflictError, OperationFailedError,
)
from agent_idempotency_service import (
    AgentIdempotencyService,
    compute_fingerprint,
    get_idempotency_service,
    IdempotencyConflictError,
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
        revision=getattr(project, "revision", 0) or 0,
        review_policy=getattr(project, "review_policy", "none") or "none",
        mask_enabled=bool(getattr(project, "mask_enabled", 1) or 0),
        created_at=project.created_at.isoformat() if project.created_at else None,
    )


def _gen_op_id() -> str:
    return f"op_{uuid.uuid4().hex[:12]}"


def _idempotency_replay_or_raise(claim_result) -> Optional[dict[str, Any]]:
    """Return a replay dict (with header) or None; convert conflicts."""
    if claim_result.replay_response is not None:
        return JSONResponse(
            claim_result.replay_response,
            headers={"X-Agent-Idempotency-Replay": "true"},
        )
    return None


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
# OpenAPI / Swagger documentation
# ---------------------------------------------------------------------------

@router.get("/openapi.json")
def agent_openapi_json() -> dict[str, Any]:
    """Return the OpenAPI 3.0 specification for the Agent API."""
    from agent_api.openapi_docs import build_agent_openapi_spec
    return build_agent_openapi_spec(stable_only=True)


@router.get("/docs")
def agent_swagger_ui() -> str:
    """Return an embedded Swagger UI page pointing at the Agent API OpenAPI spec."""
    from agent_api.openapi_docs import render_swagger_ui

    return HTMLResponse(
        content=render_swagger_ui("/api/agent/v1/openapi.json"),
    )


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

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "project.create", "", payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        # Map Agent API request to existing service
        service = get_project_service()
        internal_payload = ProjectCreate(
            name=payload.name,
            description=payload.description,
            ai_mode=payload.automation_mode.value if payload.automation_mode else "auto",
            canvas_profile=payload.canvas_profile.value if payload.canvas_profile else "landscape_16_9",
            review_policy=payload.review_policy.value if payload.review_policy else "none",
            mask_enabled=payload.mask_enabled,
        )
        result = service.create(internal_payload, db)
        project_id = result.get("project", {}).get("id", "")
        project = db.query(Project).filter(Project.id == project_id).first()

        response = ProjectCreateResult(
            project=_project_summary(project),
            operation_id=_gen_op_id(),
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except Exception:
        idempotency.finalize(claim.record_pk, False, None)
        raise


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
            slide_ids = read_contract_slide_ids(project.run_dir)
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

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "project.update", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        AgentIdempotencyService.check_revision(project, payload.expected_revision)
    except IdempotencyConflictError as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise ConflictError(str(e), details=e.details)

    try:
        if payload.name is not None:
            project.name = payload.name
        if payload.description is not None:
            project.description = payload.description
        if payload.ai_mode is not None:
            project.ai_mode = payload.ai_mode

        AgentIdempotencyService.bump_revision(db, project)
        db.commit()
        db.refresh(project)

        response = ProjectUpdateResult(
            project=_project_summary(project),
            updated=True,
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except Exception:
        idempotency.finalize(claim.record_pk, False, None)
        raise


@router.delete("/projects/{project_id}")
def agent_delete_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a project and all its artifacts."""
    project = _resolve_project(db, project_id)
    from project_service import get_project_service

    service = get_project_service()
    result = service.delete(project_id, db)
    return {"project_id": project_id, "deleted": True, "details": result}


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

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "source.set", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        import article_service as article_svc

        if payload.content:
            # Direct article import
            result = article_svc.import_article(project, payload.content, db)
            article_text = payload.content
        elif payload.topic:
            # Topic-based generation
            gen_payload = {"topic": payload.topic}
            result = article_svc.generate_article_from_topic(project, gen_payload)
            article_text = str(result.get("content") or "")
            # Topic generation only produces text.  Persist it through the same
            # source-owned import path used by the web UI before reporting success.
            article_svc.import_article(project, article_text, db)
        else:
            raise ValidationFailedError("Either 'content' or 'topic' must be provided")

        preview = article_text[:500] if article_text else ""
        word_count = len(article_text) if article_text else 0

        response = SourceSetResult(
            project_id=project_id,
            article_imported=True,
            article_preview=preview,
            word_count=word_count,
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except Exception:
        idempotency.finalize(claim.record_pk, False, None)
        raise


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

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "pipeline.run", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        from one_click_orchestrator import start_one_click

        one_click_payload: dict[str, Any] = {}
        if "start_from" in payload.model_fields_set and payload.start_from:
            one_click_payload["start_from"] = payload.start_from
        if payload.stop_at:
            one_click_payload["stop_at"] = payload.stop_at
        if payload.mode:
            one_click_payload["mode"] = payload.mode

        result = start_one_click(project, one_click_payload)
        status = unwrap_one_click_status(result)

        response = PipelineRunResult(
            operation_id=status.get("run_id", _gen_op_id()),
            project_id=project_id,
            status=str(status.get("status", "running")),
            current_stage=str(status.get("current_stage", "preflight")),
            message=str(status.get("message", "")),
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except ValueError as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise ValidationFailedError(str(e))
    except Exception as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise OperationFailedError(f"Pipeline start failed: {e}")


@router.get("/projects/{project_id}/runs/latest")
def agent_pipeline_status(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get current pipeline status."""
    project = _resolve_project(db, project_id)

    from one_click_orchestrator import get_one_click_status
    status_dict = unwrap_one_click_status(get_one_click_status(project))
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


_SSE_TERMINAL_STATES = frozenset({"completed", "failed", "waiting_for_review", "idle", "paused"})
_SSE_POLL_INTERVAL = 1.0
_SSE_HEARTBEAT_INTERVAL = 15.0
_SSE_MAX_DURATION = 1800.0  # 30 minutes safety valve


def _sse_event(data: dict[str, Any], event_name: str = "progress") -> bytes:
    """Format a Server-Sent Events frame."""
    import json
    payload = json.dumps(data, ensure_ascii=False, default=str)
    frame = f"event: {event_name}\ndata: {payload}\n\n"
    return frame.encode("utf-8")


def _sse_heartbeat() -> bytes:
    """SSE heartbeat comment for connection keep-alive."""
    return b": heartbeat\n\n"


def _sse_generator(
    project_id: str,
    db_session_factory,
    poll_interval: float = _SSE_POLL_INTERVAL,
    heartbeat_interval: float = _SSE_HEARTBEAT_INTERVAL,
    max_duration: float = _SSE_MAX_DURATION,
):
    """Generate SSE events by polling the pipeline status.

    Yields progress events when the pipeline stage or status changes,
    a final terminal event when the pipeline reaches a terminal state,
    and heartbeat comments periodically.
    """
    import time

    from one_click_orchestrator import get_one_click_status, _RUNNING
    from database import Project

    start_time = time.monotonic()
    last_heartbeat = start_time
    last_sent = None
    terminal_sent = False

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= max_duration:
            yield _sse_event(
                {"project_id": project_id, "reason": "max_duration_exceeded", "status": "timeout"},
                event_name="close",
            )
            return

        # Poll the current status
        db = db_session_factory()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                yield _sse_event(
                    {"project_id": project_id, "error": "Project not found"},
                    event_name="error",
                )
                return
            status_dict = unwrap_one_click_status(get_one_click_status(project))
        finally:
            db.close()

        status = status_dict.get("status", "idle")
        current_stage = status_dict.get("current_stage", "")
        run_id = status_dict.get("run_id", "")
        stages = status_dict.get("stages", [])

        # Compute aggregate progress from stages
        stage_items = stages if isinstance(stages, list) else []
        done_count = sum(1 for s in stage_items if s.get("status") == "done")
        total_count = max(1, len(stage_items))
        progress = round(done_count / total_count, 4)

        snapshot = {
            "project_id": project_id,
            "run_id": run_id,
            "status": status,
            "current_stage": current_stage,
            "progress": progress,
            "stages": stage_items,
            "blocking_errors": status_dict.get("blocking_errors", []),
            "review_checkpoint": status_dict.get("review_checkpoint", ""),
            "updated_at": status_dict.get("updated_at", ""),
        }

        # Send event when something changes
        fingerprint = (status, current_stage, run_id)
        if fingerprint != last_sent:
            yield _sse_event(snapshot, event_name="progress")
            last_sent = fingerprint

        # Check for terminal state
        if status in _SSE_TERMINAL_STATES:
            if not terminal_sent:
                yield _sse_event(snapshot, event_name="complete")
                terminal_sent = True
            return

        # Heartbeat
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_interval:
            yield _sse_heartbeat()
            last_heartbeat = now

        # Wait before next poll
        time.sleep(poll_interval)


@router.get("/projects/{project_id}/runs/latest/stream")
def agent_pipeline_stream(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Stream real-time pipeline progress via Server-Sent Events.

    The client connects once and receives ``event: progress`` frames
    whenever the pipeline stage or status changes, an ``event: complete``
    frame when the pipeline reaches a terminal state, and periodic
    ``: heartbeat`` comments to keep the connection alive.

    The stream auto-closes after the terminal event or after 30 minutes.
    """
    project = _resolve_project(db, project_id)

    from database import SessionLocal

    session_factory = SessionLocal

    return StreamingResponse(
        _sse_generator(project_id, session_factory),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/projects/{project_id}/runs/latest/resume")
def agent_resume_pipeline(
    project_id: str,
    payload: PipelineResumeRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Resume a paused or failed pipeline."""
    project = _resolve_project(db, project_id)

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "pipeline.resume", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        from one_click_orchestrator import start_one_click

        one_click_payload: dict[str, Any] = {"mode": "resume"}
        if payload.stop_at:
            one_click_payload["stop_at"] = payload.stop_at

        result = start_one_click(project, one_click_payload)
        status = unwrap_one_click_status(result)

        response = PipelineRunResult(
            operation_id=status.get("run_id", _gen_op_id()),
            project_id=project_id,
            status=str(status.get("status", "running")),
            current_stage=str(status.get("current_stage", "")),
            message=str(status.get("message", "")),
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except ValueError as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise ValidationFailedError(str(e))
    except Exception as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise OperationFailedError(f"Pipeline resume failed: {e}")


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
    if payload.checkpoint != checkpoint:
        raise ValidationFailedError("Checkpoint in the path and request body must match")

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "checkpoint.approve", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        if payload.approved:
            # Resume pipeline from this checkpoint
            from one_click_orchestrator import start_one_click
            start_one_click(
                project,
                {"mode": "resume", "approved_checkpoint": checkpoint},
            )
            next_stage = "pipeline resumed"
        else:
            from one_click_orchestrator import reject_one_click_checkpoint
            reject_one_click_checkpoint(project, checkpoint, payload.notes)
            next_stage = "pipeline remains halted at checkpoint"

        response = CheckpointResult(
            project_id=project_id,
            checkpoint=checkpoint,
            approved=payload.approved,
            next_stage=next_stage,
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except AgentAPIError:
        idempotency.finalize(claim.record_pk, False, None)
        raise
    except Exception as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise OperationFailedError(f"Checkpoint approve failed: {e}")


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
# Agent media resources
# ---------------------------------------------------------------------------

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


@router.get("/projects/{project_id}/videos/latest")
def agent_get_latest_video(
    project_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return the latest final video through the configured video service."""
    from video_render_service import get_video_render_service
    path = get_video_render_service().final_video_download(db, project_id)
    return FileResponse(path, media_type="video/mp4")


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
    _resolve_project(db, project_id)

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "images.regenerate", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        from pipeline_services import get_project_pipeline_services
        services = get_project_pipeline_services(db, project_id)
        result = services.generate_image(slide_id, payload.instruction or "")
        revision = result.get("revision", 0)
    except Exception as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise OperationFailedError(f"Image regeneration failed: {e}")

    resource_uri = build_resource_uri(project_id, "image", slide_id)

    response = ImageRegenerateResult(
        slide_id=slide_id,
        artifact_id=result.get("artifact_id", ""),
        resource_uri=resource_uri,
        revision=revision,
        message="Image regenerated successfully",
    ).model_dump()
    idempotency.finalize(claim.record_pk, True, response)
    return response


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
    project = _resolve_project(db, project_id)

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "narration.update", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        AgentIdempotencyService.check_revision(project, payload.expected_revision)
    except IdempotencyConflictError as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise ConflictError(str(e), details=e.details)

    try:
        from pipeline_services import get_project_pipeline_services

        services = get_project_pipeline_services(db, project_id)
        current = services.narration()
        beats = current.get("beats") if isinstance(current, dict) else None
        if not isinstance(beats, dict) or not isinstance(beats.get("slides"), list):
            raise ValidationFailedError("Narration beats do not exist; initialize narration first")

        updated = False
        for slide in beats["slides"]:
            if isinstance(slide, dict) and str(slide.get("slide_id") or "") == slide_id:
                # tts_text is the canonical speech text consumed by the TTS
                # service.  Preserve all other beat metadata verbatim.
                slide["tts_text"] = payload.narration_text
                updated = True
                break
        if not updated:
            raise ValidationFailedError(f"Slide '{slide_id}' does not exist in narration beats")

        # The source-owned service persists the payload and invalidates stale
        # audio/video state through the existing step-navigation lifecycle.
        services.save_narration(beats)

        AgentIdempotencyService.bump_revision(db, project)
        db.commit()

        response = {
            "project_id": project_id,
            "slide_id": slide_id,
            "updated": True,
            "narration_text": payload.narration_text,
        }
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except AgentAPIError:
        idempotency.finalize(claim.record_pk, False, None)
        raise
    except Exception as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise OperationFailedError(f"Narration update failed: {e}")


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
    _resolve_project(db, project_id)

    if payload.slide_ids:
        raise ValidationFailedError(
            "Partial TTS synthesis is not supported by the production service; omit slide_ids to synthesize the current project"
        )

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "tts.synthesize", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        from pipeline_services import get_project_pipeline_services
        services = get_project_pipeline_services(db, project_id)
        result = services.synthesize_audio()
    except Exception as e:
        idempotency.finalize(claim.record_pk, False, None)
        raise OperationFailedError(f"TTS synthesis failed: {e}")

    response = TtsSynthesizeResult(
        operation_id=_gen_op_id(),
        project_id=project_id,
        status=result.get("status", "running"),
        job_id=result.get("job_id", result.get("task_id", "")),
    ).model_dump()
    idempotency.finalize(claim.record_pk, True, response)
    return response


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
    _resolve_project(db, project_id)

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "videos.render", project_id, payload.idempotency_key or "",
            compute_fingerprint(payload.model_dump(mode="json")),
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
        idempotency.finalize(claim.record_pk, False, None)
        raise OperationFailedError(f"Video render failed: {e}")

    response = VideoRenderResult(
        operation_id=_gen_op_id(),
        project_id=project_id,
        status=result.get("status", "running"),
        job_id=result.get("job_id", result.get("task_id", "")),
    ).model_dump()
    idempotency.finalize(claim.record_pk, True, response)
    return response


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
        .filter(ArtifactRecord.id == artifact_id, ArtifactRecord.project_id == project_id)
        .first()
    )
    if not record:
        raise AgentAPIError("ARTIFACT_NOT_FOUND", f"Artifact '{artifact_id}' not found", 404)
    run_dir = Path(project.run_dir).resolve()
    candidate = (run_dir / record.relative_path).resolve()
    if not candidate.is_relative_to(run_dir) or not candidate.is_file():
        raise AgentAPIError("ARTIFACT_UNAVAILABLE", "Artifact file is unavailable", 404)
    return FileResponse(candidate, media_type=record.mime_type or mime_for_type(record.artifact_type), filename=record.filename)


# ---------------------------------------------------------------------------
# Digital Human (Step 9 optional)
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/digital-human/config")
def agent_get_digital_human_config(
    project_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """Get the digital-human configuration for a project."""
    project = _resolve_project(db, project_id)
    config_path = Path(project.run_dir) / "planning" / "digital_human.json"
    if not config_path.is_file():
        return JSONResponse({"enabled": False, "configured": False})
    import json as _json
    data = _json.loads(config_path.read_text(encoding="utf-8"))
    return data


@router.patch("/projects/{project_id}/digital-human/config")
def agent_update_digital_human_config(
    project_id: str,
    payload: DigitalHumanConfigUpdateRequest,
    db: Session = Depends(get_db),
) -> DigitalHumanConfigResult:
    """Update the digital-human configuration."""
    project = _resolve_project(db, project_id)
    from digital_human_routes import update_digital_human_config

    config = update_digital_human_config(project, payload.config)
    return DigitalHumanConfigResult(config=config)


@router.get("/projects/{project_id}/digital-human/health")
def agent_digital_human_health(
    project_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """Check digital-human service availability."""
    _resolve_project(db, project_id)
    try:
        from digital_human_client import get_digital_human_client
        client = get_digital_human_client()
        health = client.health()
        return {"available": True, "health": health}
    except Exception as e:
        return {"available": False, "error": str(e)}


@router.post("/projects/{project_id}/digital-human/generate-full")
def agent_digital_human_generate_full(
    project_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """Trigger full digital-human generation for all slides."""
    project = _resolve_project(db, project_id)
    from visual_contract_service import read_contract_slide_ids
    slide_ids = read_contract_slide_ids(Path(project.run_dir))
    if not slide_ids:
        raise ValidationFailedError("No slides found in visual contract")
    try:
        from digital_human_client import get_digital_human_client, DigitalHumanUnavailable
        client = get_digital_human_client()
    except Exception as e:
        raise OperationFailedError(f"Digital human service unavailable: {e}")

    results: list[dict[str, Any]] = []
    for slide_id in slide_ids:
        audio_path = Path(project.run_dir) / "slides" / slide_id / "voice.mp3"
        if not audio_path.is_file():
            results.append({"slide_id": slide_id, "status": "skipped", "reason": "no audio"})
            continue
        try:
            job = client.create_job(audio_path=str(audio_path), slide_id=slide_id)
            results.append({"slide_id": slide_id, "status": "submitted", "job": job})
        except DigitalHumanUnavailable as e:
            results.append({"slide_id": slide_id, "status": "failed", "error": str(e)})
        except Exception as e:
            results.append({"slide_id": slide_id, "status": "failed", "error": str(e)})
    return {"success": True, "results": results}
