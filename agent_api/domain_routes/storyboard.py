"""Agent storyboard adapters to the source-owned Step 2 services.

每个适配器与对应业务路由调用同一服务函数，并保持完全相同的提交
（commit）语义；invoke 与分域 HTTP 走的就是这些函数。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agent_contract.models import (
    Step2PromptTemplateSaveRequest,
    StoryboardContractUpdateRequest,
    StoryboardPromptsUpdateRequest,
    StoryboardRulesUpdateRequest,
    StoryboardScriptExecuteRequest,
    StoryboardScriptPlanPayload,
    StoryboardSkeletonRequest,
    StoryboardTemplateSaveRequest,
    StoryboardVisualPlanPayload,
)
from database import get_db

import storyboard_service as service

router = APIRouter()


def _optional_body(payload: Optional[Any]) -> Optional[dict[str, Any]]:
    if payload is None:
        return None
    data = payload.model_dump(exclude_none=True)
    return data or None


# ---- 模板管理（全局资源） ----

@router.get("/storyboard/templates")
def agent_list_storyboard_templates() -> dict[str, Any]:
    return service.get_storyboard_templates()


@router.post("/storyboard/templates")
def agent_save_storyboard_template(payload: StoryboardTemplateSaveRequest) -> dict[str, Any]:
    return service.save_storyboard_template(payload.model_dump())


@router.delete("/storyboard/templates/{template_id}")
def agent_delete_storyboard_template(template_id: str) -> dict[str, Any]:
    return service.delete_storyboard_template(template_id)


@router.get("/storyboard/prompt-templates")
def agent_list_step2_prompt_templates() -> dict[str, Any]:
    return service.get_step2_prompt_templates()


@router.get("/storyboard/prompt-templates/{template_id}")
def agent_get_step2_prompt_template(template_id: str) -> dict[str, Any]:
    return service.get_step2_prompt_template(template_id)


@router.post("/storyboard/prompt-templates")
def agent_save_step2_prompt_template(payload: Step2PromptTemplateSaveRequest) -> dict[str, Any]:
    return service.save_step2_prompt_template(payload.model_dump())


@router.delete("/storyboard/prompt-templates/{template_id}")
def agent_delete_step2_prompt_template(template_id: str) -> dict[str, Any]:
    return service.delete_step2_prompt_template(template_id)


# ---- 项目规划配置 ----

@router.get("/projects/{project_id}/storyboard/rules")
def agent_get_step2_rules(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_step2_rules(project_id, db)


@router.put("/projects/{project_id}/storyboard/rules")
def agent_update_step2_rules(
    project_id: str,
    payload: StoryboardRulesUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_rules(project_id, payload.model_dump(), db)


@router.get("/projects/{project_id}/storyboard/prompts")
def agent_get_step2_prompts(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_step2_prompts(project_id, db)


@router.put("/projects/{project_id}/storyboard/prompts")
def agent_update_step2_prompts(
    project_id: str,
    payload: StoryboardPromptsUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_prompts(project_id, payload.model_dump(), db)


# ---- 两阶段规划 ----

@router.post("/projects/{project_id}/storyboard/script/execute")
def agent_execute_step2_script_plan(
    project_id: str,
    payload: StoryboardScriptExecuteRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = service.execute_step2_script_plan(
        project_id,
        db=db,
        payload=_optional_body(payload),
    )
    if result.get("workflow_changed"):
        db.commit()
    return result


@router.get("/projects/{project_id}/storyboard/script")
def agent_get_step2_script_plan(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_step2_script_plan(project_id, db)


@router.put("/projects/{project_id}/storyboard/script")
def agent_update_step2_script_plan(
    project_id: str,
    payload: StoryboardScriptPlanPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = service.update_step2_script_plan(project_id, payload.model_dump(), db)
    if result.get("workflow_changed"):
        db.commit()
    return result


@router.post("/projects/{project_id}/storyboard/visual/execute")
def agent_execute_step2_visual_plan(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.execute_step2_visual_plan(project_id, db)


@router.get("/projects/{project_id}/storyboard/visual")
def agent_get_step2_visual_plan(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_step2_visual_plan(project_id, db)


@router.put("/projects/{project_id}/storyboard/visual")
def agent_update_step2_visual_plan(
    project_id: str,
    payload: StoryboardVisualPlanPayload,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_step2_visual_plan(project_id, payload.model_dump(), db)


@router.post("/projects/{project_id}/storyboard/compose")
def agent_compose_step2_visual_contract(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.compose_step2_visual_contract(project_id, db)


@router.post("/projects/{project_id}/storyboard/preview")
def agent_get_step2_prompt_preview(
    project_id: str,
    payload: StoryboardRulesUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_step2_prompt_preview(project_id, db=db, payload=_optional_body(payload))


# ---- 合约读取与保存 ----

@router.get("/projects/{project_id}/storyboard/contract")
def agent_get_step2_result(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_step2_result(project_id, db)


@router.post("/projects/{project_id}/storyboard/contract/repair")
def agent_repair_step2_result(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.repair_step2_result(project_id, db)


@router.put("/projects/{project_id}/storyboard/contract")
def agent_update_step2_result(
    project_id: str,
    payload: StoryboardContractUpdateRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    body = dict(payload.contract)
    if payload.expected_contract_sha256:
        body["expected_contract_sha256"] = payload.expected_contract_sha256
    return service.update_step2_result(project_id, body, db)


@router.post("/projects/{project_id}/storyboard/manual-skeleton")
def agent_submit_step2_manual_skeleton(
    project_id: str,
    payload: StoryboardSkeletonRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.submit_step2_manual_skeleton(
        project_id,
        service.ManualSkeletonPayload.model_validate(payload.model_dump()),
        db,
    )


@router.post("/projects/{project_id}/storyboard/execute")
def agent_execute_step2(
    project_id: str,
    payload: StoryboardScriptExecuteRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.execute_step2(project_id, db=db, payload=_optional_body(payload))
