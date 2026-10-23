"""Agent output-domain declarations: visible Step 8 video, PPTX and subtitles."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agent_contract.registry import AgentCapability, CapabilityStatus


class VideoSpeedRequest(BaseModel):
    payload: Dict[str, Any] = Field(..., description="变速参数（如 speed 倍数）")


class VideoListResult(BaseModel):
    success: bool = True
    videos: List[Dict[str, Any]] = []


class VideoStatusResult(BaseModel):
    success: bool = True
    status: Optional[str] = None
    video: Optional[Dict[str, Any]] = None


class PptxReadinessResult(BaseModel):
    success: bool = True
    ready: bool = False
    blockers: List[str] = []


class PptxJobListResult(BaseModel):
    success: bool = True
    jobs: List[Dict[str, Any]] = []


class PptxJobResult(BaseModel):
    success: bool = True
    job: Dict[str, Any]


class PptxExportsResult(BaseModel):
    success: bool = True
    exports: List[Dict[str, Any]] = []


class SubtitleReadinessResult(BaseModel):
    success: bool = True
    ready: bool = False
    blockers: List[str] = []


class PptxJobsListRequest(BaseModel):
    job_type: Optional[str] = Field(None, description="按任务类型过滤")


CAPABILITIES = [
    AgentCapability(
        id="video.list", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="List rendered videos with freshness metadata; exact artifacts are addressed via artifacts.list.",
        request_model=BaseModel, response_model=VideoListResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/videos",
        mcp_tool_name="ppt_video_list", cli_command="video list",
        service_ref="video_render_service.VideoRenderService.list_videos",
    ),
    AgentCapability(
        id="video.download", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download one rendered MP4 by filename as binary content (FileResponse stream, not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/videos/{filename}/content",
        mcp_tool_name="ppt_video_download", cli_command="video download",
        service_ref="video_render_service.VideoRenderService.video_download",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="video.status.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the final-video status including the current rendered artifact reference.",
        request_model=BaseModel, response_model=VideoStatusResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/video/status",
        mcp_tool_name="ppt_video_status_get", cli_command="video status",
        service_ref="video_render_service.VideoRenderService.final_video_status",
    ),
    AgentCapability(
        id="video.speed", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Create a speed-adjusted MP4 variant of one rendered video; the new file is registered in the artifact registry.",
        request_model=VideoSpeedRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/videos/{filename}/speed",
        mcp_tool_name="ppt_video_speed", cli_command="video speed",
        service_ref="video_render_service.VideoRenderService.create_speed_adjusted_video",
        long_running=True,
    ),
    AgentCapability(
        id="video.delete", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Delete one rendered MP4 together with its .render.json sidecar and artifact record. Destructive and irreversible.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/projects/{project_id}/videos/{filename}",
        mcp_tool_name="ppt_video_delete", cli_command="video delete",
        service_ref="video_render_service.VideoRenderService.delete_video",
        destructive=True,
    ),
    AgentCapability(
        id="pptx.readiness", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read image-only PPTX export readiness and its blockers.",
        request_model=BaseModel, response_model=PptxReadinessResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/readiness",
        mcp_tool_name="ppt_pptx_readiness", cli_command="pptx readiness",
        service_ref="pptx_service.PptxExportService.readiness",
    ),
    AgentCapability(
        id="pptx.export.create", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Submit a persistent image-only PPTX export job; returns a job id addressable via operation.get and pptx.jobs.get.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/exports",
        mcp_tool_name="ppt_pptx_export_create", cli_command="pptx export",
        service_ref="pptx_service.PptxExportService.create_export",
        long_running=True,
    ),
    AgentCapability(
        id="pptx.exports.list", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="List completed PPTX export artifacts.",
        request_model=BaseModel, response_model=PptxExportsResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/exports",
        mcp_tool_name="ppt_pptx_exports_list", cli_command="pptx exports",
        service_ref="pptx_service.PptxExportService.list_exports",
    ),
    AgentCapability(
        id="pptx.export.download", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download one PPTX export by artifact id as binary content (FileResponse stream, not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/exports/{artifact_id}/content",
        mcp_tool_name="ppt_pptx_export_download", cli_command="pptx download",
        service_ref="pptx_service.PptxExportService.download_export",
        transport="binary",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="pptx.exports.delete", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Delete one PPTX export artifact and its registry record. Destructive and irreversible.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/exports/{artifact_id}",
        mcp_tool_name="ppt_pptx_exports_delete", cli_command="pptx delete",
        service_ref="pptx_service.PptxExportService.delete_export",
        destructive=True,
    ),
    AgentCapability(
        id="pptx.jobs.list", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="List persistent PPTX/video export jobs with an optional job-type filter.",
        request_model=PptxJobsListRequest, response_model=PptxJobListResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/jobs",
        mcp_tool_name="ppt_pptx_jobs_list", cli_command="pptx jobs",
        service_ref="pptx_service.PptxExportService.list_jobs",
    ),
    AgentCapability(
        id="pptx.jobs.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read one persistent export job by id; never substitutes the latest job.",
        request_model=BaseModel, response_model=PptxJobResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/jobs/{job_id}",
        mcp_tool_name="ppt_pptx_jobs_get", cli_command="pptx job",
        service_ref="pptx_service.PptxExportService.get_job",
    ),
    AgentCapability(
        id="pptx.jobs.retry", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Retry one failed export job as a new persistent job.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/pptx/jobs/{job_id}/retry",
        mcp_tool_name="ppt_pptx_jobs_retry", cli_command="pptx retry",
        service_ref="pptx_service.PptxExportService.retry_job",
        long_running=True,
    ),
    AgentCapability(
        id="subtitles.readiness", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read merged SRT subtitle export readiness for the current slides.",
        request_model=BaseModel, response_model=SubtitleReadinessResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/subtitles/readiness",
        mcp_tool_name="ppt_subtitles_readiness", cli_command="subtitles readiness",
        service_ref="subtitle_export_service.subtitle_export_readiness",
    ),
    AgentCapability(
        id="subtitles.download", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Download the merged SRT subtitle file as text/srt binary content (not a JSON tool result).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/subtitles/content",
        mcp_tool_name="ppt_subtitles_download", cli_command="subtitles download",
        service_ref="subtitle_export_service.build_subtitle_export",
        transport="binary",
        mcp_enabled=False,
    ),
]
