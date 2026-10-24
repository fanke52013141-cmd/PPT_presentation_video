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


from pydantic import BaseModel

from agent_contract.registry import AgentCapability, CapabilityStatus  # noqa: F401  (re-exported)

from agent_contract.models import (
    ProjectStateResult,
    ProjectDeleteRequest,
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
    ArticleSettingsResult, ArticleSettingsUpdateRequest,
    ArticleSourceResult, ArticleSourceUpdateRequest,
    Step2PromptTemplateDetailResult, Step2PromptTemplateListResult,
    Step2PromptTemplateSaveRequest, Step2PromptTemplateSaveResult,
    StoryboardComposeResult, StoryboardContractGetResult,
    StoryboardContractRepairResult, StoryboardContractUpdateRequest,
    StoryboardContractWriteResult, StoryboardPreviewResult,
    StoryboardPromptsResult, StoryboardPromptsUpdateRequest,
    StoryboardRulesResult, StoryboardRulesUpdateRequest,
    StoryboardScriptExecuteRequest, StoryboardScriptPlanPayload,
    StoryboardScriptPlanResult, StoryboardSkeletonRequest,
    StoryboardSkeletonResult, StoryboardTemplateListResult,
    StoryboardTemplateSaveRequest, StoryboardTemplateSaveResult,
    StoryboardVisualPlanPayload, StoryboardVisualPlanResult,
)
from agent_contract.operations import OperationResult, OperationListRequest, OperationListResult, OperationCancelResult

# Historic inline declarations above; new domain declarations live in
# agent_contract/domains/* and are aggregated here so the registry keeps a
# single ordered capability list.
from agent_contract.domains.accounts import CAPABILITIES as ACCOUNTS_CAPABILITIES
from agent_contract.domains.annotations import CAPABILITIES as ANNOTATIONS_CAPABILITIES
from agent_contract.domains.audio import CAPABILITIES as AUDIO_CAPABILITIES
from agent_contract.domains.digital_human import CAPABILITIES as DIGITAL_HUMAN_CAPABILITIES
from agent_contract.domains.images import CAPABILITIES as IMAGES_CAPABILITIES
from agent_contract.domains.mask import CAPABILITIES as MASK_CAPABILITIES
from agent_contract.domains.outputs import CAPABILITIES as OUTPUTS_CAPABILITIES
from agent_contract.domains.project import CAPABILITIES as PROJECT_CAPABILITIES
from agent_contract.domains.style import CAPABILITIES as STYLE_CAPABILITIES
from agent_contract.domains.system import CAPABILITIES as SYSTEM_CAPABILITIES
from agent_contract.domains.workspace import CAPABILITIES as WORKSPACE_CAPABILITIES

