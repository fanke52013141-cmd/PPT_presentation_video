"""Agent digital_human adapters to source-owned business services."""

from __future__ import annotations

from typing import Any
from fastapi import Depends
from sqlalchemy.orm import Session
from database import get_db
from agent_contract.models import (
    DigitalHumanConfigUpdateRequest,
    DigitalHumanConfigResult,
)
from fastapi import APIRouter

from agent_api.domain_routes.common import _resolve_project

router = APIRouter()


@router.get("/projects/{project_id}/digital-human/config")
def agent_get_digital_human_config(
    project_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """Read the same normalized configuration and media summary as the Web UI."""
    from digital_human_routes import get_dh_config

    return DigitalHumanConfigResult.model_validate(get_dh_config(project_id, db=db))



@router.patch("/projects/{project_id}/digital-human/config")
def agent_update_digital_human_config(
    project_id: str,
    payload: DigitalHumanConfigUpdateRequest,
    db: Session = Depends(get_db),
) -> DigitalHumanConfigResult:
    """Update the digital-human configuration."""
    project = _resolve_project(db, project_id)
    from digital_human_routes import update_digital_human_config_with_impact

    config = update_digital_human_config_with_impact(project, payload.config, db)
    db.commit()
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
    """Use the same full-audio generation service as the Web UI."""
    from digital_human_routes import generate_dh_full

    return generate_dh_full(project_id, db=db)
