"""Agent project adapters to source-owned business services."""

from __future__ import annotations

from typing import Annotated, Any, Optional
from fastapi import Depends, Query, Request, HTTPException
from sqlalchemy.orm import Session
from database import get_db, Project
from account_context import get_current_account_id
from agent_contract.models import (
    ProjectSummary,
    ProjectCreateRequest,
    ProjectCreateResult,
    ProjectListResult,
    ProjectGetResult,
    ProjectUpdateRequest,
    ProjectUpdateResult,
    ProjectDeleteRequest,
    ProjectStateResult,
)
from agent_api.errors import ValidationFailedError, ConflictError
from agent_api.fingerprints import request_fingerprint
from agent_idempotency_service import (
    AgentIdempotencyService,
    get_idempotency_service,
    IdempotencyConflictError,
)
from fastapi import APIRouter

from agent_api.domain_routes.common import (
    _idempotency_replay_or_raise,
    _resolve_project,
)
from agent_contract.domains.freeform import FreeFormRequest
from agent_contract.domains.project import AiModeUpdateRequest

router = APIRouter()


@router.get("/projects/{project_id}/state", response_model=ProjectStateResult)
def agent_project_state(project_id: str, request: Request, db: Session = Depends(get_db)):
    from database import LocalJob
    from agent_contract.capabilities import CAPABILITIES
    from agent_contract.discovery import required_scope
    from agent_workflow_service import inspect_project_state
    from annotation_service import get_annotation_service
    from digital_human_routes import _load_config
    from project_path_service import project_run_dir_or_500
    from project_storage import safe_identifier, UnsafeProjectPath
    from visual_contract_service import read_contract_slide_ids
    from video_render_service import get_video_render_service

    project = _resolve_project(db, project_id)
    project_run_dir_or_500(project)
    identities = read_contract_slide_ids(project.run_dir)
    try:
        for identity in identities:
            safe_identifier(identity, label="slide_id")
    except UnsafeProjectPath as exc:
        from agent_api.errors import AgentAPIError
        raise AgentAPIError("INVALID_PROJECT_ARTIFACT", "Contract contains invalid slide identifiers", 409) from exc
    annotation = {"module_state": "not_started", "readiness": {"can_render": True, "blocking": []}}
    if identities:
        try:
            annotation = get_annotation_service().get_summary(db, project_id)
        except HTTPException as exc:
            annotation = {"module_state": "unavailable", "readiness": {
                "can_render": False, "blocking": [{"reason": "annotation_state_unavailable", "status_code": exc.status_code}],
            }}
    scopes = getattr(request.state, "agent_scopes", set())
    authenticated = getattr(request.state, "agent_authenticated", False)
    authorized = {cap.id for cap in CAPABILITIES if cap.status.value != "removed"
                  and (not authenticated or not scopes or required_scope(cap) in scopes)}
    active = db.query(LocalJob.id).filter(LocalJob.project_id == project_id, LocalJob.status.in_(("queued", "running"))).order_by(LocalJob.id).all()
    return inspect_project_state(project, annotation=annotation,
                                 digital_human_enabled=bool(_load_config(project).get("enabled")),
                                 render_submission=get_video_render_service().inspect_submission(project),
                                 active_jobs=["job:" + row[0] for row in active], authorized_capabilities=authorized)


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
        mask_enabled=bool(getattr(project, "mask_enabled", 0) or 0),
        production_mode=getattr(project, "production_mode", "guided") or "guided",
        presentation_mode=getattr(project, "presentation_mode", "full_frame")
        or "full_frame",
        creation_config=(
            {
                "package_id": project.creation_config_package_id,
                "version": project.creation_config_version,
                "content_hash": project.creation_config_hash,
            }
            if getattr(project, "creation_config_package_id", None)
            else None
        ),
        course_id=getattr(project, "course_id", None),
        chapter_id=getattr(project, "chapter_id", None),
        created_at=project.created_at.isoformat() if project.created_at else None,
    )


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
            "project.create",
            "",
            payload.idempotency_key or "",
            request_fingerprint("project.create", payload.model_dump(mode="json")),
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
            ai_mode=payload.automation_mode.value
            if payload.automation_mode
            else "auto",
            canvas_profile=payload.canvas_profile.value
            if payload.canvas_profile
            else "landscape_16_9",
            review_policy=payload.review_policy.value
            if payload.review_policy
            else "none",
            mask_enabled=payload.mask_enabled,
            production_mode=payload.production_mode.value
            if payload.production_mode
            else "guided",
            presentation_mode=payload.presentation_mode.value
            if payload.presentation_mode
            else "full_frame",
            config_package_id=payload.config_package_id,
            config_package_version=payload.config_package_version,
            config_overrides=payload.config_overrides,
            course_id=payload.course_id,
            chapter_id=payload.chapter_id,
        )
        result = service.create(internal_payload, db)
        project_id = result.get("project", {}).get("id", "")
        project = (
            db.query(Project)
            .filter(
                Project.id == project_id,
                Project.account_id == get_current_account_id(),
            )
            .first()
        )

        response = ProjectCreateResult(
            project=_project_summary(project),
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
    query = db.query(Project).filter(Project.account_id == get_current_account_id())
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
            "project.update",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "project.update", payload.model_dump(mode="json"), project_id=project_id
            ),
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
        edits = payload.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"expected_revision", "idempotency_key"},
        )
        if all(getattr(project, key) == value for key, value in edits.items()):
            response = ProjectUpdateResult(
                project=_project_summary(project), updated=False
            ).model_dump()
            idempotency.finalize(claim.record_pk, True, response)
            return response
        AgentIdempotencyService.bump_revision(db, project)
        if payload.name is not None:
            project.name = payload.name
        if payload.description is not None:
            project.description = payload.description
        if payload.ai_mode is not None:
            project.ai_mode = payload.ai_mode
        if payload.production_mode is not None:
            project.production_mode = payload.production_mode.value
            if project.production_mode == "one_click":
                project.presentation_mode = "full_frame"
                project.mask_enabled = 0
        if payload.presentation_mode is not None:
            if (
                project.production_mode == "one_click"
                and payload.presentation_mode.value == "reveal"
            ):
                raise ValidationFailedError("一键生成仅支持整页展示")
            project.presentation_mode = payload.presentation_mode.value
            project.mask_enabled = 1 if project.presentation_mode == "reveal" else 0

        db.commit()
        db.refresh(project)

        response = ProjectUpdateResult(
            project=_project_summary(project),
            updated=True,
        ).model_dump()
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except IdempotencyConflictError as e:
        db.rollback()
        idempotency.finalize(claim.record_pk, False, None)
        raise ConflictError(str(e), details=e.details)
    except Exception:
        db.rollback()
        idempotency.finalize(claim.record_pk, False, None)
        raise


