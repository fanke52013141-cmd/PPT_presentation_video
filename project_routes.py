"""Explicit FastAPI routes for project lifecycle."""

from __future__ import annotations

from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from project_path_service import project_or_404
from project_impact_service import list_impacts, set_decision
from project_impact_service import resolve_impacts
from impact_source_version import impact_source_version
from artifact_fingerprint import sha256_file
from pipeline_lifecycle import read_json_file
from project_service import (
    AiModeUpdate,
    ProjectCreate,
    ProjectService,
    ProjectUpdate,
    get_project_service,
)


router = APIRouter()


@router.get("/api/projects/{project_id}/impacts")
def get_project_impacts(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    items = list_impacts(project.run_dir)
    from project_storage import slide_dir

    for item in items:
        if item.get("reason") == "storyboard_visual_changed" and "images" in item.get("affected", ()):
            slide_id = str(item.get("scope_id") or "")
            item["image_sha256"] = sha256_file(slide_dir(project.run_dir, slide_id) / "visual_draft.png")
        if item.get("reason") == "article_changed" and "storyboard" in item.get("affected", ()):
            root = Path(project.run_dir)
            item["article_sha256"] = sha256_file(root / "inputs" / "article.md")
            item["contract_sha256"] = sha256_file(root / "planning" / "visual_contract.json")
    return {"success": True, "items": items}


@router.get("/api/projects/{project_id}/impacts/storyboard-reuse-preview")
def preview_storyboard_reuse(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    root = Path(project.run_dir)
    article = root / "inputs" / "article.md"
    contract = root / "planning" / "visual_contract.json"
    if not article.is_file() or not contract.is_file():
        raise HTTPException(status_code=409, detail="文章或分镜不存在")
    from project_storage import safe_child

    payload = read_json_file(safe_child(project.run_dir, "planning", "visual_contract.json"))
    slides = payload.get("slides") if isinstance(payload, dict) else None
    return {
        "article": article.read_text(encoding="utf-8-sig"),
        "slides": [{"slide_id": str(slide.get("slide_id") or ""),
                    "title": str(slide.get("main_title") or "")}
                   for slide in slides if isinstance(slide, dict)] if isinstance(slides, list) else [],
        "article_sha256": sha256_file(article),
        "contract_sha256": sha256_file(contract),
    }


@router.put("/api/projects/{project_id}/impacts/reuse-storyboard")
def confirm_storyboard_reuse(
    project_id: str, payload: dict[str, Any], db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record a human decision that the existing storyboard still serves the article."""
    project = project_or_404(db, project_id)
    from pipeline_lifecycle import project_artifact_lock

    with project_artifact_lock(project.run_dir):
        root = Path(project.run_dir)
        version = str(payload.get("source_version") or "")
        current = next((item for item in list_impacts(project.run_dir)
                        if item.get("id") == "article_changed:project"), None)
        if (current is None or "storyboard" not in current.get("affected", ())
                or current.get("source_version") != version
                or impact_source_version(project.run_dir, "article_changed", "project") != version
                or sha256_file(root / "inputs" / "article.md") != payload.get("article_sha256")
                or sha256_file(root / "planning" / "visual_contract.json") != payload.get("contract_sha256")):
            raise HTTPException(status_code=409, detail="文章或分镜已变化，请刷新后重新核对")
        settled = resolve_impacts(project.run_dir, affected=("storyboard",), source_version=version)
    return {"success": True, "resolved": bool(settled)}


@router.put("/api/projects/{project_id}/impacts/decision")
def update_project_impact_decision(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    try:
        item = set_decision(
            project.run_dir,
            str(payload.get("impact_id") or ""),
            str(payload.get("decision") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="待处理影响不存在")
    return {"success": True, "item": item}


@router.put("/api/projects/{project_id}/impacts/reuse-image")
def confirm_storyboard_image_reuse(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Confirm one existing image against the current storyboard visual input."""
    project = project_or_404(db, project_id)
    slide_id = str(payload.get("slide_id") or "").strip()
    version = str(payload.get("source_version") or "").strip()
    image_hash = str(payload.get("image_sha256") or "").strip()
    if not slide_id or not version or not image_hash:
        raise HTTPException(status_code=400, detail="缺少页面、分镜版本或图片版本")
    from project_storage import slide_dir
    from pipeline_lifecycle import project_artifact_lock

    with project_artifact_lock(project.run_dir):
        current = next((item for item in list_impacts(project.run_dir)
                        if item.get("id") == f"storyboard_visual_changed:{slide_id}"), None)
        image = slide_dir(project.run_dir, slide_id) / "visual_draft.png"
        if (current is None or "images" not in current.get("affected", ())
                or current.get("source_version") != version
                or impact_source_version(project.run_dir, "storyboard_visual_changed", slide_id) != version
                or sha256_file(image) != image_hash):
            raise HTTPException(status_code=409, detail="分镜或图片已变化，请刷新后重新核对")
        settled = resolve_impacts(
            project.run_dir, affected=("images",), slide_ids=(slide_id,), source_version=version,
        )
        # 复用决策是用户对"现有图片仍代表当前画面"的显式确认:同步把逐页
        # provenance 哈希对齐到当前视觉投影,否则渲染门仍会按旧口径拒绝。
        from visual_provenance import confirm_reused_slide_image

        provenance_refreshed = confirm_reused_slide_image(project.run_dir, slide_id)
    return {"success": True, "resolved": bool(settled), "provenance_refreshed": provenance_refreshed}


@router.post("/api/projects")
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.create(payload, db)


@router.get("/api/projects")
def list_projects(
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> list[dict[str, Any]]:
    return service.list(db)


@router.get("/api/projects/{project_id}")
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.get(project_id, db)


@router.get("/api/projects/{project_id}/ai-mode")
def get_project_ai_mode(
    project_id: str,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, str]:
    return service.get_ai_mode(project_id, db)


@router.put("/api/projects/{project_id}/ai-mode")
def update_project_ai_mode(
    project_id: str,
    payload: AiModeUpdate,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.update_ai_mode(project_id, payload, db)


@router.put("/api/projects/{project_id}")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.update(project_id, payload, db)


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    service: ProjectService = Depends(get_project_service),
) -> dict[str, Any]:
    return service.delete(project_id, db)
