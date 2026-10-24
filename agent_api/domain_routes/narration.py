"""Agent narration adapters to source-owned business services."""

from __future__ import annotations

from typing import Any
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from agent_contract.models import (
    NarrationUpdateRequest,
    TtsSynthesizeRequest,
    TtsSynthesizeResult,
)
from agent_contract.operations import normalize_status
from agent_api.errors import (
    AgentAPIError,
    ValidationFailedError,
    ConflictError,
    OperationFailedError,
)
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
    finalize_claim_failure,
)

router = APIRouter()


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
            "narration.update",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "narration.update",
                payload.model_dump(mode="json"),
                project_id=project_id,
                slide_id=slide_id,
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
        idempotency.finalize(claim.record_pk, False, None, retryable=True)
        raise ConflictError(str(e), details=e.details)

    try:
        from pipeline_services import get_project_pipeline_services

        AgentIdempotencyService.bump_revision(db, project)
        services = get_project_pipeline_services(db, project_id)
        current = services.narration()
        beats = current.get("beats") if isinstance(current, dict) else None
        if not isinstance(beats, dict) or not isinstance(beats.get("slides"), list):
            raise ValidationFailedError(
                "Narration beats do not exist; initialize narration first"
            )

        updated = False
        for slide in beats["slides"]:
            if isinstance(slide, dict) and str(slide.get("slide_id") or "") == slide_id:
                if slide.get("tts_text") == payload.narration_text:
                    db.rollback()  # Release CAS without changing the version.
                    response = {
                        "project_id": project_id,
                        "slide_id": slide_id,
                        "updated": False,
                        "narration_text": payload.narration_text,
                        "revision": project.revision,
                    }
                    idempotency.finalize(claim.record_pk, True, response)
                    return response
                # tts_text is the canonical speech text consumed by the TTS
                # service.  Preserve all other beat metadata verbatim.
                slide["tts_text"] = payload.narration_text
                updated = True
                break
        if not updated:
            raise ValidationFailedError(
                f"Slide '{slide_id}' does not exist in narration beats"
            )

        # The source-owned service persists the payload and invalidates stale
        # audio/video state through the existing step-navigation lifecycle.
        services.save_narration(beats)

        db.commit()

        response = {
            "project_id": project_id,
            "slide_id": slide_id,
            "updated": True,
            "narration_text": payload.narration_text,
            "revision": project.revision,
        }
        idempotency.finalize(claim.record_pk, True, response)
        return response
    except IdempotencyConflictError as e:
        db.rollback()
        idempotency.finalize(claim.record_pk, False, None, retryable=True)
        raise ConflictError(str(e), details=e.details)
    except AgentAPIError as exc:
        db.rollback()
        finalize_claim_failure(claim, exc)
        raise
    except Exception as e:
        db.rollback()
        finalize_claim_failure(claim, e)
        raise OperationFailedError(f"Narration update failed: {e}")


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
            "tts.synthesize",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "tts.synthesize", payload.model_dump(mode="json"), project_id=project_id
            ),
        )
    except IdempotencyConflictError as e:
        raise ConflictError(str(e), details=e.details)
    replay = _idempotency_replay_or_raise(claim)
    if replay is not None:
        return replay

    try:
        from tts_service import get_tts_async_service

        result = get_tts_async_service().create_job(db, project_id, {})
    except HTTPException as exc:
        finalize_claim_failure(claim, exc)
        raise
    except Exception as e:
        finalize_claim_failure(claim, e)
        raise OperationFailedError(f"TTS synthesis failed: {e}")

    response = TtsSynthesizeResult(
        operation_id="job:" + result["job"]["id"],
        project_id=project_id,
        status=normalize_status(str(result["job"]["status"])).value,
        job_id=result["job"]["id"],
    ).model_dump()
    idempotency.finalize(claim.record_pk, True, response)
    return response