@router.delete("/projects/{project_id}")
def agent_delete_project(
    project_id: str,
    payload: Annotated[ProjectDeleteRequest, Query()],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a project and all its artifacts."""
    from project_service import get_project_service

    idempotency = get_idempotency_service()
    try:
        claim = idempotency.claim(
            # Bind a logical delete key once per account/capability. The target
            # is in the fingerprint, so reusing it for another project conflicts.
            "project.delete", "", payload.idempotency_key or "",
            request_fingerprint("project.delete", payload.model_dump(mode="json"), project_id=project_id),
        )
    except IdempotencyConflictError as exc:
        raise ConflictError(str(exc), details=exc.details) from exc
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay
    try:
        project = _resolve_project(db, project_id)
        AgentIdempotencyService.check_revision(project, payload.expected_revision)
        AgentIdempotencyService.bump_revision(db, project)
        result = get_project_service().delete(project_id, db)
        response = {"project_id": project_id, "deleted": True, "details": result}
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except IdempotencyConflictError as exc:
        db.rollback()
        idempotency.finalize(claim.record_pk, False, None)
        raise ConflictError(str(exc), details=exc.details) from exc
    except Exception:
        db.rollback()
        idempotency.finalize(claim.record_pk, False, None)
        raise


# ---- 影响决策与 AI 模式（分域扩展） ----

@router.get("/projects/{project_id}/impacts")
def agent_get_project_impacts(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from project_routes import get_project_impacts

    return get_project_impacts(project_id, db)


@router.get("/projects/{project_id}/impacts/storyboard-reuse-preview")
def agent_preview_storyboard_reuse(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from project_routes import preview_storyboard_reuse

    return preview_storyboard_reuse(project_id, db)


@router.put("/projects/{project_id}/impacts/reuse-storyboard")
def agent_confirm_storyboard_reuse(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from project_routes import confirm_storyboard_reuse

    return confirm_storyboard_reuse(project_id, payload.payload, db)


@router.put("/projects/{project_id}/impacts/decision")
def agent_update_impact_decision(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from project_routes import update_project_impact_decision

    return update_project_impact_decision(project_id, payload.payload, db)


@router.put("/projects/{project_id}/impacts/reuse-image")
def agent_confirm_storyboard_image_reuse(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from project_routes import confirm_storyboard_image_reuse

    return confirm_storyboard_image_reuse(project_id, payload.payload, db)


@router.get("/projects/{project_id}/ai-mode")
def agent_get_project_ai_mode(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from project_routes import get_project_service

    return get_project_service().get_ai_mode(project_id, db)


@router.put("/projects/{project_id}/ai-mode")
def agent_update_project_ai_mode(
    project_id: str,
    payload: AiModeUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from project_routes import AiModeUpdate, get_project_service

    body = {"ai_mode": payload.ai_mode}
    if payload.expected_revision is not None:
        body["expected_revision"] = payload.expected_revision
    return get_project_service().update_ai_mode(
        project_id, AiModeUpdate.model_validate(body), db
    )