_DOMAIN_CAPABILITIES = (
    AUDIO_CAPABILITIES
    + OUTPUTS_CAPABILITIES
    + IMAGES_CAPABILITIES
    + STYLE_CAPABILITIES
    + MASK_CAPABILITIES
    + ANNOTATIONS_CAPABILITIES
    + DIGITAL_HUMAN_CAPABILITIES
    + WORKSPACE_CAPABILITIES
    + SYSTEM_CAPABILITIES
    + PROJECT_CAPABILITIES
    + ACCOUNTS_CAPABILITIES
)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        id="project.state", version="1.0", status=CapabilityStatus.stable,
        description="Observe eight visible steps, saved internal statuses, source-owned artifact checks, resource hashes, annotation decision, optional presenter state, pending impacts and authorized candidate actions. Read-only; not a render-success guarantee or a global concurrency lock. Actions marked requires_input need additional schema-valid input.",
        request_model=BaseModel, response_model=ProjectStateResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/state",
        mcp_tool_name="ppt_project_state", cli_command="project state", service_ref="agent_workflow_service.inspect_project_state",
    ),
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
        version="1.4",
        behavior_version="3",
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
        transport="event_stream",
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
        version="2.1", behavior_version="3",
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
        version="1.1",
        behavior_version="3",
        status=CapabilityStatus.stable,
        description="List registered project artifacts with exact per-artifact resource URIs, never substituting the latest output. Hashes are computed by artifact.get.",
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
        version="1.1",
        behavior_version="3",
        status=CapabilityStatus.stable,
        description="Get exact artifact metadata, controlled download path and current SHA-256. Hash is null when its file is unavailable; no arbitrary file paths are accepted.",
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
        version="1.1",
        behavior_version="3",
        status=CapabilityStatus.stable,
        description="Delete a project and all derived artifacts with optional revision checking and account-scoped idempotent replay, including after deletion. Destructive and irreversible.",
        request_model=ProjectDeleteRequest,
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
        transport="binary",
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
        transport="binary",
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
        transport="binary",
    ),
    AgentCapability(
        id="artifact.download",
        version="1.1",
        behavior_version="3",
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
        transport="binary",
    ),
    # ---- 可见 Step 1：文章设置与结果编辑 ----
    AgentCapability(
        id="article.settings.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the global article-generation System Content prompt.",
        request_model=BaseModel, response_model=ArticleSettingsResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/article/settings",
        mcp_tool_name="ppt_article_settings_get", cli_command="article settings",
        service_ref="article_service.get_article_generation_settings",
    ),
    AgentCapability(
        id="article.settings.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Replace the global article-generation System Content prompt; blank content is rejected.",
        request_model=ArticleSettingsUpdateRequest, response_model=ArticleSettingsResult,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/article/settings",
        mcp_tool_name="ppt_article_settings_update", cli_command="article settings --set",
        service_ref="article_service.update_article_generation_settings",
    ),
    AgentCapability(
        id="article.result.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the project article source (title, summary, content). success=false with message when no article is imported yet.",
        request_model=BaseModel, response_model=ArticleSourceResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/article",
        mcp_tool_name="ppt_article_get", cli_command="article show",
        service_ref="article_service.get_step1_result",
    ),
    AgentCapability(
        id="article.result.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Replace the project article content; an identical save is a no-op without downstream invalidation, a changed save invalidates Step 2+ artifacts.",
        request_model=ArticleSourceUpdateRequest, response_model=ArticleSourceResult,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/article",
        mcp_tool_name="ppt_article_update", cli_command="article update",
        service_ref="article_service.update_step1_result",
    ),
    # ---- 可见 Step 2：模板管理 ----
    AgentCapability(
        id="storyboard.templates.list", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="List reusable storyboard structure templates (rules + profile YAML).",
        request_model=BaseModel, response_model=StoryboardTemplateListResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/storyboard/templates",
        mcp_tool_name="ppt_storyboard_templates_list", cli_command="storyboard templates",
        service_ref="storyboard_service.get_storyboard_templates",
    ),
    AgentCapability(
        id="storyboard.templates.save", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Create or update a storyboard template by name; built-in template names cannot be overwritten.",
        request_model=StoryboardTemplateSaveRequest, response_model=StoryboardTemplateSaveResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/storyboard/templates",
        mcp_tool_name="ppt_storyboard_templates_save", cli_command="storyboard template-save",
        service_ref="storyboard_service.save_storyboard_template",
    ),
    AgentCapability(
        id="storyboard.templates.delete", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Delete a custom storyboard template by id; built-in templates are rejected.",
        request_model=BaseModel, response_model=StoryboardTemplateListResult,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/storyboard/templates/{template_id}",
        mcp_tool_name="ppt_storyboard_templates_delete", cli_command="storyboard template-delete",
        service_ref="storyboard_service.delete_storyboard_template",
    ),
    AgentCapability(
        id="storyboard.prompt_templates.list", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="List reusable Step 2 prompt templates (script/visual system content and output example).",
        request_model=BaseModel, response_model=Step2PromptTemplateListResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/storyboard/prompt-templates",
        mcp_tool_name="ppt_step2_prompt_templates_list", cli_command="storyboard prompt-templates",
        service_ref="storyboard_service.get_step2_prompt_templates",
    ),
    AgentCapability(
        id="storyboard.prompt_templates.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read one Step 2 prompt template by id.",
        request_model=BaseModel, response_model=Step2PromptTemplateDetailResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/storyboard/prompt-templates/{template_id}",
        mcp_tool_name="ppt_step2_prompt_templates_get", cli_command="storyboard prompt-template",
        service_ref="storyboard_service.get_step2_prompt_template",
    ),
    AgentCapability(
        id="storyboard.prompt_templates.save", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Create or update a Step 2 prompt template; both prompt fields of the declared type are required and built-in names cannot be overwritten.",
        request_model=Step2PromptTemplateSaveRequest, response_model=Step2PromptTemplateSaveResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/storyboard/prompt-templates",
        mcp_tool_name="ppt_step2_prompt_templates_save", cli_command="storyboard prompt-template-save",
        service_ref="storyboard_service.save_step2_prompt_template",
    ),
    AgentCapability(
        id="storyboard.prompt_templates.delete", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Delete a custom Step 2 prompt template by id; built-in templates are rejected.",
        request_model=BaseModel, response_model=Step2PromptTemplateListResult,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/storyboard/prompt-templates/{template_id}",
        mcp_tool_name="ppt_step2_prompt_templates_delete", cli_command="storyboard prompt-template-delete",
        service_ref="storyboard_service.delete_step2_prompt_template",
    ),
    # ---- 可见 Step 2：项目规划配置 ----
    AgentCapability(
        id="storyboard.rules.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the project's custom storyboard rules, pipeline profile YAML, contract schema text and profile editor data.",
        request_model=BaseModel, response_model=StoryboardRulesResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/rules",
        mcp_tool_name="ppt_storyboard_rules_get", cli_command="storyboard rules",
        service_ref="storyboard_service.get_step2_rules",
    ),
    AgentCapability(
        id="storyboard.rules.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Replace the project's storyboard rules and/or pipeline profile YAML; omitted text falls back to the built-in defaults; profile_patch is applied after profile_yaml.",
        request_model=StoryboardRulesUpdateRequest, response_model=StoryboardRulesResult,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/rules",
        mcp_tool_name="ppt_storyboard_rules_update", cli_command="storyboard rules --set",
        service_ref="storyboard_service.update_step2_rules",
    ),
    AgentCapability(
        id="storyboard.prompts.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the project's effective Step 2 prompts, built-in defaults, legacy-contract compatibility flags and composed system contents.",
        request_model=BaseModel, response_model=StoryboardPromptsResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/prompts",
        mcp_tool_name="ppt_storyboard_prompts_get", cli_command="storyboard prompts",
        service_ref="storyboard_service.get_step2_prompts",
    ),
    AgentCapability(
        id="storyboard.prompts.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Replace Step 2 prompt fields; omitted fields reset to the built-in defaults.",
        request_model=StoryboardPromptsUpdateRequest, response_model=StoryboardPromptsResult,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/prompts",
        mcp_tool_name="ppt_storyboard_prompts_update", cli_command="storyboard prompts --set",
        service_ref="storyboard_service.update_step2_prompts",
    ),
    # ---- 可见 Step 2：两阶段规划与合约 ----
    AgentCapability(
        id="storyboard.script.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the stored Step 2A speech script plan and target-duration response.",
        request_model=BaseModel, response_model=StoryboardScriptPlanResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/script",
        mcp_tool_name="ppt_storyboard_script_get", cli_command="storyboard script",
        service_ref="storyboard_service.get_step2_script_plan",
    ),
    AgentCapability(
        id="storyboard.script.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Save a normalized speech script plan (manual edit); an empty slides list clears the storyboard chain; replanning effects are reported via workflow_changed/workflow_pending.",
        request_model=StoryboardScriptPlanPayload, response_model=StoryboardScriptPlanResult,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/script",
        mcp_tool_name="ppt_storyboard_script_update", cli_command="storyboard script --set",
        service_ref="storyboard_service.update_step2_script_plan",
    ),
    AgentCapability(
        id="storyboard.script.execute", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Run the Step 2A article-to-script LLM planning call synchronously; uses the configured LLM provider and the storyboard cooperative stop signal.",
        request_model=StoryboardScriptExecuteRequest, response_model=StoryboardScriptPlanResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/script/execute",
        mcp_tool_name="ppt_storyboard_script_execute", cli_command="storyboard script-execute",
        service_ref="storyboard_service.execute_step2_script_plan",
        long_running=True,
    ),
    AgentCapability(
        id="storyboard.visual.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the stored Step 2B visual plan and whether it is stale relative to the current script plan.",
        request_model=BaseModel, response_model=StoryboardVisualPlanResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/visual",
        mcp_tool_name="ppt_storyboard_visual_get", cli_command="storyboard visual",
        service_ref="storyboard_service.get_step2_visual_plan",
    ),
    AgentCapability(
        id="storyboard.visual.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Save a normalized visual plan (manual edit); narration fragments are re-bound deterministically from the stored script plan.",
        request_model=StoryboardVisualPlanPayload, response_model=StoryboardVisualPlanResult,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/visual",
        mcp_tool_name="ppt_storyboard_visual_update", cli_command="storyboard visual --set",
        service_ref="storyboard_service.update_step2_visual_plan",
    ),
    AgentCapability(
        id="storyboard.visual.execute", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Run the Step 2B script-to-visual LLM planning call synchronously; requires a stored script plan.",
        request_model=BaseModel, response_model=StoryboardVisualPlanResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/visual/execute",
        mcp_tool_name="ppt_storyboard_visual_execute", cli_command="storyboard visual-execute",
        service_ref="storyboard_service.execute_step2_visual_plan",
        long_running=True,
    ),
    AgentCapability(
        id="storyboard.compose", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Compose and persist the Visual Contract from the stored script and visual plans, run contract validation, and apply downstream invalidation; stale visual plans are rejected before any write.",
        request_model=BaseModel, response_model=StoryboardComposeResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/compose",
        mcp_tool_name="ppt_storyboard_compose", cli_command="storyboard compose",
        service_ref="storyboard_service.compose_step2_visual_contract",
        long_running=True,
    ),
    AgentCapability(
        id="storyboard.preview", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Compose the Step 2 LLM request preview (system/user content) from the article plus optional rule/profile overrides, without calling any model.",
        request_model=StoryboardRulesUpdateRequest, response_model=StoryboardPreviewResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/preview",
        mcp_tool_name="ppt_storyboard_preview", cli_command="storyboard preview",
        service_ref="storyboard_service.get_step2_prompt_preview",
    ),
    AgentCapability(
        id="storyboard.contract.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the normalized Visual Contract with its canonical SHA-256 CAS baseline and schema-repair hints; success=false before the first compose.",
        request_model=BaseModel, response_model=StoryboardContractGetResult,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/contract",
        mcp_tool_name="ppt_storyboard_contract_get", cli_command="storyboard contract",
        service_ref="storyboard_service.get_step2_result",
    ),
    AgentCapability(
        id="storyboard.contract.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Save the Visual Contract under CAS: pass the previously read contract_sha256 as expected_contract_sha256; a stale baseline returns 409 with zero side effects, an identical save is a no-op. Manual edits trigger validation, reveal/narration sync and registered downstream impacts.",
        request_model=StoryboardContractUpdateRequest, response_model=StoryboardContractWriteResult,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/contract",
        mcp_tool_name="ppt_storyboard_contract_update", cli_command="storyboard contract --set",
        service_ref="storyboard_service.update_step2_result",
    ),
    AgentCapability(
        id="storyboard.contract.repair", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Explicitly persist schema normalization of the stored contract instead of mutating on read; reports whether anything changed.",
        request_model=BaseModel, response_model=StoryboardContractRepairResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/contract/repair",
        mcp_tool_name="ppt_storyboard_contract_repair", cli_command="storyboard contract-repair",
        service_ref="storyboard_service.repair_step2_result",
    ),
    AgentCapability(
        id="storyboard.skeleton.submit", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Manual mode: build a Visual Contract from title + narration slides only (empty visual groups, static pages), set ai_mode=manual and finish Step 2.",
        request_model=StoryboardSkeletonRequest, response_model=StoryboardSkeletonResult,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/manual-skeleton",
        mcp_tool_name="ppt_storyboard_skeleton_submit", cli_command="storyboard skeleton",
        service_ref="storyboard_service.submit_step2_manual_skeleton",
    ),
    AgentCapability(
        id="storyboard.execute", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Legacy one-shot composite (script execute + visual execute + compose) kept in parity with the business route; Agents should prefer the two-phase storyboard.script/visual/compose flow which reports intermediate results.",
        request_model=StoryboardScriptExecuteRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/storyboard/execute",
        mcp_tool_name="ppt_storyboard_execute", cli_command="storyboard execute-legacy",
        service_ref="storyboard_service.execute_step2",
        long_running=True,
    ),
] + _DOMAIN_CAPABILITIES


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

