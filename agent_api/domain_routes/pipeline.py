"""Agent pipeline adapters to source-owned business services."""

from __future__ import annotations

from typing import Any
from fastapi import Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database import get_db
from account_context import get_current_account_id
from agent_contract.models import (
    PipelineRunRequest,
    PipelineRunResult,
    PipelineStatusResult,
    PipelineResumeRequest,
    StageGetResult,
    CheckpointApproveRequest,
    CheckpointResult,
)
from agent_contract.operations import (
    CHECKPOINT_STAGES,
    get_checkpoint,
    operation_from_one_click,
    unwrap_one_click_status,
    normalize_status,
)
from agent_api.errors import (
    AgentAPIError,
    ValidationFailedError,
    ConflictError,
    OperationFailedError,
)
from agent_api.fingerprints import request_fingerprint
from agent_idempotency_service import get_idempotency_service, IdempotencyConflictError
from fastapi import APIRouter

from agent_api.domain_routes.common import (
    _idempotency_replay_or_raise,
    _resolve_project,
)

router = APIRouter()


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
            "pipeline.run",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "pipeline.run", payload.model_dump(mode="json"), project_id=project_id
            ),
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
            operation_id="pipeline:" + status["run_id"],
            project_id=project_id,
            status=normalize_status(str(status.get("status", "unknown"))).value,
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


_SSE_TERMINAL_STATES = frozenset(
    {
        "completed",
        "failed",
        "waiting_for_review",
        "waiting_for_user",
        "idle",
        "paused",
    }
)


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
    account_id: str = "default",
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

    from one_click_orchestrator import get_one_click_status
    from database import Project

    start_time = time.monotonic()
    last_heartbeat = start_time
    last_sent = None
    terminal_sent = False

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= max_duration:
            yield _sse_event(
                {
                    "project_id": project_id,
                    "reason": "max_duration_exceeded",
                    "status": "timeout",
                },
                event_name="close",
            )
            return

        # Poll the current status
        db = db_session_factory()
        try:
            project = (
                db.query(Project)
                .filter(
                    Project.id == project_id,
                    Project.account_id == account_id,
                )
                .first()
            )
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
    _resolve_project(db, project_id)

    from database import SessionLocal

    session_factory = SessionLocal

    return StreamingResponse(
        _sse_generator(project_id, session_factory, get_current_account_id()),
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
            "pipeline.resume",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "pipeline.resume",
                payload.model_dump(mode="json"),
                project_id=project_id,
            ),
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
            operation_id="pipeline:" + status["run_id"],
            project_id=project_id,
            status=normalize_status(str(status.get("status", "unknown"))).value,
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
    get_checkpoint(checkpoint)
    if payload.checkpoint != checkpoint:
        raise ValidationFailedError(
            "Checkpoint in the path and request body must match"
        )

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            "checkpoint.approve",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "checkpoint.approve",
                payload.model_dump(mode="json"),
                project_id=project_id,
                checkpoint=checkpoint,
            ),
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
