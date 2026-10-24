"""Agent images adapters to source-owned business services."""

from __future__ import annotations

from typing import Any
from fastapi import Depends
from sqlalchemy.orm import Session
from database import get_db
from agent_contract.models import ImageRegenerateRequest, ImageRegenerateResult
from agent_contract.artifacts import build_resource_uri
from agent_api.errors import ConflictError, OperationFailedError
from agent_api.fingerprints import request_fingerprint
from agent_idempotency_service import get_idempotency_service, IdempotencyConflictError
from fastapi import APIRouter

from agent_api.domain_routes.common import (
    _idempotency_replay_or_raise,
    _resolve_project,
    finalize_claim_failure,
)

router = APIRouter()


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
            "images.regenerate",
            project_id,
            payload.idempotency_key or "",
            request_fingerprint(
                "image.regenerate",
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
        from pipeline_services import get_project_pipeline_services

        services = get_project_pipeline_services(db, project_id)
        result = services.generate_image(slide_id, payload.instruction or "")
        revision = result.get("revision", 0)
    except Exception as e:
        finalize_claim_failure(claim, e)
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
