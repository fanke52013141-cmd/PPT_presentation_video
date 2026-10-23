"""Agent digital_human adapters to source-owned business services."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from fastapi import Depends
from sqlalchemy.orm import Session
from database import get_db
from agent_contract.models import (
    DigitalHumanConfigUpdateRequest,
    DigitalHumanConfigResult,
)
from agent_api.errors import ValidationFailedError, OperationFailedError
from fastapi import APIRouter

from agent_api.domain_routes.common import _resolve_project

router = APIRouter()


@router.get("/projects/{project_id}/digital-human/config")
def agent_get_digital_human_config(
    project_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """Get the digital-human configuration for a project."""
    project = _resolve_project(db, project_id)
    config_path = Path(project.run_dir) / "planning" / "digital_human.json"
    if not config_path.is_file():
        return DigitalHumanConfigResult(config={"enabled": False, "configured": False})
    import json as _json

    data = _json.loads(config_path.read_text(encoding="utf-8"))
    return DigitalHumanConfigResult(config=data)


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
    """Trigger full digital-human generation for all slides."""
    project = _resolve_project(db, project_id)
    from visual_contract_service import read_contract_slide_ids

    slide_ids = read_contract_slide_ids(Path(project.run_dir))
    if not slide_ids:
        raise ValidationFailedError("No slides found in visual contract")
    try:
        from digital_human_client import (
            get_digital_human_client,
            DigitalHumanUnavailable,
        )

        client = get_digital_human_client()
    except Exception as e:
        raise OperationFailedError(f"Digital human service unavailable: {e}")

    results: list[dict[str, Any]] = []
    for slide_id in slide_ids:
        audio_path = Path(project.run_dir) / "slides" / slide_id / "voice.mp3"
        if not audio_path.is_file():
            results.append(
                {"slide_id": slide_id, "status": "skipped", "reason": "no audio"}
            )
            continue
        try:
            job = client.create_job(audio_path=str(audio_path), slide_id=slide_id)
            results.append({"slide_id": slide_id, "status": "submitted", "job": job})
        except DigitalHumanUnavailable as e:
            results.append({"slide_id": slide_id, "status": "failed", "error": str(e)})
        except Exception as e:
            results.append({"slide_id": slide_id, "status": "failed", "error": str(e)})
    return {"success": True, "results": results}
