"""Agent system adapters to source-owned business services."""

from __future__ import annotations

from typing import Any
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import get_db, Project, ArtifactRecord
from account_context import get_current_account_id
from agent_contract.models import (
    DiagnosticsResult,
    IdentityResult,
    GenerationKind,
    GenerationControlResult,
    GenerationStopRequest,
    GenerationStopResult,
)
from agent_contract.versions import get_meta, get_contract_hash, AGENT_API_VERSION
from fastapi import APIRouter

from agent_api.domain_routes.common import _resolve_project

router = APIRouter()


@router.get(
    "/projects/{project_id}/generation/{stage}/status",
    response_model=GenerationControlResult,
)
def agent_generation_status(
    project_id: str, stage: GenerationKind, db: Session = Depends(get_db)
):
    import generation_control

    _resolve_project(db, project_id)
    return generation_control.status(project_id, stage)


@router.post(
    "/projects/{project_id}/generation/{stage}/stop",
    response_model=GenerationStopResult,
)
def agent_generation_stop(
    project_id: str,
    stage: GenerationKind,
    payload: GenerationStopRequest,
    db: Session = Depends(get_db),
):
    import generation_control

    _resolve_project(db, project_id)
    return generation_control.request_stop(project_id, stage, payload.operation_id)


@router.get("/meta")
def get_agent_meta() -> dict[str, Any]:
    """Return Agent API version, contract hash, and capability list."""
    return get_meta()


@router.get("/identity")
def get_agent_identity(
    request: Request, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Return the account identity selected by the Agent token/context."""
    from account_service import get_account

    account = get_account(db, get_current_account_id())
    return IdentityResult(
        account_id=account.id,
        account_name=account.name,
        scopes=sorted(getattr(request.state, "agent_scopes", set())),
        authenticated=bool(getattr(request.state, "agent_authenticated", False)),
    ).model_dump()


@router.get("/diagnostics")
def get_diagnostics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return system diagnostics for troubleshooting."""
    from agent_contract.capabilities import get_stable_capabilities

    account_id = get_current_account_id()
    project_count = db.query(Project).filter(Project.account_id == account_id).count()
    artifact_count = (
        db.query(ArtifactRecord)
        .join(Project, Project.id == ArtifactRecord.project_id)
        .filter(Project.account_id == account_id)
        .count()
    )

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
