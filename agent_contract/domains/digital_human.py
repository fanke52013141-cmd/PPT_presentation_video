"""Agent digital_human request and response contracts."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from agent_contract.registry import AgentCapability, CapabilityStatus
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest


class DigitalHumanConfigUpdateRequest(BaseModel):
    """Validated Agent transport envelope for the project digital-human config."""

    config: dict[str, Any] = Field(
        ...,
        description="Digital-human configuration patch. Only supported fields are persisted.",
    )


class DigitalHumanConfigResult(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


def _cap(**kwargs) -> AgentCapability:
    kwargs.setdefault("version", "1.0")
    kwargs.setdefault("behavior_version", "1")
    kwargs.setdefault("status", CapabilityStatus.stable)
    kwargs.setdefault("request_model", BaseModel)
    kwargs.setdefault("response_model", BaseModel)
    kwargs["mcp_tool_name"] = "ppt_" + kwargs["id"].replace(".", "_")
    kwargs.setdefault("destructive", False)
    kwargs.setdefault("long_running", False)
    return AgentCapability(**kwargs)


CAPABILITIES = [
    _cap(
        id="digital_human.slide.generate",
        description="Generate the digital-human presenter video for one slide (ComfyUI/Minimax backend per configuration).",
        request_model=OptionalFreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/generate",
        cli_command="digital-human generate-slide",
        service_ref="digital_human_routes.generate_dh",
        long_running=True,
    ),
    _cap(
        id="digital_human.jobs.get",
        description="Read one digital-human generation job by id.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/jobs/{job_id}",
        cli_command="digital-human job",
        service_ref="digital_human_routes.get_dh_job",
    ),
    _cap(
        id="digital_human.slide_video.get",
        description="Download one slide's digital-human video as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/video",
        cli_command="digital-human slide-video",
        service_ref="digital_human_routes.get_dh_slide_video",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.slide.compose",
        description="Compose the slide video with the digital-human presenter overlay.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/compose",
        cli_command="digital-human compose",
        service_ref="digital_human_routes.compose_dh_slide",
        long_running=True,
    ),
    _cap(
        id="digital_human.composite_video.get",
        description="Download one slide's composed digital-human overlay video as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/composite-video",
        cli_command="digital-human composite-video",
        service_ref="digital_human_routes.get_dh_composite_video",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.audio.export",
        description="Export the full digital-human narration audio for the project.",
        request_model=OptionalFreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/export-audio",
        cli_command="digital-human export-audio",
        service_ref="digital_human_routes.export_full_audio",
        long_running=True,
    ),
    _cap(
        id="digital_human.audio.file",
        description="Download the exported full audio file as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/export-audio/content",
        cli_command="digital-human audio",
        service_ref="digital_human_routes.get_full_audio",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.video.upload",
        description="Upload one digital-human presenter video (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/upload",
        cli_command="digital-human upload-video",
        service_ref="digital_human_routes.upload_dh_video",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.video.uploaded.get",
        description="Download the uploaded digital-human presenter video as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/upload/content",
        cli_command="digital-human uploaded-video",
        service_ref="digital_human_routes.get_dh_upload_video",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.avatars.upload",
        description="Upload one digital-human avatar image (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/avatars/upload",
        cli_command="digital-human upload-avatar",
        service_ref="digital_human_routes.upload_dh_avatar",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.avatars.list",
        description="List uploaded digital-human avatars.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/avatars",
        cli_command="digital-human avatars",
        service_ref="digital_human_routes.list_dh_avatars",
    ),
    _cap(
        id="digital_human.workflow.upload",
        description="Upload a ComfyUI workflow template for digital-human generation (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/workflow/upload",
        cli_command="digital-human upload-workflow",
        service_ref="digital_human_routes.upload_comfyui_workflow",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.workflow.get",
        description="Read the project ComfyUI workflow template state.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/workflow",
        cli_command="digital-human workflow",
        service_ref="digital_human_routes.get_comfyui_workflow",
    ),
]
