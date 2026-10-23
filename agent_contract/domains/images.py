"""Agent image-domain declarations: Step 3 image workflow and generation requests."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agent_contract.registry import AgentCapability, CapabilityStatus
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest


class ImageRegenerateRequest(BaseModel):
    slide_id: str
    instruction: str = Field("", description="修改指令，如'更有冲击力'")
    idempotency_key: Optional[str] = None


class ImageRegenerateResult(BaseModel):
    slide_id: str
    artifact_id: str = ""
    resource_uri: str = ""
    revision: int = 0
    message: str = ""


class ImageGenerateRequest(BaseModel):
    slide_id: str
    prompt: str
    preview: bool = False
    disposition: str = Field("keep", description="keep 或 cleanup")
    expected_version: str = Field("", description="CAS 页面版本；不匹配则拒绝")
    idempotency_key: Optional[str] = Field(
        None, description="网络未知结果时复用同一键重放原结果，不会重复付费生成"
    )


class ImageDeleteRequest(BaseModel):
    disposition: str = "keep"
    expected_version: str = ""


CAPABILITIES = [
    AgentCapability(
        id="image.prompt_settings.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read project Step 3 image-generation prompt settings.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/image-prompt-settings",
        mcp_tool_name="ppt_image_prompt_settings_get", cli_command="image prompt-settings",
        service_ref="image_workflow_service.get_step3_prompt_settings",
    ),
    AgentCapability(
        id="image.prompt_settings.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update project Step 3 image-generation prompt settings.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/image-prompt-settings",
        mcp_tool_name="ppt_image_prompt_settings_update", cli_command="image prompt-settings --set",
        service_ref="image_workflow_service.update_step3_prompt_settings",
    ),
    AgentCapability(
        id="image.prompts.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the composed per-slide image-generation prompts.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/image-prompts",
        mcp_tool_name="ppt_image_prompts_get", cli_command="image prompts",
        service_ref="image_workflow_service.get_slide_prompts",
    ),
    AgentCapability(
        id="image.generate", version="1.1", behavior_version="2",
        status=CapabilityStatus.stable,
        description="Generate one slide image synchronously through the generation governor; keeps the raw source pair and registers downstream invalidation.",
        request_model=ImageGenerateRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/images/generate",
        mcp_tool_name="ppt_image_generate", cli_command="image generate",
        service_ref="image_workflow_service.generate_slide_image",
        long_running=True,
    ),
    AgentCapability(
        id="image.upload", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Upload one slide image as multipart/form-data (fields: slide_id, file, disposition, expected_version); the reply is JSON but the request is a file transport.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/images/upload",
        mcp_tool_name="ppt_image_upload", cli_command="image upload",
        service_ref="image_workflow_service.upload_slide_image",
        transport="file_upload",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="image.change_preview.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the registered downstream impact preview for replacing one slide image.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/images/{slide_id}/change-preview",
        mcp_tool_name="ppt_image_change_preview_get", cli_command="image change-preview",
        service_ref="image_workflow_service.get_slide_image_change_preview",
    ),
    AgentCapability(
        id="image.recovery.list", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="List archived image versions available for geometry reuse on one slide.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/images/{slide_id}/recovery",
        mcp_tool_name="ppt_image_recovery_list", cli_command="image recovery",
        service_ref="image_workflow_service.list_slide_image_recovery",
    ),
    AgentCapability(
        id="image.recovery.overlay", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download one archived image overlay as binary content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/images/{slide_id}/recovery/{archive_id}/overlay",
        mcp_tool_name="ppt_image_recovery_overlay", cli_command="image recovery-overlay",
        service_ref="image_workflow_service.image_recovery_overlay",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="image.geometry.reuse", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Reuse saved element geometry from an archived image for one slide.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/images/{slide_id}/reuse-geometry",
        mcp_tool_name="ppt_image_geometry_reuse", cli_command="image reuse-geometry",
        service_ref="image_workflow_service.reuse_slide_image_geometry",
    ),
    AgentCapability(
        id="image.candidate.apply", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Apply a generated candidate image to its slide; candidate identity and provenance are validated.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/images/apply-candidate",
        mcp_tool_name="ppt_image_candidate_apply", cli_command="image apply-candidate",
        service_ref="image_workflow_service.apply_slide_candidate",
    ),
    AgentCapability(
        id="image.candidate.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download the current slide candidate image as binary content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/images/{slide_id}/candidate",
        mcp_tool_name="ppt_image_candidate_get", cli_command="image candidate",
        service_ref="image_workflow_service.get_slide_candidate_file",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="image.download_all", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download all slide images as a ZIP byte stream (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/images/download",
        mcp_tool_name="ppt_image_download_all", cli_command="image download-all",
        service_ref="image_workflow_service.download_all_slide_images",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="image.delete_all", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Delete all slide images with registered downstream invalidation. Destructive and irreversible.",
        request_model=OptionalFreeFormRequest, response_model=BaseModel,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/projects/{project_id}/images",
        mcp_tool_name="ppt_image_delete_all", cli_command="image delete-all",
        service_ref="image_workflow_service.delete_all_slide_images",
        destructive=True,
    ),
    AgentCapability(
        id="image.delete", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Delete one slide image (query: disposition, expected_version CAS) with downstream invalidation. Destructive and irreversible.",
        request_model=ImageDeleteRequest, response_model=BaseModel,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/projects/{project_id}/images/{slide_id}",
        mcp_tool_name="ppt_image_delete", cli_command="image delete",
        service_ref="image_workflow_service.delete_slide_image",
        destructive=True,
    ),
    AgentCapability(
        id="image.list", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="List all slide image states including versions, candidates and confirmation state.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/images",
        mcp_tool_name="ppt_image_list", cli_command="image list",
        service_ref="image_workflow_service.get_all_images",
    ),
    AgentCapability(
        id="image.order.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update the slide image ordering payload.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/image-order",
        mcp_tool_name="ppt_image_order_update", cli_command="image order --set",
        service_ref="image_workflow_service.update_step3_image_order",
    ),
    AgentCapability(
        id="image.confirm", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Confirm Step 3 images; unblocks the mask and audio stages and validates completeness.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/images/confirm",
        mcp_tool_name="ppt_image_confirm", cli_command="image confirm",
        service_ref="image_workflow_service.confirm_images",
    ),
]
