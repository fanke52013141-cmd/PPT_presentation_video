"""Agent digital_human adapters to source-owned business services."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from agent_contract.models import (
    DigitalHumanConfigPatch,
    DigitalHumanConfigResult,
    DigitalHumanConfigUpdateRequest,
    DigitalHumanHealthResult,
)
from fastapi import APIRouter

from agent_api.domain_routes.common import _resolve_project, raise_typed_http_error

router = APIRouter()


@router.get("/projects/{project_id}/digital-human/config")
def agent_get_digital_human_config(
    project_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """Read the same normalized configuration and media summary as the Web UI."""
    from digital_human_routes import get_dh_config

    try:
        return DigitalHumanConfigResult.model_validate(get_dh_config(project_id, db=db))
    except HTTPException as exc:
        raise_typed_http_error(exc)


def _patch_body(config: DigitalHumanConfigPatch) -> dict[str, Any]:
    """Serialize only supplied fields so omitted values keep their saved state."""
    return config.model_dump(exclude_unset=True, mode="json")


@router.patch("/projects/{project_id}/digital-human/config")
def agent_update_digital_human_config(
    project_id: str,
    payload: DigitalHumanConfigUpdateRequest,
    db: Session = Depends(get_db),
) -> DigitalHumanConfigResult:
    """Update the digital-human configuration through the shared writer."""
    project = _resolve_project(db, project_id)
    from digital_human_routes import update_digital_human_config_with_impact

    try:
        config = update_digital_human_config_with_impact(project, _patch_body(payload.config), db)
        db.commit()
        return DigitalHumanConfigResult(config=config)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/health")
def agent_digital_human_health(
    project_id: str,
    db: Session = Depends(get_db),
) -> DigitalHumanHealthResult:
    """Check digital-human service availability."""
    _resolve_project(db, project_id)
    try:
        from digital_human_client import get_digital_human_client

        client = get_digital_human_client()
        health = client.health()
    except Exception as exc:  # unavailable service is a state, not a transport error
        return DigitalHumanHealthResult(available=False, error=str(exc))
    return DigitalHumanHealthResult(
        available=True,
        model_ready=bool(health.get("model_ready")),
        portrait_model_ready=bool(health.get("portrait_model_ready")),
        comfyui_online=bool(health.get("comfyui_online")),
        default_motion_available=bool(health.get("default_motion_available")),
        inference_backend=str(health.get("inference_backend") or ""),
        health=health,
    )


@router.post("/projects/{project_id}/digital-human/generate-full")
def agent_digital_human_generate_full(
    project_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """Use the same full-audio generation service as the Web UI."""
    from digital_human_routes import generate_dh_full

    try:
        return generate_dh_full(project_id, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)
