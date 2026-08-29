"""Explicit FastAPI routes for Step 2 storyboard planning."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
import storyboard_service as service


router = APIRouter()


@router.get("/api/step2-prompt-templates")
def get_step2_prompt_templates() -> dict[str, Any]:
    return service.get_step2_prompt_templates()


@router.get("/api/step2-prompt-templates/{template_id}")
def get_step2_prompt_template(template_id: str) -> dict[str, Any]:
    return service.get_step2_prompt_template(template_id)


@router.post("/api/step2-prompt-templates")
def save_step2_prompt_template(
    payload: Dict[str, Any],
) -> dict[str, Any]:
    return service.save_step2_prompt_template(payload)


@router.delete("/api/step2-prompt-templates/{template_id}")
def delete_step2_prompt_template(
    template_id: str,
) -> dict[str, Any]:
    return service.delete_step2_prompt_template(template_id)


@router.get("/api/storyboard-templates")
def get_storyboard_templates() -> dict[str, Any]:
    return service.get_storyboard_templates()


@router.post("/api/storyboard-templates")
def save_storyboard_template(
    payload: Dict[str, Any],
) -> dict[str, Any]:
    return service.save_storyboard_template(payload)


@router.delete("/api/storyboard-templates/{template_id}")
def delete_storyboard_template(
    template_id: str,
) -> dict[str, Any]:
    return service.delete_storyboard_template(template_id)


@router.get("/api/projects/{project_id}/steps/2/rules")
def get_step2_rules(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step2_rules(project_id, db)


@router.put("/api/projects/{project_id}/steps/2/rules")
def update_step2_rules(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_rules(project_id, payload, db)


@router.get("/api/projects/{project_id}/steps/2/prompts")
def get_step2_prompts(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step2_prompts(project_id, db)


@router.put("/api/projects/{project_id}/steps/2/prompts")
def update_step2_prompts(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_prompts(project_id, payload, db)


@router.post("/api/projects/{project_id}/steps/2/script/execute")
def execute_step2_script_plan(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.execute_step2_script_plan(
        project_id,
        db=db,
        payload=payload,
    )


@router.get("/api/projects/{project_id}/steps/2/script/result")
def get_step2_script_plan(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step2_script_plan(project_id, db)


@router.put("/api/projects/{project_id}/steps/2/script/result")
def update_step2_script_plan(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_script_plan(
        project_id,
        payload,
        db,
    )


@router.post("/api/projects/{project_id}/steps/2/visual/execute")
def execute_step2_visual_plan(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.execute_step2_visual_plan(project_id, db)


@router.get("/api/projects/{project_id}/steps/2/visual/result")
def get_step2_visual_plan(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step2_visual_plan(project_id, db)


@router.put("/api/projects/{project_id}/steps/2/visual/result")
def update_step2_visual_plan(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_visual_plan(
        project_id,
        payload,
        db,
    )


@router.post("/api/projects/{project_id}/steps/2/compose")
def compose_step2_visual_contract(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.compose_step2_visual_contract(project_id, db)


@router.post("/api/projects/{project_id}/steps/2/prompt-preview")
def get_step2_prompt_preview(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step2_prompt_preview(
        project_id,
        db=db,
        payload=payload,
    )


@router.post("/api/projects/{project_id}/steps/2/execute")
def execute_step2(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.execute_step2(project_id, db=db, payload=payload)


@router.get("/api/projects/{project_id}/steps/2/result")
def get_step2_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step2_result(project_id, db)


@router.post("/api/projects/{project_id}/steps/2/repair")
def repair_step2_result(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.repair_step2_result(project_id, db)


@router.put("/api/projects/{project_id}/steps/2/result")
def update_step2_result(
    project_id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_result(project_id, payload, db)


@router.post("/api/projects/{project_id}/steps/2/manual-skeleton")
def submit_step2_manual_skeleton(
    project_id: str,
    payload: service.ManualSkeletonPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.submit_step2_manual_skeleton(
        project_id,
        payload,
        db,
    )
