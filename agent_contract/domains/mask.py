"""Agent mask-domain declarations: AI Mask settings/annotation and the Step 5 editor."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agent_contract.registry import AgentCapability, CapabilityStatus
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest


class MaskResultUpdateRequest(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Step 5 Manifest 载荷；由 mask_manifest_service 校验")
    build_assets: bool = Field(True, description="保存后是否重建 Reveal 产物")


class MaskAnnotateRequest(BaseModel):
    settings: Optional[Dict[str, Any]] = Field(None, description="本次 AI Mask 覆盖设置")
    slide_ids: Optional[list[str]] = Field(None, description="限定处理的页面；缺省为全部页面")


CAPABILITIES = [
    AgentCapability(
        id="mask.settings.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the global AI Mask settings and migrated prompts.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/ai-mask/settings",
        mcp_tool_name="ppt_mask_settings_get", cli_command="mask settings",
        service_ref="ai_mask_config.ai_mask_config_payload",
    ),
    AgentCapability(
        id="mask.settings.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update the global AI Mask settings; recognized legacy defaults migrate, genuine custom prompts are preserved.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/ai-mask/settings",
        mcp_tool_name="ppt_mask_settings_update", cli_command="mask settings --set",
        service_ref="ai_mask_config.save_ai_mask_settings",
    ),
    AgentCapability(
        id="mask.annotate", version="1.1", behavior_version="2",
        status=CapabilityStatus.stable,
        description="Run automatic AI Mask annotation for the project (detection, semantic matching, exact RLE masks); honors the generation governor and cooperative stop signals.",
        request_model=MaskAnnotateRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/mask/annotate",
        mcp_tool_name="ppt_mask_annotate", cli_command="mask annotate",
        service_ref="ai_mask_service.AiMaskTaskService.annotate_project",
        long_running=True,
    ),
    AgentCapability(
        id="mask.semantic_blocks", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read or normalize the Step 5 semantic blocks derived from the Reveal Manifest.",
        request_model=OptionalFreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/mask/semantic-blocks",
        mcp_tool_name="ppt_mask_semantic_blocks", cli_command="mask semantic-blocks",
        service_ref="mask_manifest_service.semantic_blocks_project",
    ),
    AgentCapability(
        id="mask.result.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the stored Step 5 reveal manifest workspace result.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/mask",
        mcp_tool_name="ppt_mask_result_get", cli_command="mask show",
        service_ref="mask_manifest_service.get_step5_result",
    ),
    AgentCapability(
        id="mask.result.repair", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Explicitly repair the stored Step 5 manifest (stale groups, missing groups) instead of mutating on read.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/mask/repair",
        mcp_tool_name="ppt_mask_result_repair", cli_command="mask repair",
        service_ref="mask_manifest_service.repair_step5_result",
    ),
    AgentCapability(
        id="mask.draft.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Save the Step 5 draft workspace state; a content change registers the mask impact and commits.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/mask/draft",
        mcp_tool_name="ppt_mask_draft_update", cli_command="mask draft --set",
        service_ref="mask_manifest_service.update_step5_draft",
    ),
    AgentCapability(
        id="mask.result.update", version="1.1", behavior_version="2",
        status=CapabilityStatus.stable,
        description="Save the final Step 5 manifest; with build_assets=true exact reveal assets are rebuilt before any render.",
        request_model=MaskResultUpdateRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/mask",
        mcp_tool_name="ppt_mask_result_update", cli_command="mask save",
        service_ref="mask_manifest_service.update_step5_result",
    ),
    AgentCapability(
        id="mask.preview.build", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Build the exact single-slide mask preview and its report.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/mask/previews/{slide_id}",
        mcp_tool_name="ppt_mask_preview_build", cli_command="mask preview-build",
        service_ref="mask_preview_service.build_step5_mask_preview",
    ),
    AgentCapability(
        id="mask.preview.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download the current slide mask preview as binary PNG content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/mask/previews/{slide_id}/content",
        mcp_tool_name="ppt_mask_preview_get", cli_command="mask preview",
        service_ref="mask_preview_service.get_step5_mask_preview_path",
        transport="binary",
        mcp_enabled=False,
    ),
]
