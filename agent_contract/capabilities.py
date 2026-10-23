"""Capability registry — the single source of truth for Agent-facing operations.

Each AgentCapability records the complete relationship between:
- Business service (the existing pipeline operation)
- Agent API endpoint
- MCP tool name
- CLI command
- Request/response Pydantic models
- Stability status

When a new capability is added, register it here. The capability matrix
documentation, MCP tool schemas, and CLI help text are auto-generated from
this registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Type

from pydantic import BaseModel

from agent_contract.models import (
    ProjectCreateRequest, ProjectCreateResult,
    ProjectListRequest, ProjectListResult,
    ProjectGetResult, ProjectUpdateRequest, ProjectUpdateResult,
    SourceSetRequest, SourceSetResult,
    PipelineRunRequest, PipelineRunResult,
    PipelineStatusResult, PipelineResumeRequest,
    StageGetResult, NarrationUpdateRequest,
    ImageRegenerateRequest, ImageRegenerateResult,
    TtsSynthesizeRequest, TtsSynthesizeResult,
    VideoRenderRequest, VideoRenderResult,
    CheckpointApproveRequest, CheckpointResult,
    ArtifactsListRequest, ArtifactsListResult,
    DigitalHumanConfigUpdateRequest, DigitalHumanConfigResult,
    ArtifactGetResult,
    DiagnosticsResult,
    IdentityResult,
    CheckpointListResult,
    ProjectDeleteResult,
    GenerationControlResult, GenerationStopRequest, GenerationStopResult,
)
from agent_contract.operations import OperationResult, OperationListRequest, OperationListResult, OperationCancelResult


class CapabilityStatus(str, Enum):
    experimental = "experimental"
    stable = "stable"
    deprecated = "deprecated"
    removed = "removed"


@dataclass(frozen=True)
class AgentCapability:
    """Describes a single Agent-facing capability and its mappings."""

    id: str
    version: str
    status: CapabilityStatus
    description: str
    request_model: Type[BaseModel]
    response_model: Type[BaseModel]
    agent_api_method: str   # GET / POST / PATCH / DELETE
    agent_api_path: str    # e.g. /api/agent/v1/projects
    mcp_tool_name: str
    cli_command: str
    service_ref: str       # e.g. project_service.ProjectService.create
    # Some transport-specific capabilities (for example SSE streams) cannot
    # be represented as an MCP request/response tool invocation.
    mcp_enabled: bool = True
    destructive: bool = False
    long_running: bool = False
    replaced_by: Optional[str] = None
    # Increment even when only semantics (not JSON shape) change.
    behavior_version: str = "2"


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        id="operation.get", version="1.0", status=CapabilityStatus.stable,
        description="Read an exact durable job or pipeline run by operation_id; never substitute latest.",
        request_model=BaseModel, response_model=OperationResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/operations/{operation_id}",
        mcp_tool_name="ppt_operation_get", cli_command="operation get", service_ref="agent_operation_service.AgentOperationService.get",
    ),
    AgentCapability(
        id="operation.list", version="1.0", status=CapabilityStatus.stable,
        description="List project operations across durable jobs and pipeline history, with pagination.",
        request_model=OperationListRequest, response_model=OperationListResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/operations",
        mcp_tool_name="ppt_operation_list", cli_command="operation list", service_ref="agent_operation_service.AgentOperationService.list",
    ),
    AgentCapability(
        id="operation.cancel", version="1.0", status=CapabilityStatus.stable,
        description="Request exact TTS/video cancellation at a safe boundary. accepted does not imply cancelled; poll operation.get. Other producers explicitly report unsupported.",
        request_model=BaseModel, response_model=OperationCancelResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/operations/{operation_id}/cancel",
        mcp_tool_name="ppt_operation_cancel", cli_command="operation cancel", service_ref="agent_operation_service.AgentOperationService.cancel",
    ),
    AgentCapability(
        id='generation.status', version='1.0', status=CapabilityStatus.stable,
        description='Read the active cooperative generation control for a project stage. Controls are process-local; durable TTS/video results remain in their job APIs.',
        request_model=BaseModel, response_model=GenerationControlResult,
        agent_api_method='GET', agent_api_path='/api/agent/v1/projects/{project_id}/generation/{stage}/status',
        mcp_tool_name='ppt_generation_status', cli_command='generation status', service_ref='generation_control.status',
    ),
    AgentCapability(
        id='generation.stop', version='1.0', status=CapabilityStatus.stable,
        description='Request a safe-boundary stop for the exact active operation ID. In-flight provider requests and render stages finish before stopping.',
        request_model=GenerationStopRequest, response_model=GenerationStopResult,
        agent_api_method='POST', agent_api_path='/api/agent/v1/projects/{project_id}/generation/{stage}/stop',
        mcp_tool_name='ppt_generation_stop', cli_command='generation stop', service_ref='generation_control.request_stop',
    ),
    AgentCapability(
        id="identity.get",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Return the creative account and scopes associated with this Agent connection.",
        request_model=BaseModel,
        response_model=IdentityResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/identity",
        mcp_tool_name="ppt_identity_get",
        cli_command="identity",
        service_ref="agent_api.auth / account_service",
    ),
    AgentCapability(
        id="project.create",
        version="1.5",
        status=CapabilityStatus.stable,
        description="Create a project with canvas, production/presentation mode, versioned creation configuration, and optional course/chapter ownership.",
        request_model=ProjectCreateRequest,
        response_model=ProjectCreateResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects",
        mcp_tool_name="ppt_project_create",
        cli_command="project create",
        service_ref="project_service.ProjectService.create",
    ),
    AgentCapability(
        id="project.list",
        version="1.3",
        status=CapabilityStatus.stable,
        description="List all projects with optional status filter.",
        request_model=ProjectListRequest,
        response_model=ProjectListResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects",
        mcp_tool_name="ppt_project_list",
        cli_command="project list",
        service_ref="project_service.ProjectService.list",
    ),
    AgentCapability(
        id="project.get",
        version="1.2",
        status=CapabilityStatus.stable,
        description="Get project details including article/contract status, slide IDs, and mask mode.",
        request_model=BaseModel,
        response_model=ProjectGetResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}",
        mcp_tool_name="ppt_project_get",
        cli_command="project show",
        service_ref="project_service.ProjectService.get",
    ),
    AgentCapability(
        id="project.update",
        version="1.2",
        status=CapabilityStatus.stable,
        description="Update project name, description, AI mode, production mode, or presentation mode.",
        request_model=ProjectUpdateRequest,
        response_model=ProjectUpdateResult,
        agent_api_method="PATCH",
        agent_api_path="/api/agent/v1/projects/{project_id}",
        mcp_tool_name="ppt_project_update",
        cli_command="project update",
        service_ref="project_service.ProjectService.update",
    ),
    AgentCapability(
        id="source.set",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Set project source content — either direct article text or a topic for AI generation.",
        request_model=SourceSetRequest,
        response_model=SourceSetResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/source",
        mcp_tool_name="ppt_source_set",
        cli_command="source set",
        service_ref="article_service.import_article / generate_article_from_topic",
    ),
    AgentCapability(
        id="pipeline.run",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Start or resume the automated pipeline. Supports stop_at checkpoints.",
        request_model=PipelineRunRequest,
        response_model=PipelineRunResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/runs",
        mcp_tool_name="ppt_pipeline_run",
        cli_command="run start",
        service_ref="one_click_orchestrator.start_one_click",
        long_running=True,
    ),
    AgentCapability(
        id="pipeline.status",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Get current pipeline status including stage progress and blocking errors.",
        request_model=BaseModel,
        response_model=PipelineStatusResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/runs/latest",
        mcp_tool_name="ppt_pipeline_status",
        cli_command="run status",
        service_ref="one_click_orchestrator.get_one_click_status",
    ),
    AgentCapability(
        id="pipeline.resume",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Resume a paused or failed pipeline from the last checkpoint.",
        request_model=PipelineResumeRequest,
        response_model=PipelineRunResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/runs/latest/resume",
        mcp_tool_name="ppt_pipeline_resume",
        cli_command="run resume",
        service_ref="one_click_orchestrator.start_one_click",
        long_running=True,
    ),
    AgentCapability(
        id="pipeline.stream",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Stream real-time pipeline progress via Server-Sent Events (SSE).",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/runs/latest/stream",
        mcp_tool_name="ppt_pipeline_stream",
        mcp_enabled=False,
        cli_command="run stream",
        service_ref="agent_api.routes.agent_pipeline_stream",
        long_running=True,
    ),
    AgentCapability(
        id="checkpoint.approve",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Approve or reject a pipeline checkpoint to continue or halt.",
        request_model=CheckpointApproveRequest,
        response_model=CheckpointResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/checkpoints/{checkpoint}/approve",
        mcp_tool_name="ppt_checkpoint_approve",
        cli_command="approve",
        service_ref="one_click_orchestrator (stage gating)",
    ),
    AgentCapability(
        id="stage.get",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Get detailed data for a specific pipeline stage (storyboard, narration, etc.).",
        request_model=BaseModel,
        response_model=StageGetResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/stages/{stage}",
        mcp_tool_name="ppt_stage_get",
        cli_command="stage get",
        service_ref="various service read functions",
    ),
    AgentCapability(
        id="image.regenerate",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Regenerate a single slide image with optional modification instruction.",
        request_model=ImageRegenerateRequest,
        response_model=ImageRegenerateResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/images/{slide_id}/regenerate",
        mcp_tool_name="ppt_image_regenerate",
        cli_command="image regenerate",
        service_ref="image_workflow_service.generate_slide_image",
        long_running=True,
    ),
    AgentCapability(
        id="narration.update",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Update narration text for a specific slide.",
        request_model=NarrationUpdateRequest,
        response_model=BaseModel,
        agent_api_method="PATCH",
        agent_api_path="/api/agent/v1/projects/{project_id}/narration/{slide_id}",
        mcp_tool_name="ppt_narration_update",
        cli_command="narration update",
        service_ref="storyboard_service.update_narration",
    ),
    AgentCapability(
        id="tts.synthesize",
        version="2.0", behavior_version="2",
        status=CapabilityStatus.stable,
        description="Submit durable background TTS synthesis for the whole project. Returns operation_id for operation.get; slide_ids is not supported yet.",
        request_model=TtsSynthesizeRequest,
        response_model=TtsSynthesizeResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/tts",
        mcp_tool_name="ppt_tts_synthesize",
        cli_command="tts synthesize",
        service_ref="tts_service.TtsAsyncService.create_job",
        long_running=True,
    ),
    AgentCapability(
        id="video.render",
        version="2.0", behavior_version="2",
        status=CapabilityStatus.stable,
        description="Start video rendering for the project.",
        request_model=VideoRenderRequest,
        response_model=VideoRenderResult,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/videos/render",
        mcp_tool_name="ppt_video_render",
        cli_command="video render",
        service_ref="video_render_service.start_render",
        long_running=True,
    ),
    AgentCapability(
        id="artifacts.list",
        version="1.0",
        status=CapabilityStatus.stable,
        description="List all artifacts (images, audio, video, pptx) for a project.",
        request_model=ArtifactsListRequest,
        response_model=ArtifactsListResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/artifacts",
        mcp_tool_name="ppt_artifacts_list",
        cli_command="artifacts list",
        service_ref="database.ArtifactRecord",
    ),
    AgentCapability(
        id="artifact.get",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Get details and download URL for a specific artifact.",
        request_model=BaseModel,
        response_model=ArtifactGetResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}",
        mcp_tool_name="ppt_artifact_get",
        cli_command="artifact get",
        service_ref="database.ArtifactRecord",
    ),
    AgentCapability(
        id="diagnostics",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Get system diagnostics including API version, capabilities, and health checks.",
        request_model=BaseModel,
        response_model=DiagnosticsResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/diagnostics",
        mcp_tool_name="ppt_diagnostics",
        cli_command="diagnostics",
        service_ref="agent_api.routes.get_diagnostics",
    ),
    AgentCapability(
        id="digital_human.config.get",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Get digital-human configuration for a project.",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/config",
        mcp_tool_name="ppt_digital_human_config_get",
        cli_command="digital-human config",
        service_ref="digital_human_routes.router",
    ),
    AgentCapability(
        id="digital_human.config.update",
        version="1.1",
        status=CapabilityStatus.stable,
        description="Update digital-human configuration for a project.",
        request_model=DigitalHumanConfigUpdateRequest,
        response_model=DigitalHumanConfigResult,
        agent_api_method="PATCH",
        agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/config",
        mcp_tool_name="ppt_digital_human_config_update",
        cli_command="digital-human config --set",
        service_ref="digital_human_routes.router",
    ),
    AgentCapability(
        id="digital_human.health",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Check digital-human service availability and model readiness.",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/health",
        mcp_tool_name="ppt_digital_human_health",
        cli_command="digital-human health",
        service_ref="digital_human_client.get_digital_human_client",
    ),
    AgentCapability(
        id="digital_human.generate",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Trigger full digital-human video generation for all slides.",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="POST",
        agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/generate-full",
        mcp_tool_name="ppt_digital_human_generate",
        cli_command="digital-human generate",
        service_ref="digital_human_client.get_digital_human_client",
    ),
    AgentCapability(
        id="project.delete",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Delete a project and all of its derived artifacts. Destructive and irreversible.",
        request_model=BaseModel,
        response_model=ProjectDeleteResult,
        agent_api_method="DELETE",
        agent_api_path="/api/agent/v1/projects/{project_id}",
        mcp_tool_name="ppt_project_delete",
        cli_command="project delete",
        service_ref="project_service.ProjectService.delete",
        destructive=True,
    ),
    AgentCapability(
        id="checkpoint.list",
        version="1.0",
        status=CapabilityStatus.stable,
        description="List the pipeline checkpoints available for a project.",
        request_model=BaseModel,
        response_model=CheckpointListResult,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/checkpoints",
        mcp_tool_name="ppt_checkpoint_list",
        cli_command="checkpoint list",
        service_ref="agent_api.routes.agent_list_checkpoints",
    ),
    # ---- 二进制下载类能力：响应是 FileResponse 字节流而非 JSON 工具结果，
    # ---- 与 pipeline.stream 同理不能封装成 MCP 请求/响应工具，故
    # ---- mcp_enabled=False、response_model=BaseModel；传输特性以描述与
    # ---- CLI 下载命令表达。
    AgentCapability(
        id="image.get",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Download the current slide image as binary content (FileResponse stream; image/png or image/jpeg, not a JSON tool result).",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/slides/{slide_id}/image",
        mcp_tool_name="ppt_image_get",
        cli_command="image get",
        service_ref="image_workflow_service.get_slide_image_file",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="audio.get",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Download the current non-stale slide audio as binary content (FileResponse stream; audio/mpeg, not a JSON tool result).",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/slides/{slide_id}/audio",
        mcp_tool_name="ppt_audio_get",
        cli_command="audio get",
        service_ref="tts_service.get_slide_audio_file",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="video.latest",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Download the latest final rendered video as binary content (FileResponse stream; video/mp4, not a JSON tool result).",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/videos/latest",
        mcp_tool_name="ppt_video_latest",
        cli_command="video latest",
        service_ref="video_render_service final_video_download",
        mcp_enabled=False,
    ),
    AgentCapability(
        id="artifact.download",
        version="1.0",
        status=CapabilityStatus.stable,
        description="Download one database-tracked artifact by id as binary content (FileResponse stream; MIME from the artifact record, not a JSON tool result). This is the target of artifact.get download_url.",
        request_model=BaseModel,
        response_model=BaseModel,
        agent_api_method="GET",
        agent_api_path="/api/agent/v1/projects/{project_id}/artifacts/{artifact_id}/content",
        mcp_tool_name="ppt_artifact_download",
        cli_command="artifact download",
        service_ref="agent_api.routes.agent_download_artifact",
        mcp_enabled=False,
    ),
]


def get_capability(capability_id: str) -> AgentCapability:
    """Get a capability by ID. Raises ValueError if not found."""
    for cap in CAPABILITIES:
        if cap.id == capability_id:
            return cap
    raise ValueError(f"Unknown capability: {capability_id}")


def get_stable_capabilities() -> list[AgentCapability]:
    """Return only capabilities with 'stable' status."""
    return [c for c in CAPABILITIES if c.status == CapabilityStatus.stable]


def get_capability_by_mcp_tool(tool_name: str) -> AgentCapability:
    """Get a capability by its MCP tool name."""
    for cap in CAPABILITIES:
        if cap.mcp_tool_name == tool_name:
            return cap
    raise ValueError(f"Unknown MCP tool: {tool_name}")


# ---------------------------------------------------------------------------
# Capability ↔ review_policy dynamic linkage
# ---------------------------------------------------------------------------

# Capabilities whose relevance depends on the project's review_policy.
# ``active`` policies enable them; ``inactive`` means the policy has no
# checkpoints so the capability is a no-op.
_REVIEW_GATED_CAPABILITY_IDS = frozenset({
    "checkpoint.approve",
})

# Maps each review policy to the set of checkpoint names it uses.
# Must stay in sync with one_click_orchestrator._POLICY_CHECKPOINTS.
_POLICY_RELEVANCE: dict[str, frozenset[str]] = {
    "none": frozenset(),
    "images_and_video": frozenset({"image_review", "video_review"}),
    "all_stages": frozenset({
        "storyboard_review", "image_review", "mask_review",
        "narration_review", "audio_review", "video_review",
    }),
}

# Policy-level labels for capability relevance.
_RELEVANCE_ACTIVE = "active"
_RELEVANCE_INACTIVE = "inactive"
_RELEVANCE_ALWAYS = "always"


def _policy_relevance(capability_id: str, policy: str) -> str:
    """Return the policy relevance label for a capability under a given policy."""
    if capability_id not in _REVIEW_GATED_CAPABILITY_IDS:
        return _RELEVANCE_ALWAYS
    checkpoints = _POLICY_RELEVANCE.get((policy or "none").strip().lower(), frozenset())
    return _RELEVANCE_ACTIVE if checkpoints else _RELEVANCE_INACTIVE


def capabilities_for_policy(
    policy: str,
    *,
    stable_only: bool = True,
) -> list[dict[str, object]]:
    """Return capability summaries annotated with ``policy_relevance``.

    Each entry is a plain dict with ``id``, ``status``, ``description``,
    ``agent_api_method``, ``agent_api_path``, ``mcp_tool_name``,
    ``cli_command``, and ``policy_relevance``.

    *policy* is the project's ``review_policy`` value ("none",
    "images_and_video", or "all_stages").
    """
    normalized = (policy or "none").strip().lower()
    if normalized not in _POLICY_RELEVANCE:
        normalized = "none"

    source = get_stable_capabilities() if stable_only else list(CAPABILITIES)
    result: list[dict[str, object]] = []
    for cap in source:
        result.append({
            "id": cap.id,
            "status": cap.status.value,
            "description": cap.description,
            "agent_api_method": cap.agent_api_method,
            "agent_api_path": cap.agent_api_path,
            "mcp_tool_name": cap.mcp_tool_name,
            "cli_command": cap.cli_command,
            "policy_relevance": _policy_relevance(cap.id, normalized),
        })
    return result


def get_active_checkpoints(policy: str) -> list[str]:
    """Return the ordered checkpoint list for a given review policy."""
    normalized = (policy or "none").strip().lower()
    checkpoints = _POLICY_RELEVANCE.get(normalized, frozenset())
    return sorted(checkpoints)

