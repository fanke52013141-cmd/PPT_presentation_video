"""Agent annotation-domain declarations: visible Step 6 勾画标注."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agent_contract.registry import AgentCapability, CapabilityStatus
from agent_contract.domains.freeform import FreeFormRequest


class AnnotationPromptsRequest(BaseModel):
    payload: Dict[str, Any] = Field(..., description="标注 Prompt 设置；由 annotation_service 校验")


class AnnotationPromptsGetRequest(BaseModel):
    slide_id: Optional[str] = Field(None, description="可选页面过滤")


CAPABILITIES = [
    AgentCapability(
        id="annotation.summary.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the project annotation summary: enable decision, per-slide revision and confirm state.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations",
        mcp_tool_name="ppt_annotation_summary_get", cli_command="annotation summary",
        service_ref="annotation_service.AnnotationService.get_summary",
    ),
    AgentCapability(
        id="annotation.settings.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update annotation settings including the enable/skip decision; commits with one database write.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/settings",
        mcp_tool_name="ppt_annotation_settings_update", cli_command="annotation settings --set",
        service_ref="annotation_service.AnnotationService.update_settings",
    ),
    AgentCapability(
        id="annotation.slide.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read one slide's structured annotation state and revision.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}",
        mcp_tool_name="ppt_annotation_slide_get", cli_command="annotation slide",
        service_ref="annotation_service.AnnotationService.get_slide",
    ),
    AgentCapability(
        id="annotation.slide.patch", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Apply a structured annotation patch (operations, undo) with revision-conflict handling; commits once.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PATCH", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}",
        mcp_tool_name="ppt_annotation_slide_patch", cli_command="annotation slide --patch",
        service_ref="annotation_service.AnnotationService.patch_slide",
    ),
    AgentCapability(
        id="annotation.text_layout.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read one slide's OCR text layout used for annotation anchoring.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/text-layout",
        mcp_tool_name="ppt_annotation_text_layout_get", cli_command="annotation text-layout",
        service_ref="annotation_service.AnnotationService.get_text_layout",
    ),
    AgentCapability(
        id="annotation.text_layout.patch", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Patch one slide's text layout; index units follow annotations_core conventions.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PATCH", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/text-layout",
        mcp_tool_name="ppt_annotation_text_layout_patch", cli_command="annotation text-layout --patch",
        service_ref="annotation_service.AnnotationService.patch_text_layout",
    ),
    AgentCapability(
        id="annotation.prompts.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read annotation prompts with an optional slide filter.",
        request_model=AnnotationPromptsGetRequest, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/prompts",
        mcp_tool_name="ppt_annotation_prompts_get", cli_command="annotation prompts",
        service_ref="annotation_service.AnnotationService.get_prompts",
    ),
    AgentCapability(
        id="annotation.prompts.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update annotation prompts.",
        request_model=AnnotationPromptsRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/prompts",
        mcp_tool_name="ppt_annotation_prompts_update", cli_command="annotation prompts --set",
        service_ref="annotation_service.AnnotationService.put_prompts",
    ),
    AgentCapability(
        id="annotation.slide.prepare", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Prepare one slide for annotation review (scene context binding).",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/prepare",
        mcp_tool_name="ppt_annotation_slide_prepare", cli_command="annotation prepare",
        service_ref="annotation_service.AnnotationService.prepare_slide",
    ),
    AgentCapability(
        id="annotation.slide.confirm", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Confirm one slide's annotations; the confirmation binds the reviewed revision and commits once.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/confirm",
        mcp_tool_name="ppt_annotation_slide_confirm", cli_command="annotation confirm",
        service_ref="annotation_service.AnnotationService.confirm_slide",
    ),
    AgentCapability(
        id="annotation.jobs.submit", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Submit an OCR/annotation planning job; poll via annotation.jobs.get or operation.get when durable.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/jobs",
        mcp_tool_name="ppt_annotation_jobs_submit", cli_command="annotation submit",
        service_ref="annotation_service.AnnotationService.submit_job",
        long_running=True,
    ),
    AgentCapability(
        id="annotation.jobs.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read one annotation job by id; ownership is validated against the account.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/jobs/{job_id}",
        mcp_tool_name="ppt_annotation_jobs_get", cli_command="annotation job",
        service_ref="annotation_service.AnnotationService.get_job",
    ),
    AgentCapability(
        id="annotation.jobs.cancel", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Request cancellation of one annotation job at a safe boundary.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/jobs/{job_id}/cancel",
        mcp_tool_name="ppt_annotation_jobs_cancel", cli_command="annotation cancel",
        service_ref="annotation_service.AnnotationService.cancel_job",
    ),
    AgentCapability(
        id="annotation.preview.export", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Export an annotation preview video for one slide; returns a token addressable by the download transport.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/export-preview",
        mcp_tool_name="ppt_annotation_preview_export", cli_command="annotation export-preview",
        service_ref="annotation_service.AnnotationService.export_preview",
        long_running=True,
    ),
    AgentCapability(
        id="annotation.scene_asset.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download one prepared scene asset as binary PNG content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/scene-assets/{asset}",
        mcp_tool_name="ppt_annotation_scene_asset_get", cli_command="annotation scene-asset",
        service_ref="annotation_service.AnnotationService.preview_scene_asset",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="annotation.editor_ink.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download one editor ink stroke as binary PNG content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/editor-inks/{annotation_id}/{stroke_index}",
        mcp_tool_name="ppt_annotation_editor_ink_get", cli_command="annotation editor-ink",
        service_ref="annotation_service.AnnotationService.annotation_editor_ink",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="annotation.ink.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download one rendered annotation ink frame as binary PNG content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/inks/{build_id}/{annotation_id}/{stroke_index}/{frame_index}",
        mcp_tool_name="ppt_annotation_ink_get", cli_command="annotation ink",
        service_ref="annotation_service.AnnotationService.annotation_asset",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="annotation.preview.download", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download one exported annotation preview MP4 by token as binary content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/annotations/slides/{slide_id}/export-previews/{token}",
        mcp_tool_name="ppt_annotation_preview_download", cli_command="annotation preview",
        service_ref="annotation_service preview_exports",
        transport="binary",
        mcp_enabled=False,
    ),
]
