"""Agent article adapters to the source-owned Step 1 services."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agent_contract.models import (
    ArticleSettingsUpdateRequest,
    ArticleSourceUpdateRequest,
)
from database import get_db

from agent_api.domain_routes.common import _resolve_project

import article_service as service

router = APIRouter()


@router.get("/article/settings")
def agent_get_article_settings() -> dict[str, Any]:
    return service.get_article_generation_settings()


@router.put("/article/settings")
def agent_update_article_settings(payload: ArticleSettingsUpdateRequest) -> dict[str, Any]:
    return service.update_article_generation_settings(payload.model_dump())


@router.get("/projects/{project_id}/article")
def agent_get_article_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step1_result(_resolve_project(db, project_id))


@router.put("/projects/{project_id}/article")
def agent_update_article_result(
    project_id: str,
    payload: ArticleSourceUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _resolve_project(db, project_id)
    return service.update_step1_result(project, payload.model_dump(), db)
